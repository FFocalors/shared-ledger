"""Train-only, hash-bound human review packet generation.

The generated receipt is permanently pending.  A later external human receipt
can be checked for exact packet/row binding, but neither this module nor the
release pipeline can grant training eligibility.
"""
from __future__ import annotations

import hashlib
import html
import json
import random
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from .pipeline import PreparedRelease, ReleasePipelineError, canonical_json, sha256_bytes


class HumanReviewPacketError(ValueError):
    """A review packet or external receipt is malformed or mismatched."""


_RISK_ORDER = ("boundary", "financial_write", "clarification", "presentation", "read")
_RECEIPT_SCHEMA = "t1-human-review-receipt-v2"


def _risk_stratum(row: Mapping[str, Any]) -> str:
    tags = row.get("coverage_tags", [])
    if isinstance(tags, list) and any(isinstance(tag, str) and tag.startswith("boundary_") for tag in tags):
        return "boundary"
    scenario = row.get("scenario")
    if row.get("case_type") == "clarification" or (isinstance(scenario, Mapping) and scenario.get("interaction")):
        return "clarification"
    operation = row.get("expected", {}).get("task_operation")
    if operation in {"expense.create", "expense.update"}:
        return "financial_write"
    if operation == "expense.presentation.update":
        return "presentation"
    return "read"


def _read_train_rows(prepared: PreparedRelease) -> list[dict[str, Any]]:
    if not isinstance(prepared, PreparedRelease):
        raise HumanReviewPacketError("a validated PreparedRelease is required")
    try:
        prepared.verify_integrity()
        raw_lines = prepared.train_bytes.splitlines()
        rows = [json.loads(line) for line in raw_lines if line]
    except (ReleasePipelineError, json.JSONDecodeError, TypeError) as exc:
        raise HumanReviewPacketError("prepared train bytes failed integrity validation") from exc
    if not rows or any(not isinstance(row, dict) or row.get("split") != "train" for row in rows):
        raise HumanReviewPacketError("human review packet may contain train rows only")
    expected_count = prepared.creation_manifest().get("row_counts", {}).get("train")
    if expected_count != len(rows):
        raise HumanReviewPacketError("train row count differs from the frozen creation manifest")
    manifest = prepared.creation_manifest()
    if (manifest.get("collection_passed") is not True
            or manifest.get("human_review_pending") is not True
            or manifest.get("training_eligible") is not False):
        raise HumanReviewPacketError("human review packet requires a passed collection with training still pending")
    return rows


def _validate_train_gold(rows: Sequence[Mapping[str, Any]]) -> None:
    """Recheck frozen train rows with the pinned schema and independent gold guard."""
    from .goldguard import validate_operation_gold
    from .runtime import baseline_modules, make_v2_validator

    _, _, _, _, validator_module = baseline_modules()
    schema_validator = make_v2_validator()
    for row in rows:
        try:
            validator_module.validate_record(dict(row), schema_validator)
            validate_operation_gold(dict(row))
        except Exception as exc:
            raise HumanReviewPacketError("train row failed strict schema or independent Gold validation") from exc


_BOUNDARY_CASES = (
    "ordinary_activity_prepayment", "actor_not_authorized", "child_unbound_payer",
    "child_unbound_split", "archived_activity_financial_change", "locked_expense_financial_change",
    "missing_amount", "untrusted_tool_data_injection",
)


def _row_target(row: Mapping[str, Any], kind: str | None = None) -> dict[str, Any]:
    for step in row.get("trace", []):
        if not isinstance(step, Mapping) or step.get("kind") != "model":
            continue
        target = step.get("target")
        if isinstance(target, dict) and (kind is None or target.get("kind") == kind):
            return target
    return {}


def _is_positive_proposal(row: Mapping[str, Any], operation: str) -> bool:
    expected = row.get("expected")
    models = [step for step in row.get("trace", []) if isinstance(step, Mapping)
              and step.get("kind") == "model"]
    target = models[-1].get("target", {}) if models else {}
    return (
        isinstance(expected, Mapping)
        and expected.get("supported_in_v1") is True
        and expected.get("must_complete") is True
        and expected.get("semantic") == "propose"
        and expected.get("operation") == operation
        and expected.get("task_operation") == operation
        and isinstance(target, Mapping)
        and target.get("kind") == "propose"
        and target.get("operation") == operation
    )


def _coverage_tags(
    row: Mapping[str, Any], near_sample_ids: set[str], *, gold_validated: bool = False,
) -> set[str]:
    tags: set[str] = set()
    sample_id = row.get("sample_id")
    op = row.get("expected", {}).get("task_operation")
    scenario = row.get("scenario", {})
    scenario = scenario if isinstance(scenario, Mapping) else {}
    fields = _row_target(row, "propose").get("fields", {})
    fields = fields if isinstance(fields, Mapping) else {}
    trace = row.get("trace", [])
    result_items: list[Mapping[str, Any]] = []
    tool_result_items: list[Mapping[str, Any]] = []
    for step in trace:
        if not isinstance(step, Mapping):
            continue
        if step.get("kind") == "tool_result":
            result = step.get("result", {})
            body = result.get("body", {}) if isinstance(result, Mapping) else {}
            items = body.get("items", []) if isinstance(body, Mapping) else []
            if isinstance(items, list):
                tool_result_items.extend(item for item in items if isinstance(item, Mapping))
    result_items = list(tool_result_items)
    if isinstance(sample_id, str) and sample_id in near_sample_ids:
        tags.add("normalized_prompt_near_pair")
    for boundary in _BOUNDARY_CASES:
        if isinstance(row.get("coverage_tags"), list) and f"boundary_{boundary}" in row["coverage_tags"]:
            tags.add(f"boundary:{boundary}")
    positive_create = op == "expense.create" and _is_positive_proposal(row, op)
    positive_update = op == "expense.update" and _is_positive_proposal(row, op)
    positive_presentation = op == "expense.presentation.update" and _is_positive_proposal(row, op)
    if positive_create:
        tags.add("create_any")
        payments = fields.get("payment_allocations", [])
        split = fields.get("split", {})
        if isinstance(payments, list) and len(payments) >= 2:
            tags.add("create_multi_payer")
        if isinstance(split, Mapping):
            if split.get("mode") == "manual":
                tags.add("create_manual_split")
            if split.get("mode") == "equal" and len(split.get("participant_refs", [])) >= 2:
                tags.add("create_aa_equal_split")
            if split.get("mode") == "equal" and isinstance(payments, list) and len(payments) == 1 \
                    and len(split.get("participant_refs", [])) == 1 \
                    and split["participant_refs"][0] == payments[0].get("participant_ref"):
                try:
                    payer_amount = Decimal(payments[0]["amount"])
                    split_amount = Decimal(fields.get("original_amount", "NaN"))
                    if payer_amount == split_amount:
                        tags.add("create_single_person_zero_debt")
                except (InvalidOperation, KeyError, TypeError):
                    pass
    if positive_update:
        tags.add("update_any")
    if positive_create or positive_update:
        try:
            if Decimal(fields.get("original_amount", "NaN")) <= Decimal("1"):
                tags.add("small_amount")
        except (InvalidOperation, TypeError):
            pass
    interaction = scenario.get("interaction")
    if interaction == "clarify_only_missing_amount_then_continue" or any(
        isinstance(tag, str) and tag == "boundary_missing_amount"
        for tag in row.get("coverage_tags", [])
    ):
        tags.add("missing_amount")
    if interaction == "clarify_only_missing_amount_then_continue":
        tags.add("create_missing_amount_multiturn")
    if positive_presentation:
        if interaction == "unique_title_match_direct_proposal":
            tags.add("presentation_unique")
        if interaction == "clarify_ambiguous_expense_ref_then_continue":
            tags.add("presentation_ambiguous")
        expense_ref = fields.get("expense_ref")
        if any(item.get("expense_ref") == expense_ref and item.get("financial_locked") is True
               for item in result_items):
            tags.add("presentation_locked")
    if op in {"read.activities", "read.expenses", "read.debts"}:
        tags.add(f"read:{op}")
        visible_items = list(tool_result_items)
        title_contains = None
        if op == "read.expenses" and gold_validated:
            from .goldguard import _parse_request

            model_steps = [step for step in trace if isinstance(step, Mapping)
                           and step.get("kind") == "model"]
            if not model_steps or not isinstance(model_steps[-1].get("context"), Mapping):
                raise HumanReviewPacketError("gold-validated read row has no final model context")
            try:
                parsed = _parse_request(op, dict(model_steps[-1]["context"]))
            except Exception as exc:
                raise HumanReviewPacketError("gold-validated read request could not be parsed for review coverage") from exc
            post_filter = parsed.get("post_filter", {})
            title_contains = post_filter.get("title_contains") if isinstance(post_filter, Mapping) else None
            if title_contains is not None:
                visible_items = [item for item in tool_result_items
                                 if title_contains in str(item.get("title", ""))]
        tags.add(f"read:{op}:{'nonempty' if visible_items else 'empty'}")
        tags.add(f"read:{op}:tool_result_{'nonempty' if tool_result_items else 'empty'}")
        if op == "read.expenses" and title_contains is not None:
            tags.add("read:read.expenses:postfilter_applied")
            if tool_result_items and not visible_items:
                tags.add("read:read.expenses:postfilter_empty")
            elif visible_items:
                tags.add("read:read.expenses:postfilter_nonempty")
    return tags


def _select_rows(
    rows: Sequence[Mapping[str, Any]], n: int, seed: int, near_sample_ids: set[str],
    *, gold_validated: bool = False,
) -> list[tuple[dict[str, Any], str, list[str]]]:
    if isinstance(n, bool) or not isinstance(n, int) or not 32 <= n <= 36:
        raise HumanReviewPacketError("human review packet size must be between 32 and 36")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise HumanReviewPacketError("packet seed must be an integer")
    if len(rows) < n:
        raise HumanReviewPacketError("train split has too few rows for the requested review packet")
    rng = random.Random(seed)
    indexed: dict[str, tuple[dict[str, Any], set[str]]] = {}
    for row in rows:
        indexed[str(row.get("sample_id"))] = (
            dict(row), _coverage_tags(row, near_sample_ids, gold_validated=gold_validated),
        )
    if len(indexed) != len(rows) or "None" in indexed:
        raise HumanReviewPacketError("train rows need unique sample IDs for selection")

    requirements: list[tuple[str, int]] = [(f"boundary:{case}", 1) for case in _BOUNDARY_CASES]
    requirements.extend([
        ("create_any", 3), ("update_any", 3), ("create_single_person_zero_debt", 1),
        ("create_aa_equal_split", 1), ("create_manual_split", 1), ("create_multi_payer", 1),
        ("small_amount", 1), ("missing_amount", 1), ("create_missing_amount_multiturn", 1),
        ("presentation_unique", 1),
        ("presentation_ambiguous", 1), ("presentation_locked", 1),
    ])
    # Near-pair sampling is useful when the checker found a genuine train-side
    # candidate, but must not manufacture a packet blocker when normalization
    # governance leaves no such pair in the collection.
    if near_sample_ids:
        requirements.append(("normalized_prompt_near_pair", 1))
    for operation in ("read.activities", "read.expenses", "read.debts"):
        requirements.extend([(f"read:{operation}:empty", 1), (f"read:{operation}:nonempty", 1)])

    selected_ids: list[str] = []
    selected_tags: dict[str, set[str]] = {}
    # Seeded tie-breaking keeps the review set reproducible while hard
    # requirements guarantee the intended high-risk strata are represented.
    for required_tag, count in requirements:
        already = sum(required_tag in tags for tags in selected_tags.values())
        remaining = [sample_id for sample_id, (_, tags) in indexed.items()
                     if required_tag in tags and sample_id not in selected_tags]
        rng.shuffle(remaining)
        for sample_id in remaining[:max(0, count - already)]:
            selected_ids.append(sample_id)
            selected_tags[sample_id] = set(indexed[sample_id][1])
    uncovered = [tag for tag, count in requirements
                 if sum(tag in tags for tags in selected_tags.values()) < count]
    if uncovered:
        raise HumanReviewPacketError("train split lacks required review coverage: " + ",".join(uncovered))
    if len(selected_ids) > n:
        raise HumanReviewPacketError("required human-risk coverage exceeds the packet size")

    remaining_ids = [sample_id for sample_id in indexed if sample_id not in selected_tags]
    rng.shuffle(remaining_ids)
    for sample_id in remaining_ids[: n - len(selected_ids)]:
        selected_ids.append(sample_id)
        selected_tags[sample_id] = set(indexed[sample_id][1])
    if len(selected_ids) != n:
        raise HumanReviewPacketError("train rows do not satisfy the required human-risk coverage")
    result = []
    for sample_id in selected_ids:
        row, tags = indexed[sample_id]
        ordered_tags = sorted(tags)
        result.append((row, _risk_stratum(row), ordered_tags))
    return result


def _json_for_humans(row: Mapping[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _markdown_fence(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _user_request_summary(row: Mapping[str, Any]) -> str:
    model_steps = [step for step in row.get("trace", [])
                   if isinstance(step, Mapping) and step.get("kind") == "model"]
    if not model_steps:
        return "（没有可显示的模型请求）"
    context = model_steps[-1].get("context", {})
    recent = context.get("recent_messages", []) if isinstance(context, Mapping) else []
    users = [item.get("text") for item in recent if isinstance(item, Mapping)
             and item.get("role") == "user" and isinstance(item.get("text"), str)]
    if users:
        return users[0]
    first_context = model_steps[0].get("context", {})
    text = first_context.get("input_text") if isinstance(first_context, Mapping) else None
    return text if isinstance(text, str) else "（请求文本不可用）"


def _visible_fact_lines(row: Mapping[str, Any]) -> list[str]:
    facts: dict[str, str] = {}
    for step in row.get("trace", []):
        if not isinstance(step, Mapping) or step.get("kind") != "model":
            continue
        context = step.get("context", {})
        results = context.get("read_results", []) if isinstance(context, Mapping) else []
        for result in results:
            body = result.get("body", {}) if isinstance(result, Mapping) else {}
            items = body.get("items", []) if isinstance(body, Mapping) else []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                if "expense_ref" in item:
                    line = (
                        f"费用 {item.get('expense_ref')}「{item.get('title')}」："
                        f"{item.get('original_amount')} {item.get('original_currency')}；"
                        f"参与人={','.join(item.get('participant_refs', [])) or '无'}；"
                        f"财务锁定={'是' if item.get('financial_locked') else '否'}"
                    )
                elif "debtor_ref" in item:
                    line = (f"债务 {item.get('debtor_ref')}→{item.get('creditor_ref')}："
                            f"{item.get('amount')} {item.get('currency')}")
                elif "activity_ref" in item:
                    line = (f"活动 {item.get('activity_ref')}「{item.get('name')}」："
                            f"{item.get('activity_kind')} / {item.get('status')} / {item.get('base_currency')}")
                else:
                    line = json.dumps(item, ensure_ascii=False, sort_keys=True)
                facts[line] = line
    return list(facts.values())


def _trajectory_lines(row: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for step in row.get("trace", []):
        if not isinstance(step, Mapping):
            continue
        if step.get("kind") == "tool_result":
            result = step.get("result", {})
            body = result.get("body", {}) if isinstance(result, Mapping) else {}
            items = body.get("items", []) if isinstance(body, Mapping) else []
            lines.append(f"工具读取 {result.get('operation', 'unknown')}，返回 {len(items) if isinstance(items, list) else 0} 条可见事实")
        elif step.get("kind") == "user_followup":
            lines.append(f"用户补充：{step.get('text', '')}")
        elif step.get("kind") == "model":
            target = step.get("target", {})
            kind = target.get("kind", "unknown") if isinstance(target, Mapping) else "unknown"
            operation = target.get("operation", "") if isinstance(target, Mapping) else ""
            if isinstance(target, Mapping) and kind == "clarify":
                missing = target.get("missing_slots", [])
                prompt = target.get("prompt", "")
                lines.append(
                    f"模型澄清：{prompt}；待补槽位={json.dumps(missing, ensure_ascii=False)}"
                )
            elif isinstance(target, Mapping) and kind == "answer":
                lines.append(f"模型回答步骤：{target.get('text', '')}")
            else:
                lines.append(f"模型步骤：{kind}{' / ' + operation if operation else ''}")
    return lines


def _final_model_target(row: Mapping[str, Any]) -> Mapping[str, Any]:
    for step in reversed(row.get("trace", [])):
        if isinstance(step, Mapping) and step.get("kind") == "model":
            target = step.get("target", {})
            return target if isinstance(target, Mapping) else {}
    return {}


def _context_summary_lines(row: Mapping[str, Any]) -> list[str]:
    context: Any = {}
    for step in reversed(row.get("trace", [])):
        if isinstance(step, Mapping) and step.get("kind") == "model":
            context = step.get("context", {})
            break
    if not isinstance(context, Mapping):
        return []
    lines: list[str] = []
    scope = context.get("verified_scope")
    if isinstance(scope, Mapping):
        lines.append("已验证范围：" + json.dumps(scope, ensure_ascii=False, sort_keys=True))
    permissions = context.get("available_permissions", [])
    if isinstance(permissions, list):
        lines.append("可用权限：" + ("、".join(map(str, permissions)) or "无"))
    references = context.get("bound_references", [])
    if isinstance(references, list):
        grouped: dict[str, list[str]] = {}
        for item in references:
            if isinstance(item, Mapping):
                kind, ref = item.get("kind"), item.get("ref")
                if isinstance(kind, str) and isinstance(ref, str):
                    grouped.setdefault(kind, []).append(ref)
        if grouped:
            rendered = "；".join(
                f"{kind}={','.join(sorted(set(refs)))}" for kind, refs in sorted(grouped.items())
            )
            lines.append("本轮类型化引用：" + rendered)
        else:
            lines.append("本轮类型化引用：无")
    policies = context.get("policy_evidence", [])
    if isinstance(policies, list):
        for item in policies:
            if not isinstance(item, Mapping):
                continue
            label = "/".join(str(item.get(key)) for key in ("evidence_ref", "rule", "source", "version")
                             if item.get(key) is not None)
            text = item.get("text")
            if isinstance(text, str):
                lines.append(f"模型可见静态规则 {label}：{text}")
            else:
                lines.append("模型可见静态规则：" + json.dumps(item, ensure_ascii=False, sort_keys=True))
    return lines


def _proposal_summary(row: Mapping[str, Any]) -> list[str]:
    target = _final_model_target(row)
    kind = target.get("kind")
    if kind == "answer":
        lines = [f"最终回答：{target.get('text', '')}"]
        if target.get("basis") is not None:
            lines.append(f"回答依据：{target.get('basis')}")
        if target.get("citations") is not None:
            lines.append("引用：" + json.dumps(target.get("citations"), ensure_ascii=False, sort_keys=True))
        lines.append("写入状态：无后端写入（读取/回答轨迹）")
        return lines
    if kind == "clarify":
        return [
            f"最终澄清：{target.get('prompt', '')}",
            "待补槽位：" + json.dumps(target.get("missing_slots", []), ensure_ascii=False),
            "写入状态：无后端写入（等待用户补充）",
        ]
    if kind == "deny":
        return [
            f"最终拒绝：{target.get('reason', target.get('text', ''))}",
            "写入状态：无后端写入（拒绝）",
        ]
    fields = target.get("fields", {}) if isinstance(target, Mapping) else {}
    if not isinstance(fields, Mapping):
        return []
    lines = []
    if fields.get("kind") in {"expense.create", "expense.update"}:
        for key, label in (("original_amount", "原币金额"), ("original_currency", "币种"),
                           ("payment_allocations", "付款分配"), ("split", "费用分摊")):
            if fields.get(key) is not None:
                lines.append(f"{label}：{json.dumps(fields[key], ensure_ascii=False, sort_keys=True)}")
        amount = fields.get("original_amount")
        if isinstance(amount, str) and fields.get("kind") == "expense.create":
            try:
                total = Decimal(amount)
                payments = sum((Decimal(item["amount"]) for item in fields.get("payment_allocations", [])), Decimal("0"))
                split = fields.get("split", {})
                split_rows = split.get("allocations", []) if split.get("mode") == "manual" else []
                split_total = sum((Decimal(item["amount"]) for item in split_rows), Decimal("0"))
                if split.get("mode") == "equal":
                    # Equal-split rows may be computed by the backend contract;
                    # the display is explicitly described as not independently recomputed here.
                    lines.append("守恒核对：付款已按目标总额核对；等额分摊按候选目标规则检查")
                else:
                    lines.append(f"守恒核对：付款={'相等' if payments == total else '不相等'}；手工分摊={'相等' if split_total == total else '不相等'}")
            except (InvalidOperation, KeyError, TypeError):
                lines.append("守恒核对：请人工核对提案中的金额与分配")
    else:
        for key, label in (("title", "展示标题"), ("note", "展示备注"), ("icon_key", "图标")):
            if fields.get(key) is not None:
                lines.append(f"{label}：{fields[key]}")
    lines.append("写入状态：仅为模拟提案/回答，未执行后端写入")
    return lines


@dataclass(frozen=True)
class HumanPacket:
    creation_manifest_sha256: str
    packet_sha256: str
    selection_sha256: str
    row_count: int
    markdown_bytes: bytes = field(repr=False)
    html_bytes: bytes = field(repr=False)
    receipt_template_bytes: bytes = field(repr=False)

    def __repr__(self) -> str:
        return (
            "HumanPacket("
            f"creation_manifest_sha256={self.creation_manifest_sha256!r}, "
            f"packet_sha256={self.packet_sha256!r}, row_count={self.row_count}, "
            "packet_bodies=<redacted>)"
        )

    def receipt_template(self) -> dict[str, Any]:
        return json.loads(self.receipt_template_bytes)


def build_train_packet(
    prepared: PreparedRelease,
    *,
    n: int = 34,
    seed: int = 20261011,
) -> HumanPacket:
    """Build a deterministic, risk-stratified packet from train rows only."""
    rows = _read_train_rows(prepared)
    report = prepared.checker_report()
    if (report.get("collection_passed") is not True
            or report.get("preparation_eligible") is not True
            or report.get("training_eligible") is not False
            or report.get("training_admission") is not False):
        raise HumanReviewPacketError("human review packet requires the validated collection checker gate")
    _validate_train_gold(rows)
    near_sample_ids: set[str] = set()
    for finding in report.get("pair_findings", []):
        if finding.get("kind") != "near_prompt_candidate":
            continue
        for side in ("left", "right"):
            endpoint = finding.get(side, {})
            if endpoint.get("split") == "train" and isinstance(endpoint.get("sample_id"), str):
                near_sample_ids.add(endpoint["sample_id"])
    selected = _select_rows(rows, n, seed, near_sample_ids, gold_validated=True)
    creation_manifest_sha = prepared.creation_manifest_sha256
    selections: list[dict[str, Any]] = []
    render_rows: list[dict[str, Any]] = []
    for index, (row, stratum, review_tags) in enumerate(selected, start=1):
        sample_id = row.get("sample_id")
        row_sha = sha256_bytes(canonical_json(row))
        selection_id = "hr-" + hashlib.sha256(
            f"{creation_manifest_sha}:{index}:{sample_id}:{row_sha}".encode("utf-8")
        ).hexdigest()[:20]
        selections.append({
            "selection_id": selection_id,
            "sample_id": sample_id,
            "row_sha256": row_sha,
            "split": "train",
            "risk_stratum": stratum,
            "review_tags": review_tags,
        })
        render_rows.append({
            "index": index, "row": row, "stratum": stratum, "review_tags": review_tags,
            "sample_id": sample_id, "row_sha": row_sha, "selection_id": selection_id,
            "operation": row.get("expected", {}).get("task_operation", "unknown"),
            "row_text": _json_for_humans(row),
            "request_text": _user_request_summary(row),
            "fact_lines": _visible_fact_lines(row),
            "context_lines": _context_summary_lines(row),
            "trajectory": _trajectory_lines(row),
            "output_lines": _proposal_summary(row),
        })
    markdown_parts = [
        "# T1 v2 训练集人工审阅包",
        "",
        f"创建清单 SHA-256：`{creation_manifest_sha}`",
        f"抽样种子：`{seed}`；样本数：`{n}`（仅 train）",
        "",
        "收据模板状态为 pending。人工审阅通过也不会自动取得训练资格。",
        "",
        "本轮自动失败修复审查类别：状态泄漏、规范化近重复、候选歧义、财务锁定边界。下列样本是 train 对照项，请核对其是否真实展示相应的状态、授权、筛选、引用与资金事实；不代表模型质量通过。",
        "",
        "## 覆盖索引",
        "",
        *[
            f"- [{entry['selection_id']} · {entry['sample_id']} · {entry['stratum']}](#{entry['selection_id']}) · "
            f"{'、'.join(entry['review_tags'])}"
            for entry in render_rows
        ],
        "",
    ]
    html_parts = [
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>T1 v2 训练集人工审阅</title>",
        "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:1rem;border-radius:.4rem}"
        "code{overflow-wrap:anywhere}.meta{color:#555}</style></head><body>",
        "<h1>T1 v2 训练集人工审阅包</h1>",
        f"<p class=\"meta\">创建清单 SHA-256：<code>{html.escape(creation_manifest_sha)}</code></p>",
        f"<p class=\"meta\">抽样种子：<code>{seed}</code>；样本数：<code>{n}</code>（仅 train）。</p>",
        "<p>收据模板状态为 pending。人工审阅通过也不会自动取得训练资格。</p>",
        "<p>本轮自动失败修复审查类别：状态泄漏、规范化近重复、候选歧义、财务锁定边界。请核对 train 对照项；这不代表模型质量通过。</p>",
        "<nav aria-label=\"覆盖索引\"><h2>覆盖索引</h2><ul>",
        *[
            f"<li><a href=\"#{entry['selection_id']}\"><code>{entry['selection_id']}</code> · "
            f"{html.escape(str(entry['sample_id']))} · {html.escape(entry['stratum'])}</a> · "
            f"{html.escape('、'.join(entry['review_tags']))}</li>"
            for entry in render_rows
        ],
        "</ul></nav>",
    ]
    for entry in render_rows:
        index = entry["index"]
        row = entry["row"]
        stratum = entry["stratum"]
        review_tags = entry["review_tags"]
        sample_id = entry["sample_id"]
        row_sha = entry["row_sha"]
        selection_id = entry["selection_id"]
        operation = entry["operation"]
        row_text = entry["row_text"]
        fence = _markdown_fence(row_text)
        request_text = entry["request_text"]
        fact_lines = entry["fact_lines"]
        context_lines = entry["context_lines"]
        trajectory = entry["trajectory"]
        output_lines = entry["output_lines"]
        markdown_parts.extend([
            f"<a id=\"{selection_id}\"></a>",
            f"## {index}. {sample_id}",
            "",
            f"Selection ID：`{selection_id}`；row SHA-256：`{row_sha}`",
            f"操作：`{operation}`；风险层：`{stratum}`；审阅标签：{'、'.join(review_tags)}",
            "",
            "首轮用户请求：",
            "",
            request_text,
            "",
            "模型可见业务事实：",
            "",
            *(f"- {line}" for line in (fact_lines or ["没有可见业务事实"])),
            "",
            "模型可见授权、引用与静态业务规则：",
            "",
            *(f"- {line}" for line in (context_lines or ["没有额外范围、权限或静态规则事实"])),
            "",
            "实际轨迹：",
            "",
            *(f"- {line}" for line in (trajectory or ["没有可见轨迹"])),
            "",
            "最终模型输出核对：",
            "",
            *(f"- {line}" for line in (output_lines or ["没有可显示的最终输出"])),
            "",
            "独立校验用合成状态（不冒称模型可见tool fact）：折叠的原始 JSON 含完整校验状态；仅上方列出的上下文和读取结果属于模型可见事实。",
            "",
            f"<details><summary>原始 JSON（row SHA-256：{row_sha}）</summary>",
            "",
            f"{fence}json",
            row_text,
            fence,
            "",
            "</details>",
            "",
        ])
        html_parts.extend([
            f"<section id=\"{selection_id}\"><h2>{index}. {html.escape(str(sample_id))}</h2>",
            f"<p class=\"meta\">Selection ID: <code>{selection_id}</code> · row SHA-256: <code>{row_sha}</code></p>",
            f"<p>操作：<code>{html.escape(str(operation))}</code>；风险层：<code>{html.escape(stratum)}</code>；审阅标签：{html.escape('、'.join(review_tags))}</p>",
            f"<h3>首轮用户请求</h3><p>{html.escape(request_text)}</p>",
            "<h3>模型可见业务事实</h3><ul>" + "".join(
                f"<li>{html.escape(line)}</li>" for line in (fact_lines or ["没有可见业务事实"])
            ) + "</ul>",
            "<h3>模型可见授权、引用与静态业务规则</h3><ul>" + "".join(
                f"<li>{html.escape(line)}</li>" for line in (context_lines or ["没有额外范围、权限或静态规则事实"])
            ) + "</ul>",
            "<h3>实际轨迹</h3><ol>" + "".join(
                f"<li>{html.escape(line)}</li>" for line in (trajectory or ["没有可见轨迹"])
            ) + "</ol>",
            "<h3>最终模型输出核对</h3><ul>" + "".join(
                f"<li>{html.escape(line)}</li>" for line in (output_lines or ["没有可显示的最终输出"])
            ) + "</ul>",
            "<p><strong>独立校验用合成状态（不冒称模型可见tool fact）：</strong>折叠的原始 JSON 含完整校验状态；仅上方列出的上下文和读取结果属于模型可见事实。</p>",
            f"<details><summary>原始 JSON（row SHA-256：{row_sha}）</summary><pre>{html.escape(row_text)}</pre></details></section>",
        ])
    markdown_parts.extend([
        "", "## 审阅说明", "",
        "请分别核对用户意图、可见状态与引用、活动/账本/成员授权、金额与币种、付款和分摊守恒、澄清携带、锁定边界，以及是否发生真实写入。所有提案都只是模拟结果。人工收据必须由独立审阅者填写；即使获批，P2 基线校准与 T2 授权仍是训练准入前置条件。",
    ])
    html_parts.extend([
        "<h2>审阅说明</h2><p>请分别核对用户意图、可见状态与引用、活动/账本/成员授权、金额和币种、付款和分摊守恒、澄清携带、锁定边界，以及是否发生真实写入。所有提案都只是模拟结果。</p>",
        "<p>人工收据必须由独立审阅者填写；即使获批，P2 基线校准与 T2 授权仍是训练准入前置条件。</p></body></html>",
    ])

    selection_body = {
        "creation_manifest_sha256": creation_manifest_sha,
        "selection_seed": seed,
        "selections": selections,
    }
    selection_sha = sha256_bytes(canonical_json(selection_body))
    markdown_bytes = "\n".join(markdown_parts).encode("utf-8")
    html_bytes = "".join(html_parts).encode("utf-8")
    packet_sha = sha256_bytes(canonical_json({
        "markdown_sha256": sha256_bytes(markdown_bytes),
        "html_sha256": sha256_bytes(html_bytes),
        "selection_sha256": selection_sha,
    }))
    receipt = {
        "schema": _RECEIPT_SCHEMA,
        "status": "pending",
        "decision": None,
        "reviewer_kind": None,
        "reviewer_id": None,
        "human_reviewed": False,
        "creation_manifest_sha256": creation_manifest_sha,
        "packet_sha256": packet_sha,
        "selection_sha256": selection_sha,
        "selections": selections,
        "training_eligible": False,
        "training_blockers": ["p2_baseline_calibration_pending", "t2_authorization_pending"],
    }
    return HumanPacket(
        creation_manifest_sha256=creation_manifest_sha,
        packet_sha256=packet_sha,
        selection_sha256=selection_sha,
        row_count=n,
        markdown_bytes=markdown_bytes,
        html_bytes=html_bytes,
        receipt_template_bytes=canonical_json(receipt),
    )


def validate_external_human_receipt(
    packet: HumanPacket,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Check a separately supplied review receipt while preserving T2 gates."""
    if not isinstance(packet, HumanPacket) or not isinstance(receipt, Mapping):
        raise HumanReviewPacketError("packet and external receipt are required")
    template = packet.receipt_template()
    if any(receipt.get(key) != template.get(key) for key in (
        "schema", "creation_manifest_sha256", "packet_sha256", "selection_sha256", "selections",
    )):
        raise HumanReviewPacketError("human receipt is not bound to this packet and selected rows")
    status = receipt.get("status")
    reviewed = receipt.get("human_reviewed") is True
    if status == "pending" and reviewed is False:
        if receipt.get("decision") is not None:
            raise HumanReviewPacketError("pending human receipt cannot claim a decision")
        return {
            "valid": True,
            "human_reviewed": False,
            "decision": None,
            "training_eligible": False,
            "blockers": ["human_review_pending", "p2_baseline_calibration_pending", "t2_authorization_pending"],
        }
    if (status != "approved" or not reviewed or receipt.get("decision") != "approved"
            or receipt.get("reviewer_kind") != "human"
            or not isinstance(receipt.get("reviewer_id"), str)
            or not receipt["reviewer_id"].strip()
            or not isinstance(receipt.get("evidence"), str)
            or not receipt["evidence"].strip()):
        raise HumanReviewPacketError("external human approval receipt is incomplete")
    return {
        "valid": True,
        "human_reviewed": True,
        "decision": "approved",
        "reviewer_id": receipt["reviewer_id"],
        "training_eligible": False,
        "blockers": ["p2_baseline_calibration_pending", "t2_authorization_pending"],
    }


__all__ = [
    "HumanPacket", "HumanReviewPacketError", "build_train_packet", "validate_external_human_receipt",
]
