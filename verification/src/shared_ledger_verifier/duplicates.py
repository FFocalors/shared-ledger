"""Normalised duplicate detection for generated raw cases and scenarios.

Two generated cases can be different documents and still be the same test: the
refs get renamed, the titles get reworded, the scenario_id changes, and the
business structure underneath is identical.  Counting such cases separately
inflates coverage without adding evidence.

This module reduces both artefacts to a stable structural digest:

* :func:`scenario_fingerprint` maps every participant ref and operation ref to
  its *position*, then records only business-relevant fields, so renaming a
  participant or a ref does not change the digest.
* :func:`raw_case_fingerprint` keeps the event-type sequence and the multiset of
  numbers mentioned in the intents, ignoring the wording.

This is deliberately a simple, dependency-free digest rather than a similarity
model: it detects exact structural repeats, which is what a batch needs to
decide whether a case adds coverage.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _digest(material: Any) -> str:
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def scenario_fingerprint(document: dict[str, Any] | None) -> str | None:
    """Structural digest of a Scenario v1 document, blind to ref and title wording."""
    if not isinstance(document, dict) or "operations" not in document or "participants" not in document:
        return None
    participants = list(document.get("participants") or [])
    position = {name: index for index, name in enumerate(participants)}
    operations = list(document.get("operations") or [])
    op_position: dict[str, int] = {}
    for index, operation in enumerate(operations):
        if isinstance(operation, dict) and isinstance(operation.get("ref"), str):
            op_position[operation["ref"]] = index

    def participant(name: Any) -> Any:
        return position.get(name, name)

    def operation_ref(name: Any) -> Any:
        return op_position.get(name, name)

    canonical: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            canonical.append({"t": "?"})
            continue
        kind = operation.get("type")
        if kind in {"create_expense", "linked_refund"}:
            canonical.append({
                "t": kind,
                "amount": operation.get("amount"),
                "currency": operation.get("currency"),
                "payments": sorted((participant(k), v) for k, v in (operation.get("payments") or {}).items()),
                "split_method": operation.get("split_method"),
                "splits": sorted((participant(k), v) for k, v in (operation.get("splits") or {}).items()),
                "aa": sorted(participant(x) for x in (operation.get("aa_participants") or [])),
                "source": operation_ref(operation.get("original_expense_ref")),
            })
        elif kind in {"fifo_repayment", "targeted_repayment"}:
            canonical.append({
                "t": kind,
                "amount": operation.get("amount"),
                "currency": operation.get("currency"),
                "from": participant(operation.get("from_participant")),
                "to": participant(operation.get("to_participant")),
                "targets": sorted(operation_ref(x) for x in (operation.get("target_expense_refs") or [])),
            })
        elif kind in {"create_prepayment", "return_prepayment"}:
            canonical.append({
                "t": kind,
                "amount": operation.get("amount"),
                "currency": operation.get("currency"),
                "owner": participant(operation.get("owner_participant")),
                "custodian": participant(operation.get("custodian_participant")),
            })
        elif kind == "void_transfer":
            canonical.append({"t": kind, "voided": operation_ref(operation.get("transfer_ref"))})
        else:
            canonical.append({"t": kind})

    activity = document.get("activity") or {}
    return _digest({
        "activity": {
            "type": activity.get("type"),
            "base_currency": activity.get("base_currency"),
            "multi_currency_enabled": activity.get("multi_currency_enabled"),
        },
        "participants": len(participants),
        "operations": canonical,
    })


def raw_case_fingerprint(document: dict[str, Any] | None) -> str | None:
    """Structural digest of a raw case, blind to theme wording and intent phrasing."""
    if not isinstance(document, dict) or "events" not in document or "participants" not in document:
        return None
    events = list(document.get("events") or [])
    numbers: list[str] = []
    for event in events:
        if isinstance(event, dict):
            numbers.extend(_NUMBER.findall(str(event.get("intent", ""))))
    return _digest({
        "participants": len(document.get("participants") or []),
        "currency": document.get("currency"),
        "events": [event.get("type") if isinstance(event, dict) else "?" for event in events],
        "numbers": sorted(numbers),
    })


def mark_duplicates(records: Iterable[dict[str, Any]], *, key: str = "scenario_fingerprint",
                    id_key: str = "case_id", focus_key: str = "focus",
                    group_by_focus: bool = False) -> dict[str, str]:
    """Return ``{case_id: canonical_case_id}`` for every repeat, first seen wins.

    Records are expected in chronological order.  The first case carrying a
    given fingerprint is the canonical one and is absent from the result; later
    cases map to it and are ``DUPLICATE_CASE``.

    Deduplication is global by default: one business structure is one test,
    whichever focus label produced it, so the same scenario generated under two
    focus names still counts once.  Pass ``group_by_focus=True`` to keep a
    separate canonical case per focus instead.
    """
    seen: dict[tuple[str, ...], str] = {}
    duplicates: dict[str, str] = {}
    for record in records:
        fingerprint = record.get(key)
        if not fingerprint:
            continue
        identity = (
            (str(record.get(focus_key) or ""), str(fingerprint))
            if group_by_focus else (str(fingerprint),)
        )
        canonical = seen.get(identity)
        if canonical is None:
            seen[identity] = str(record.get(id_key) or "")
        else:
            duplicates[str(record.get(id_key) or "")] = canonical
    return duplicates


__all__ = ["mark_duplicates", "raw_case_fingerprint", "scenario_fingerprint"]
