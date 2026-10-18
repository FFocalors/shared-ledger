from __future__ import annotations

import pytest

from agent.evaluation.t1_release.human_review import (
    HumanReviewPacketError,
    _context_summary_lines,
    _coverage_tags,
    _proposal_summary,
    _select_rows,
    _trajectory_lines,
    build_train_packet,
    validate_external_human_receipt,
)
from agent.evaluation.t1_release.builder import _make_record, _multiturn_create_record
from agent.evaluation.t1_release.boundary import build_boundary_records
from agent.evaluation.t1_release.goldguard import validate_operation_gold
from agent.evaluation.t1_release.pipeline import (
    PreparedRelease,
    _PREPARED_RELEASE_SEAL,
    canonical_json,
    sha256_bytes,
)


def _prepared_with_train_bytes(train: bytes, validation: bytes, sealed: bytes) -> PreparedRelease:
    source_body = {"format": "synthetic-human-test-source"}
    source_sha = sha256_bytes(canonical_json(source_body))
    source_bytes = canonical_json({**source_body, "source_manifest_sha256": source_sha})
    report_bytes = canonical_json({
        "pair_findings": [], "collection_passed": True, "preparation_eligible": True,
        "training_eligible": False, "training_admission": False,
    })
    payload_hashes = {"train": sha256_bytes(train), "validation": sha256_bytes(validation),
                      "sealed": sha256_bytes(sealed)}
    payloads_sha = sha256_bytes(canonical_json(payload_hashes))
    manifest_body = {
        "source_manifest_sha256": source_sha,
        "root_creation_receipt_sha256": "a" * 64,
        "collection_sha256": "b" * 64,
        "checker_report_sha256": sha256_bytes(report_bytes),
        "payload_sha256": payload_hashes,
        "payloads_sha256": payloads_sha,
        "row_counts": {"train": len(train.splitlines()), "validation": len(validation.splitlines()),
                        "sealed": len(sealed.splitlines())},
        "collection_passed": True, "human_review_pending": True, "training_eligible": False,
    }
    manifest_bytes = canonical_json(manifest_body)
    prepared = PreparedRelease(
        train_bytes=train,
        validation_bytes=validation,
        sealed_bytes=sealed,
        creation_manifest_bytes=manifest_bytes,
        source_manifest_bytes=source_bytes,
        checker_report_bytes=report_bytes,
        root_receipt_sha256="a" * 64,
        collection_sha256="b" * 64,
        payloads_sha256=payloads_sha,
        creation_manifest_sha256=sha256_bytes(manifest_bytes),
    )
    object.__setattr__(prepared, "_seal", _PREPARED_RELEASE_SEAL)
    return prepared


def _row(sample_id: str, operation: str | None, *, fields: dict | None = None,
         interaction: str | None = None, coverage: list[str] | None = None,
         result_items: list[dict] | None = None) -> dict:
    target = {"kind": "answer", "text": "模拟结果。", "citations": [], "basis": "grounded"}
    if fields is not None:
        target = {"kind": "propose", "operation": operation, "fields": fields}
    request = f"单元测试请求 {sample_id}。"
    context = {"input_text": request, "recent_messages": [{"role": "user", "text": request}],
               "read_results": []}
    trace = [
        {"kind": "model", "context": context, "target": target},
        {"kind": "tool_result", "result": {"operation": operation or "read.activities",
                                               "body": {"items": list(result_items or [])}}},
    ]
    return {
        "sample_id": sample_id,
        "split": "train",
        "case_type": "clarification" if interaction else "supported_operation",
        "expected": {
            "supported_in_v1": operation is not None,
            "must_complete": operation is not None,
            "semantic": "propose" if fields is not None else "answer",
            "operation": operation,
            "task_operation": operation,
        },
        "scenario": {"interaction": interaction} if interaction else {},
        "coverage_tags": list(coverage or []),
        "trace": trace,
    }


def _required_coverage_rows() -> list[dict]:
    rows = [
        _row(f"boundary-{case}", None, coverage=[f"boundary_{case}"])
        for case in (
            "ordinary_activity_prepayment", "actor_not_authorized", "child_unbound_payer",
            "child_unbound_split", "archived_activity_financial_change",
            "locked_expense_financial_change", "missing_amount", "untrusted_tool_data_injection",
        )
    ]
    rows.extend([
        _row("create-single-zero-debt-small", "expense.create", fields={
            "kind": "expense.create", "original_amount": "0.50", "original_currency": "USD",
            "payment_allocations": [{"participant_ref": "participant_1", "amount": "0.50"}],
            "split": {"mode": "equal", "participant_refs": ["participant_1"]},
        }),
        _row("create-aa-multi-payer", "expense.create", fields={
            "kind": "expense.create", "original_amount": "12.00", "original_currency": "USD",
            "payment_allocations": [
                {"participant_ref": "participant_1", "amount": "6.00"},
                {"participant_ref": "participant_2", "amount": "6.00"},
            ],
            "split": {"mode": "equal", "participant_refs": ["participant_1", "participant_2"]},
        }),
        _row("create-manual-small", "expense.create", fields={
            "kind": "expense.create", "original_amount": "0.75", "original_currency": "USD",
            "payment_allocations": [{"participant_ref": "participant_1", "amount": "0.75"}],
            "split": {"mode": "manual", "allocations": [
                {"participant_ref": "participant_1", "amount": "0.50"},
                {"participant_ref": "participant_2", "amount": "0.25"},
            ]},
        }),
        _row("create-missing-amount-positive", "expense.create", fields={
            "kind": "expense.create", "original_amount": "84.00", "original_currency": "USD",
            "payment_allocations": [{"participant_ref": "participant_1", "amount": "84.00"}],
            "split": {"mode": "equal", "participant_refs": ["participant_1", "participant_2"]},
        }, interaction="clarify_only_missing_amount_then_continue"),
    ])
    rows.extend(_row(f"update-{index}", "expense.update", fields={}) for index in range(3))
    rows.extend([
        _row("presentation-unique", "expense.presentation.update",
             fields={"kind": "expense.presentation.update", "expense_ref": "expense_1", "title": "新标题"},
             interaction="unique_title_match_direct_proposal"),
        _row("presentation-ambiguous", "expense.presentation.update",
             fields={"kind": "expense.presentation.update", "expense_ref": "expense_2", "title": "新标题"},
             interaction="clarify_ambiguous_expense_ref_then_continue"),
        _row("presentation-locked", "expense.presentation.update",
             fields={"kind": "expense.presentation.update", "expense_ref": "expense_locked", "icon_key": "meal"},
             result_items=[{"expense_ref": "expense_locked", "financial_locked": True}]),
    ])
    for operation in ("read.activities", "read.expenses", "read.debts"):
        rows.append(_row(f"{operation}-empty", operation, result_items=[]))
        rows.append(_row(f"{operation}-nonempty", operation, result_items=[{"evidence_ref": "fact_visible"}]))
    rows.extend(_row(f"filler-{index}", None) for index in range(12))
    return rows


def _valid_train_rows_for_packet() -> list[dict]:
    rows = [row for row in build_boundary_records() if row["split"] == "train"]
    create_candidates = [_make_record("expense.create", g) for g in range(20)]
    chosen_create: dict[str, dict] = {}
    for required in (
        "create_single_person_zero_debt", "create_aa_equal_split", "create_manual_split",
        "create_multi_payer", "small_amount",
    ):
        candidate = next(row for row in create_candidates
                         if required in _coverage_tags(row, set()))
        chosen_create[candidate["sample_id"]] = candidate
    for row in create_candidates:
        if len(chosen_create) >= 8:
            break
        chosen_create.setdefault(row["sample_id"], row)
    rows.extend(chosen_create.values())
    rows.append(_multiturn_create_record(1))
    rows.extend(_make_record("expense.update", g) for g in range(6))
    rows.extend(_make_record("expense.presentation.update", g) for g in range(4))
    for operation in ("read.activities", "read.expenses", "read.debts"):
        rows.append(_make_record(operation, 0, read_variant="full"))
        rows.append(_make_record(operation, 0, read_variant="empty"))
    rows.append(_make_record("read.activities", 1, read_variant="narrow"))
    for row in rows:
        validate_operation_gold(row)
    return rows


def test_risk_selection_requires_all_fixed_coverage_but_not_a_fake_near_pair() -> None:
    rows = _required_coverage_rows()
    selected = _select_rows(rows, 34, 20261011, set())
    ids = {row["sample_id"] for row, _, _ in selected}
    assert "boundary-ordinary_activity_prepayment" in ids
    assert "create-single-zero-debt-small" in ids
    assert "create-aa-multi-payer" in ids
    assert "create-manual-small" in ids
    assert "create-missing-amount-positive" in ids
    assert "presentation-unique" in ids
    assert "presentation-ambiguous" in ids
    assert "presentation-locked" in ids
    assert all(row.get("split") == "train" for row, _, _ in selected)
    selected_tag_rows = [(row, set(tags)) for row, _, tags in selected]
    assert sum("create_any" in tags for _, tags in selected_tag_rows) >= 3
    assert sum("update_any" in tags for _, tags in selected_tag_rows) >= 3
    for row, tags in selected_tag_rows:
        if any(tag.startswith("boundary:") for tag in tags):
            assert "create_any" not in tags
            assert "update_any" not in tags


def test_boundary_denials_and_clarifications_do_not_count_as_positive_writes() -> None:
    create_denial = _row("create-denial", "expense.create")
    create_denial["expected"].update({"supported_in_v1": False, "must_complete": False,
                                      "semantic": "deny"})
    create_denial["trace"][0]["target"] = {"kind": "deny", "reason": "unauthorized"}

    update_denial = _row("update-denial", "expense.update")
    update_denial["expected"].update({"supported_in_v1": False, "must_complete": False,
                                      "semantic": "deny"})
    update_denial["trace"][0]["target"] = {"kind": "deny", "reason": "locked"}

    missing_amount = _row("create-clarification", "expense.create", interaction="clarify_only_missing_amount_then_continue")
    missing_amount["expected"].update({"supported_in_v1": False, "must_complete": False,
                                        "semantic": "clarify"})
    missing_amount["trace"][0]["target"] = {"kind": "clarify", "missing_slots": ["original_amount"]}

    assert "create_any" not in _coverage_tags(create_denial, set())
    assert "update_any" not in _coverage_tags(update_denial, set())
    clarify_tags = _coverage_tags(missing_amount, set())
    assert "missing_amount" in clarify_tags
    assert "create_missing_amount_multiturn" in clarify_tags
    assert "create_any" not in clarify_tags


def test_risk_selection_fails_closed_when_required_boundary_coverage_is_missing() -> None:
    rows = [row for row in _required_coverage_rows() if row["sample_id"] != "boundary-child_unbound_split"]
    with pytest.raises(HumanReviewPacketError, match="required review coverage"):
        _select_rows(rows, 34, 20261011, set())


def test_human_packet_is_chinese_train_only_hash_bound_and_permanently_pending() -> None:
    rows = _valid_train_rows_for_packet()
    train_bytes = b"\n".join(canonical_json(row) for row in rows) + b"\n"
    prepared = _prepared_with_train_bytes(
        train_bytes,
        b'{"split":"validation","sample_id":"validation-only"}\n',
        b'{"split":"sealed","secret":"SEALED-SEMANTIC-SECRET"}\n',
    )
    packet = build_train_packet(prepared, n=34, seed=20261011)
    template = packet.receipt_template()
    markdown = packet.markdown_bytes.decode("utf-8")
    html = packet.html_bytes.decode("utf-8")
    assert packet.row_count == 34
    assert template["status"] == "pending"
    assert template["human_reviewed"] is False
    assert template["training_eligible"] is False
    assert all(item["split"] == "train" for item in template["selections"])
    selected_tags = {tag for item in template["selections"] for tag in item["review_tags"]}
    for operation in ("read.activities", "read.expenses", "read.debts"):
        assert f"read:{operation}:empty" in selected_tags
        assert f"read:{operation}:nonempty" in selected_tags
    assert "read:read.expenses:postfilter_empty" in selected_tags
    assert "read:read.expenses:tool_result_nonempty" in selected_tags
    assert "首轮用户请求" in markdown and "模型可见业务事实" in markdown
    assert "未执行后端写入" in markdown
    assert "<details><summary>原始 JSON" in markdown
    assert "<details><summary>原始 JSON" in html
    assert markdown.index("## 覆盖索引") < markdown.index("## 1.")
    assert html.index("</ul></nav>") < html.index("<section id=\"hr-")
    assert "href=\"#hr-" in html
    first_selection = template["selections"][0]["selection_id"]
    assert f"(#{first_selection})" in markdown
    assert f'<a id="{first_selection}"></a>' in markdown
    assert f'href="#{first_selection}"' in html
    assert html.count("<ul>") == html.count("</ul>")
    assert html.count("<li>") == html.count("</li>")
    assert html.count("<section id=") == html.count("</section>") == 34
    assert "模型可见授权、引用与静态业务规则" in markdown
    assert "模型可见授权、引用与静态业务规则" in html
    assert "validation-only" not in markdown and "validation-only" not in html
    assert "SEALED-SEMANTIC-SECRET" not in repr(packet)
    assert "SEALED-SEMANTIC-SECRET" not in markdown and "SEALED-SEMANTIC-SECRET" not in html
    pending = validate_external_human_receipt(packet, template)
    assert pending["training_eligible"] is False
    assert pending["human_reviewed"] is False

    approved = dict(template)
    approved.update({"status": "approved", "decision": "approved", "reviewer_kind": "human",
                     "reviewer_id": "reviewer-1", "evidence": "separate human review receipt",
                     "human_reviewed": True, "training_eligible": True})
    result = validate_external_human_receipt(packet, approved)
    assert result["human_reviewed"] is True
    assert result["training_eligible"] is False
    approved["selections"] = list(approved["selections"])
    approved["selections"][0] = {**approved["selections"][0], "row_sha256": "0" * 64}
    with pytest.raises(HumanReviewPacketError, match="not bound"):
        validate_external_human_receipt(packet, approved)


def test_read_coverage_uses_gold_verified_postfilter_visible_results() -> None:
    tool_empty = _make_record("read.activities", 0, read_variant="empty")
    filtered_empty = _make_record("read.expenses", 0, read_variant="empty")
    filtered_nonempty = _make_record("read.expenses", 0, read_variant="narrow")
    alternate_expense_scope_wording = _make_record("read.expenses", 10)
    for row in (tool_empty, filtered_empty, filtered_nonempty, alternate_expense_scope_wording):
        validate_operation_gold(row)
    empty_tags = _coverage_tags(filtered_empty, set(), gold_validated=True)
    nonempty_tags = _coverage_tags(filtered_nonempty, set(), gold_validated=True)
    raw_empty_tags = _coverage_tags(tool_empty, set(), gold_validated=True)
    assert "read:read.expenses:empty" in empty_tags
    assert "read:read.expenses:tool_result_nonempty" in empty_tags
    assert "read:read.expenses:postfilter_empty" in empty_tags
    assert "read:read.expenses:nonempty" in nonempty_tags
    assert "read:read.expenses:tool_result_nonempty" in nonempty_tags
    assert "read:read.expenses:postfilter_nonempty" in nonempty_tags
    assert "read:read.activities:empty" in raw_empty_tags
    assert "read:read.activities:tool_result_empty" in raw_empty_tags


def test_packet_rejects_train_row_without_independent_gold_validation() -> None:
    row = _make_record("expense.create", 0)
    row["trace"][-1]["target"]["fields"]["original_amount"] = "999.00"
    train = canonical_json(row) + b"\n"
    prepared = _prepared_with_train_bytes(
        train,
        b'{"split":"validation","sample_id":"validation-only"}\n',
        b'{"split":"sealed","secret":"SEALED-SEMANTIC-SECRET"}\n',
    )
    with pytest.raises(HumanReviewPacketError, match="independent Gold validation"):
        build_train_packet(prepared, n=34, seed=20261011)


def test_human_summary_shows_real_answers_clarifications_and_visible_authority() -> None:
    context = {
        "verified_scope": {"kind": "activity", "activity_ref": "activity_1"},
        "available_permissions": ["read.expenses"],
        "bound_references": [
            {"kind": "activity", "ref": "activity_1"},
            {"kind": "ledger_unit", "ref": "ledger_unit_1"},
            {"kind": "participant", "ref": "participant_1"},
        ],
        "policy_evidence": [{
            "evidence_ref": "P01", "rule": "business_logic_current", "source": "BUSINESS_LOGIC.md",
            "version": "v1", "text": "活动成员可读取本活动费用。",
        }],
    }
    row = {"trace": [
        {"kind": "model", "context": context, "target": {
            "kind": "clarify", "prompt": "请指定费用ref。", "missing_slots": ["expense_ref"],
        }},
        {"kind": "user_followup", "text": "expense_ref=expense_1。"},
        {"kind": "model", "context": context, "target": {
            "kind": "answer", "text": "该费用为 12.00 USD。", "basis": "grounded",
            "citations": ["expense_fact_1"],
        }},
    ]}
    assert any("模型澄清：请指定费用ref" in line for line in _trajectory_lines(row))
    output = _proposal_summary(row)
    assert any("最终回答：该费用为 12.00 USD。" in line for line in output)
    assert any("grounded" in line for line in output)
    assert any("expense_fact_1" in line for line in output)
    context_lines = _context_summary_lines(row)
    joined = "\n".join(context_lines)
    for expected in (
        "read.expenses", "ledger_unit_1", "participant_1", "business_logic_current",
        "活动成员可读取本活动费用。",
    ):
        assert expected in joined

    clarify_row = {"trace": [{"kind": "model", "context": context, "target": {
        "kind": "clarify", "prompt": "请补充原币金额。", "missing_slots": ["original_amount"],
    }}]}
    clarification = _proposal_summary(clarify_row)
    assert "最终澄清：请补充原币金额。" in clarification
    assert '"original_amount"' in clarification[1]

