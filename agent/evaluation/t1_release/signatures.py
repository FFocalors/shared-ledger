"""Operation-relevant signatures and prompt similarity for T1 release v2."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from difflib import SequenceMatcher
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def _current_activity(state: dict[str, Any]) -> dict[str, Any]:
    activities = state.get("activities", [])
    current_ref = state.get("current_activity_ref")
    if current_ref is not None:
        current = next((row for row in activities if row.get("ref") == current_ref), None)
        if current is not None:
            return current
    current = next((row for row in activities if row.get("role") == "current"), None)
    if current is not None:
        return current
    # No explicit anchor means there is no named current activity to preserve.
    return {}


def _permission_for(operation: str) -> str:
    return {
        "read.activities": "read.activities",
        "read.expenses": "read.expenses",
        "read.debts": "read.debts",
        "expense.create": "propose.expense.create",
        "expense.update": "propose.expense.update",
        "expense.presentation.update": "propose.expense.presentation.update",
    }[operation]


def _activity_anchor(state: dict[str, Any], operation: str, *, fields: tuple[str, ...]) -> dict[str, Any]:
    current = _current_activity(state)
    ref = current.get("ref")
    permissions = current.get("permissions", [])
    permission = _permission_for(operation)
    actor = state.get("actor", {})
    actor_permissions = actor.get("permissions", []) if isinstance(actor, dict) else []
    actor_matches_activity = actor.get("activity_ref") == ref if isinstance(actor, dict) else False
    return {
        "attributes": {key: current.get(key) for key in fields},
        "operation_permission": permission in permissions,
        # UserActivityMembership is an independent authorization fact. It is
        # deliberately not inferred from a Participant row or its role.
        "actor_member": bool(
            isinstance(actor, dict)
            and actor.get("authenticated") is True
            and actor.get("activity_member") is True
            and actor.get("activity_member_active") is True
            and actor_matches_activity
            and permission in actor_permissions
        ),
    }


def _is_readable_activity(activity: dict[str, Any], visible_statuses: set[str]) -> bool:
    return bool(
        activity.get("visible")
        and activity.get("status") in {"active", "archived"}
        and activity.get("status") in visible_statuses
    )


def _readable_expenses(state: dict[str, Any]) -> list[dict[str, Any]]:
    current = _current_activity(state)
    if not current:
        return []
    activities = {row.get("ref"): row for row in state.get("activities", [])}
    activity = activities.get(current.get("ref"), {})
    if not activity.get("visible") or activity.get("status") not in {"active", "archived"}:
        return []
    return [
        expense for expense in state.get("expenses", [])
        if expense.get("activity_ref") == current.get("ref")
        and expense.get("target_allowed", True) is True
    ]


def _canonical_graph(
    vertex_labels: list[tuple[Any, ...]],
    edges: list[tuple[int, int, str]],
) -> list[dict[str, Any]]:
    """Return an exact, ID-free canonical form for a small colored graph.

    Color refinement avoids exploring permutations in ordinary graphs; exact
    individualization resolves any remaining ties. Transposable twins and
    disconnected components are collapsed before branching, so large empty or
    repetitive structures do not trigger factorial work.
    """
    count = len(vertex_labels)
    if not count:
        return []
    weak: list[set[int]] = [set() for _ in range(count)]
    for source, target, label in edges:
        if source != target:
            weak[source].add(target)
            weak[target].add(source)

    components: list[list[int]] = []
    unseen = set(range(count))
    while unseen:
        start = min(unseen)
        queue = deque([start])
        unseen.remove(start)
        component = []
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbor in weak[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        components.append(component)

    def encode_component(component: list[int]) -> dict[str, Any]:
        local = {node: index for index, node in enumerate(component)}
        local_labels = [vertex_labels[node] for node in component]
        local_edges = [
            (local[source], local[target], label)
            for source, target, label in edges
            if source in local and target in local
        ]
        local_count = len(component)
        local_counter = Counter(local_edges)
        adjacency_local: list[dict[tuple[int, str], int]] = [defaultdict(int) for _ in range(local_count)]
        incoming_local: list[dict[tuple[int, str], int]] = [defaultdict(int) for _ in range(local_count)]
        for source, target, label in local_edges:
            adjacency_local[source][(target, label)] += 1
            incoming_local[target][(source, label)] += 1

        def partition(values: list[Any]) -> list[int]:
            keys = [canonical_json(value) for value in values]
            unique = {key for key in keys}
            ordered = {key: index for index, key in enumerate(sorted(unique))}
            return [ordered[key] for key in keys]

        def refine(colors: list[int]) -> list[int]:
            while True:
                signatures = []
                for node in range(local_count):
                    neighbors = Counter()
                    for (target, label), multiplicity in adjacency_local[node].items():
                        neighbors[("out", label, colors[target])] += multiplicity
                    for (source, label), multiplicity in incoming_local[node].items():
                        if source != node:
                            neighbors[("in", label, colors[source])] += multiplicity
                    signatures.append((colors[node], tuple(sorted(neighbors.items()))))
                ordered = sorted(set(signatures), key=lambda value: (value[0], canonical_json(value[1:])))
                labels = {signature: index for index, signature in enumerate(ordered)}
                updated = [labels[signature] for signature in signatures]
                if updated == colors:
                    return colors
                colors = updated

        def transposition_is_automorphism(left: int, right: int) -> bool:
            if local_labels[left] != local_labels[right]:
                return False
            def swap(node: int) -> int:
                if node == left:
                    return right
                if node == right:
                    return left
                return node
            return all(
                local_counter[(source, target, label)]
                == local_counter[(swap(source), swap(target), label)]
                for source, target, label in set(local_edges)
                | {(swap(source), swap(target), label) for source, target, label in local_edges}
            )

        edge_labels = sorted({label for _, _, label in local_edges})
        automorphism_cache: dict[tuple[tuple[int, ...], int, int], bool] = {}

        def automorphism_exists(left: int, right: int, base_colors: list[int]) -> bool:
            """Prove an exact color-preserving automorphism maps left to right.

            Paired color refinement is used only as a sound rejection/pruning
            step.  A positive result is returned only after a complete
            bijection has been checked against every directed labeled edge
            multiplicity, including loops.
            """
            if left == right:
                return True
            if local_labels[left] != local_labels[right] or base_colors[left] != base_colors[right]:
                return False
            cache_key = (tuple(base_colors), min(left, right), max(left, right))
            cached = automorphism_cache.get(cache_key)
            if cached is not None:
                return cached

            def refine_pair(mapping: dict[int, int]) -> tuple[list[int], list[int]] | None:
                # Marker numbers are paired across the source and destination
                # copies; sorting by source makes the refinement independent
                # of recursion/insertion order.
                ordered_pairs = sorted(mapping.items())
                source_markers = {source: index for index, (source, _) in enumerate(ordered_pairs)}
                target_markers = {target: index for index, (_, target) in enumerate(ordered_pairs)}

                def assign(values_left: list[Any], values_right: list[Any]) -> tuple[list[int], list[int]]:
                    values = values_left + values_right
                    ordered_values = sorted(
                        set(values),
                        key=lambda value: (value[0], canonical_json(value[1:])),
                    )
                    ordered = {
                        canonical_json(value): index for index, value in enumerate(ordered_values)
                    }
                    keys = [canonical_json(value) for value in values]
                    colors = [ordered[key] for key in keys]
                    return colors[:local_count], colors[local_count:]

                def same_partition(left_colors: list[int], right_colors: list[int]) -> bool:
                    forward: dict[int, int] = {}
                    reverse: dict[int, int] = {}
                    for left_color, right_color in zip(left_colors, right_colors):
                        if (left_color in forward and forward[left_color] != right_color
                                or right_color in reverse and reverse[right_color] != left_color):
                            return False
                        forward[left_color] = right_color
                        reverse[right_color] = left_color
                    return True

                seeds_left = [
                    (base_colors[node], local_labels[node], source_markers.get(node))
                    for node in range(local_count)
                ]
                seeds_right = [
                    (base_colors[node], local_labels[node], target_markers.get(node))
                    for node in range(local_count)
                ]
                colors_left, colors_right = assign(seeds_left, seeds_right)
                while True:
                    signatures_left = []
                    signatures_right = []
                    for colors, output in ((colors_left, signatures_left), (colors_right, signatures_right)):
                        for node in range(local_count):
                            neighbors = Counter()
                            for (target, label), multiplicity in adjacency_local[node].items():
                                neighbors[("out", label, colors[target])] += multiplicity
                            for (source, label), multiplicity in incoming_local[node].items():
                                neighbors[("in", label, colors[source])] += multiplicity
                            output.append((colors[node], tuple(sorted(neighbors.items()))))
                    updated_left, updated_right = assign(signatures_left, signatures_right)
                    if Counter(updated_left) != Counter(updated_right):
                        return None
                    if same_partition(
                        colors_left + colors_right, updated_left + updated_right
                    ):
                        return updated_left, updated_right
                    colors_left, colors_right = updated_left, updated_right

            fixed_refinement = refine_pair({left: right})
            if fixed_refinement is None:
                automorphism_cache[cache_key] = False
                return False
            fixed_left, fixed_right = fixed_refinement

            def exact_search(mapping: dict[int, int], used_targets: set[int]) -> bool:
                if len(mapping) == local_count:
                    if set(mapping.values()) != set(range(local_count)):
                        return False
                    if any(
                        local_labels[source] != local_labels[target]
                        or base_colors[source] != base_colors[target]
                        for source, target in mapping.items()
                    ):
                        return False
                    return Counter(
                        (mapping[source], mapping[target], label)
                        for source, target, label in local_edges
                    ) == local_counter

                best_source: int | None = None
                best_targets: list[int] | None = None
                for source in range(local_count):
                    if source in mapping:
                        continue
                    targets = [
                        target for target in range(local_count)
                        if target not in used_targets
                        and fixed_right[target] == fixed_left[source]
                    ]
                    if not targets:
                        return False
                    # Existing assignments already have unique paired colors,
                    # while these explicit checks cheaply reject edge conflicts.
                    compatible = []
                    for target in targets:
                        valid = all(
                            local_counter[(source, source, label)]
                            == local_counter[(target, target, label)]
                            for label in edge_labels
                        )
                        for mapped_source, mapped_target in mapping.items():
                            for label in edge_labels:
                                if local_counter[(source, mapped_source, label)] != local_counter[(target, mapped_target, label)]:
                                    valid = False
                                    break
                                if local_counter[(mapped_source, source, label)] != local_counter[(mapped_target, target, label)]:
                                    valid = False
                                    break
                            if not valid:
                                break
                        if valid:
                            compatible.append(target)
                    if not compatible:
                        return False
                    if best_targets is None or len(compatible) < len(best_targets):
                        best_source, best_targets = source, compatible
                        if len(best_targets) == 1:
                            break

                assert best_source is not None and best_targets is not None
                for target in best_targets:
                    mapping[best_source] = target
                    used_targets.add(target)
                    if exact_search(mapping, used_targets):
                        return True
                    used_targets.remove(target)
                    del mapping[best_source]
                return False

            result = exact_search({left: right}, {right})
            automorphism_cache[cache_key] = result
            return result

        best: bytes | None = None
        best_value: dict[str, Any] | None = None

        def search(colors: list[int]) -> None:
            nonlocal best, best_value
            colors = refine(colors)
            cells: dict[int, list[int]] = defaultdict(list)
            for node, color in enumerate(colors):
                cells[color].append(node)
            unresolved = [cell for cell in cells.values() if len(cell) > 1]
            if not unresolved:
                order = [node for node, _ in sorted(enumerate(colors), key=lambda item: item[1])]
                labels = [local_labels[node] for node in order]
                canonical_index = {node: index for index, node in enumerate(order)}
                canonical_edges = sorted(
                    (canonical_index[source], canonical_index[target], label)
                    for source, target, label in local_edges
                )
                value = {"vertices": labels, "edges": canonical_edges}
                encoded = canonical_json(value)
                if best is None or encoded < best:
                    best, best_value = encoded, value
                return
            cell = min(unresolved, key=lambda values: (len(values), colors[values[0]]))
            representatives: list[int] = []
            for candidate in cell:
                if any(
                    transposition_is_automorphism(candidate, seen)
                    or automorphism_exists(candidate, seen, colors)
                    for seen in representatives
                ):
                    continue
                representatives.append(candidate)
            for candidate in representatives:
                individualized = partition([
                    (colors[node], 0 if node == candidate else 1)
                    for node in range(local_count)
                ])
                search(individualized)

        initial = partition(local_labels)
        search(initial)
        assert best_value is not None
        return best_value

    canonical_components = [encode_component(component) for component in components]
    return sorted(canonical_components, key=canonical_json)


def _expense_graph(
    expenses: list[dict[str, Any]],
    *,
    include_currency: bool,
    include_locked: bool = True,
    include_title_groups: bool = False,
) -> list[dict[str, Any]]:
    """Anonymous expense/participant graph with optional visible title groups.

    When title grouping is enabled, only the equality partition among titles
    is encoded. Literal title text and expense references never enter the
    canonical labels; renaming every title therefore preserves the graph while
    merging or splitting same-title candidate groups changes it.
    """
    vertex_labels: list[tuple[Any, ...]] = []
    node_indices: dict[tuple[str, str], int] = {}
    pending_edges: list[tuple[tuple[str, str], tuple[str, str], str]] = []
    title_groups: dict[bytes, list[tuple[str, str]]] = defaultdict(list)
    title_group_size: dict[int, int] = {}
    if include_title_groups:
        indexed_groups: dict[bytes, list[int]] = defaultdict(list)
        for index, expense in enumerate(expenses):
            title = expense.get("title")
            if isinstance(title, str) and title:
                indexed_groups[canonical_json(title)].append(index)
        for members in indexed_groups.values():
            for index in members:
                title_group_size[index] = len(members)
    for index, expense in enumerate(expenses):
        expense_ref = str(expense.get("ref", f"expense-{index}"))
        key = ("expense", expense_ref)
        node_indices[key] = len(vertex_labels)
        label_parts: list[Any] = ["expense"]
        if include_currency:
            label_parts.append(expense.get("currency"))
        if include_locked:
            label_parts.append(expense.get("locked"))
        title = expense.get("title")
        if include_title_groups:
            group_size = title_group_size.get(index, 0)
            # Singleton equivalence classes have no relationships to encode;
            # folding their existence into the anonymous expense color keeps
            # them distinct from missing titles without adding a leaf vertex.
            label_parts.append("title_singleton" if group_size == 1 else (
                "title_repeated" if group_size > 1 else "title_absent"
            ))
        label = tuple(label_parts)
        vertex_labels.append(label)
        if include_title_groups and isinstance(title, str) and title:
            title_groups[canonical_json(title)].append(key)
        for participant_ref in expense.get("participant_refs", []):
            participant_key = ("participant", str(participant_ref))
            if participant_key not in node_indices:
                node_indices[participant_key] = len(vertex_labels)
                vertex_labels.append(("participant",))
            pending_edges.append((key, participant_key, "has_participant"))
    if include_title_groups:
        for title_key, expense_keys in title_groups.items():
            if len(expense_keys) < 2:
                continue
            group_key = ("title_group", title_key.hex())
            node_indices[group_key] = len(vertex_labels)
            vertex_labels.append(("title_group",))
            for expense_key in expense_keys:
                pending_edges.append((expense_key, group_key, "same_title"))
    edges = []
    for expense_key, participant_key, label in pending_edges:
        expense_node = node_indices[expense_key]
        participant_node = node_indices[participant_key]
        edges.append((expense_node, participant_node, label))
        edges.append((participant_node, expense_node, label))
    return _canonical_graph(vertex_labels, edges)


def _debt_graph(debts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = sorted({
        ref for debt in debts for ref in (debt.get("debtor_ref"), debt.get("creditor_ref"))
        if ref is not None
    })
    node_index = {ref: index for index, ref in enumerate(refs)}
    edges = [
        (node_index[debt["debtor_ref"]], node_index[debt["creditor_ref"]], str(debt.get("currency")))
        for debt in debts
    ]
    return _canonical_graph([("participant",)] * len(refs), edges)


def _visible_activity_facts(state: dict[str, Any]) -> list[dict[str, Any]]:
    statuses = set(state.get("visible_statuses", ["active", "archived"]))
    return [
        activity for activity in state.get("activities", [])
        if _is_readable_activity(activity, statuses)
    ]


def operation_state_projection(state: dict[str, Any], operation: str) -> dict[str, Any]:
    """Project only operation-relevant, model-visible pre-task state.

    Identifiers, presentation text, dates, raw monetary amounts, versions,
    scenario requests and financial update allocations never enter a family
    signature. Unnamed participant structure is canonicalized as an incidence
    graph, without enumerating all participant permutations.
    """
    if operation not in {
        "read.activities", "read.expenses", "read.debts", "expense.create",
        "expense.update", "expense.presentation.update",
    }:
        raise ValueError(f"unknown T1 operation: {operation}")
    current = _current_activity(state)
    current_ref = current.get("ref")

    if operation == "read.activities":
        visible = _visible_activity_facts(state)
        current_fact = {
            "kind": current.get("kind"),
            "status": current.get("status"),
            "base_currency": current.get("base_currency"),
            "visible": current.get("visible"),
            "in_visible_result": any(row.get("ref") == current_ref for row in visible),
        }
        other_facts = [
            (row.get("kind"), row.get("status"), row.get("base_currency"))
            for row in visible if row.get("ref") != current_ref
        ]
        return {
            "operation": operation,
            "current_activity": current_fact,
            "other_visible_activities": sorted(other_facts),
        }

    if operation == "expense.create":
        unit = state.get("ledger_unit", {})
        participant_rows = {row.get("ref"): row for row in state.get("participants", [])}
        activity_members = set(current.get("member_allowlist", []))
        allowed = set(unit.get("participant_allowlist", []))
        eligible = {
            ref for ref in allowed & activity_members
            if ref in participant_rows and participant_rows[ref].get("active") is True
        }
        unit_bound = unit.get("activity_ref") == current_ref
        unit_active = unit.get("active") is True
        return {
            "operation": operation,
            "activity": _activity_anchor(
                state, operation, fields=("kind", "status", "base_currency", "visible")
            ),
            "unit": {
                "bound_to_current_activity": unit_bound,
                "active": unit_active,
                "parent_active": unit.get("parent_active", True) is True,
                "currency": unit.get("currency"),
                "eligible_participant_count": len(eligible),
            },
        }

    if operation == "expense.update":
        unit = state.get("ledger_unit", {})
        expenses = [
            expense for expense in _readable_expenses(state)
            if expense.get("is_target") is True
        ]
        if len(expenses) > 1:
            raise ValueError("expense.update signature requires at most one established target")
        target = expenses[0] if expenses else {}
        target_projection = None if not expenses else {
            "currency": target.get("currency"),
            "locked": target.get("locked"),
            "participant_count": len(target.get("participant_refs", [])),
        }
        unit_ref = unit.get("ref")
        return {
            "operation": operation,
            "activity": _activity_anchor(
                state, operation, fields=("kind", "status", "base_currency", "visible")
            ),
            "unit_active": unit.get("active") is True,
            "unit_parent_active": unit.get("parent_active", True) is True,
            "target_bound_to_current_unit": bool(
                target and target.get("ledger_unit_ref", unit_ref) == unit_ref
            ),
            "target_expense": target_projection,
        }

    if operation == "expense.presentation.update":
        expenses = _readable_expenses(state)
        return {
            "operation": operation,
            "activity": _activity_anchor(state, operation, fields=("status", "visible")),
            "candidate_count": len(expenses),
            "candidate_facts": _expense_graph(
                expenses,
                include_currency=True,
                include_locked=False,
                include_title_groups=True,
            ),
        }

    if operation == "read.expenses":
        expenses = _readable_expenses(state)
        return {
            "operation": operation,
            "activity": _activity_anchor(
                state, operation, fields=("kind", "status", "base_currency", "visible")
            ),
            "expenses": _expense_graph(
                expenses, include_currency=True, include_title_groups=True
            ),
        }

    debts = [
        debt for debt in state.get("debts", [])
        if debt.get("activity_ref") == current_ref
        and current.get("visible")
        and current.get("status") in {"active", "archived"}
    ]
    return {
        "operation": operation,
        "activity": _activity_anchor(
            state, operation, fields=("kind", "status", "base_currency", "visible")
        ),
        "debts": _debt_graph(debts),
    }


def operation_state_signature(state: dict[str, Any], operation: str) -> str:
    return sha256(operation_state_projection(state, operation))


def scenario_projection(scenario: dict[str, Any]) -> dict[str, Any]:
    """Request/target conditions are separate from pre-task initial-state identity."""
    return scenario


def normalize_prompt(prompt: str) -> str:
    text = prompt.casefold()
    text = re.sub(r"\bparticipant_(?:selected|[0-9]{1,2})\b", "<participant>", text)
    text = re.sub(r"\bactivity_(?:selected|[0-9]{1,2})\b", "<activity>", text)
    text = re.sub(r"\bexpense_(?:selected|[0-9]{1,2})\b", "<expense>", text)
    text = re.sub(r"\b20[0-9]{2}[-/年][0-9]{1,2}[-/月][0-9]{1,2}日?\b", "<date>", text)
    text = re.sub(r"(?<![a-z])\d+(?:\.\d+)?", "<number>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def ngrams(text: str, n: int = 3) -> set[str]:
    padded = f"  {text}  "
    return {padded[i:i+n] for i in range(max(0, len(padded)-n+1))}


def prompt_similarity(left: str, right: str) -> tuple[float, float]:
    a, b = normalize_prompt(left), normalize_prompt(right)
    ga, gb = ngrams(a), ngrams(b)
    jac = len(ga & gb) / len(ga | gb) if ga or gb else 1.0
    return SequenceMatcher(None, a, b).ratio(), jac
