from __future__ import annotations

import copy

import pytest
from jsonschema import ValidationError

from agent.evaluation.t1_release.builder import _make_record
from agent.evaluation.t1_release.goldguard import (
    GoldGuardError,
    _operation_state_eligible,
    _parse_request,
    validate_operation_gold,
)
from agent.evaluation.t1_release.runtime import baseline_modules, make_v2_validator
from agent.evaluation.t1_release.signatures import operation_state_signature, sha256


def _finish_scenario_edit(record: dict) -> None:
    record["scenario_signature_sha256"] = sha256(record["scenario"])


def _record(operation: str, index: int = 0) -> dict:
    # `_make_record` is the explicitly permitted single train op/g pure-memory path.
    return _make_record(operation, index)


def _replay_debts_all_currencies(record: dict) -> None:
    contracts, _, _, simulator, _ = baseline_modules()
    first = next(step for step in record["trace"] if step["kind"] == "model")
    old_currency = first["target"]["criteria"]["currency"]
    first["target"]["criteria"]["currency"] = None
    first["context"]["input_text"] = first["context"]["input_text"].replace(
        f"currency={old_currency}", "currency=全部币种"
    )
    record["scenario"]["criteria"]["currency"] = None
    record["scenario"]["requested_values"]["currency"] = "全部币种"
    record["scenario"]["empty_result_citation_gap"] = False
    tool = next(step for step in record["trace"] if step["kind"] == "tool_result")
    tool["request"] = copy.deepcopy(first["target"])
    result = simulator.simulate_read(
        tool["fixture_state"], tool["request"], observed_at=tool["observed_at"],
        context_version=tool["context_version"], replay_key=tool["replay_key"],
    ).model_dump(mode="json")
    tool["result"] = result
    model_result = {
        key: result[key] for key in (
            "result_ref", "operation", "observed_at", "context_version", "simulation", "body"
        )
    }
    for step in record["trace"]:
        if step.get("kind") == "model" and step["context"].get("read_results"):
            step["context"]["read_results"] = [copy.deepcopy(model_result)]
    facts = result["body"]["items"]
    answer = record["trace"][-1]["target"]
    answer["basis"] = "grounded"
    answer["citations"] = [fact["evidence_ref"] for fact in facts]
    lines = [
        f"{fact['debtor_ref']}→{fact['creditor_ref']}：{fact['amount']} {fact['currency']}"
        for fact in facts
    ]
    answer["text"] = f"模拟查询得到{len(lines)}项：" + "；".join(lines) + "。"
    _finish_scenario_edit(record)


def _refresh_read_after_fixture_edit(record: dict) -> None:
    _, _, data_signature, simulator, _ = baseline_modules()
    tool = next(step for step in record["trace"] if step["kind"] == "tool_result")
    tool["fixture_state"] = copy.deepcopy(record["fixture_state"])
    result = simulator.simulate_read(
        tool["fixture_state"], tool["request"], observed_at=tool["observed_at"],
        context_version=tool["context_version"], replay_key=tool["replay_key"],
    ).model_dump(mode="json")
    tool["result"] = result
    model_result = {
        key: result[key] for key in (
            "result_ref", "operation", "observed_at", "context_version", "simulation", "body"
        )
    }
    for step in record["trace"]:
        if step.get("kind") == "model" and step["context"].get("read_results"):
            step["context"]["read_results"] = [copy.deepcopy(model_result)]
    record["fixture_state_sha256"] = sha256(record["fixture_state"])
    record["operation_state_signature_sha256"] = operation_state_signature(
        record["operation_state"], record["expected"]["task_operation"]
    )
    record["normalized_state_signature_sha256"] = sha256(data_signature.fixture_projection(record["fixture_state"]))
    record["normalized_scenario_signature_sha256"] = sha256(
        data_signature.scenario_projection(record["fixture_state"], record)
    )


def _select_presentation_expense(record: dict, expense_ref: str) -> None:
    fields = record["trace"][-1]["target"]["fields"]
    fields["expense_ref"] = expense_ref
    record["scenario"]["target"] = copy.deepcopy(fields)
    followup = next(step for step in record["trace"] if step.get("kind") == "user_followup")
    followup["text"] = f"expense_ref={expense_ref}。"
    final_context = record["trace"][-1]["context"]
    final_context["input_text"] = followup["text"]
    for message in final_context.get("recent_messages", []):
        if message.get("role") == "user" and message.get("text", "").startswith("expense_ref="):
            message["text"] = followup["text"]
    _finish_scenario_edit(record)
    _refresh_normalized_scenario_signature(record)


def _refresh_normalized_scenario_signature(record: dict) -> None:
    data_signature = baseline_modules()[2]
    record["normalized_scenario_signature_sha256"] = sha256(
        data_signature.scenario_projection(record["fixture_state"], record)
    )


def _presentation_clarification(record: dict) -> dict:
    return next(
        step for step in record["trace"]
        if step.get("kind") == "model" and step.get("target", {}).get("kind") == "clarify"
    )


def _presentation_candidate_lines(facts: list[dict]) -> list[str]:
    lines = []
    for fact in facts:
        participants = ",".join(fact["participant_refs"]) if fact["participant_refs"] else "-"
        lock = "是" if fact["financial_locked"] else "否"
        lines.append(
            f"{fact['expense_ref']}|{fact['original_currency']}|{participants}|{lock}"
        )
    return lines


def test_expense_read_accepts_omitted_filters_and_explicit_all_scope() -> None:
    prompt = "读取活动ref=activity_1的费用；全部日期；全部参与人；title_contains=早餐。"
    parsed = _parse_request("read.expenses", {
        "input_text": prompt,
        "recent_messages": [{"role": "user", "text": prompt}],
    })
    assert parsed["criteria"] == {
        "kind": "expenses", "activity_ref": "activity_1", "from_date": None,
        "to_date": None, "participant_ref": None,
    }
    assert parsed["metadata"] == {
        "date_scope": "all", "participant_scope": "all", "title_contains": "早餐",
    }
    assert parsed["post_filter"] == {"title_contains": "早餐"}

    omitted = _parse_request("read.expenses", {"input_text": "读取活动ref=activity_1的费用。"})
    assert omitted["metadata"] == {}
    with pytest.raises(GoldGuardError, match="incomplete"):
        _parse_request("read.expenses", {
            "input_text": "读取活动ref=activity_1的费用；日期范围仅开始于2026-10-01。",
        })


def _presentation_clarification_text(query_title: str, facts: list[dict]) -> str:
    return (
        f"请求标题=“{query_title}”；候选(ref|currency|participant_refs|financial_locked)="
        + "，".join(_presentation_candidate_lines(facts))
        + "；请回复其中一个expense_ref。"
    )


def test_joint_gold_mutation_cannot_replace_the_user_requested_payer() -> None:
    record = _record("expense.create", 1)
    broken = copy.deepcopy(record)
    fields = broken["trace"][-1]["target"]["fields"]
    original_ref = fields["payment_allocations"][0]["participant_ref"]
    alternate = next(
        ref for ref in broken["operation_state"]["ledger_unit"]["participant_allowlist"]
        if ref != original_ref
    )
    fields["payment_allocations"][0]["participant_ref"] = alternate
    # Reproduce the former bypass: keep the user's request and requested_values,
    # but synchronize the model target, duplicate scenario target, and hash.
    broken["scenario"]["target"] = copy.deepcopy(fields)
    _finish_scenario_edit(broken)
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


@pytest.mark.parametrize("field", ["original_amount", "original_currency", "title", "occurred_at"])
def test_create_gold_fields_must_come_from_visible_user_request(field: str) -> None:
    record = _record("expense.create", 0)
    broken = copy.deepcopy(record)
    fields = broken["trace"][-1]["target"]["fields"]
    if field == "original_amount":
        fields[field] = "999.00"
    elif field == "original_currency":
        current = fields[field]
        fields[field] = "EUR" if current != "EUR" else "USD"
    elif field == "title":
        fields[field] = "a title the user did not ask for"
    else:
        fields[field] = "2026-10-10T12:00:00Z"
    broken["scenario"]["target"] = copy.deepcopy(fields)
    _finish_scenario_edit(broken)
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


def test_self_only_create_is_a_valid_zero_debt_expense() -> None:
    record = _record("expense.create", 0)
    fields = record["trace"][-1]["target"]["fields"]
    assert len(fields["payment_allocations"]) == 1
    assert fields["split"]["mode"] == "equal"
    assert fields["payment_allocations"][0]["participant_ref"] == fields["split"]["participant_refs"][0]
    validate_operation_gold(record)


def test_partial_update_merges_visible_old_total_when_amount_is_omitted() -> None:
    record = _record("expense.update", 1)
    broken = copy.deepcopy(record)
    state = broken["operation_state"]
    expense = state["expenses"][0]
    allowed = state["ledger_unit"]["participant_allowlist"]
    old_payer = expense["payments"][0]["participant_ref"]
    new_payer = next(ref for ref in allowed if ref != old_payer)
    amount = expense["amount"]
    fields = broken["trace"][-1]["target"]["fields"]
    fields["original_amount"] = None
    fields["original_currency"] = None
    fields["payment_allocations"] = [{"participant_ref": new_payer, "amount": amount}]
    fields["split"] = None
    broken["trace"][-1]["context"]["input_text"] = (
        f"更正费用ref={expense['ref']}：原额{expense['amount']} {expense['currency']}；"
        f"付款[{new_payer}={amount}]。"
    )
    broken["scenario"]["target"] = copy.deepcopy(fields)
    broken["scenario"]["requested_values"] = {
        "expense_ref": expense["ref"], "payment_allocations": f"付款[{new_payer}={amount}]",
    }
    _finish_scenario_edit(broken)
    validate_operation_gold(broken)


def test_partial_update_rejects_inconsistent_merged_split_total() -> None:
    record = _record("expense.update", 1)
    broken = copy.deepcopy(record)
    expense = broken["operation_state"]["expenses"][0]
    allowed = broken["operation_state"]["ledger_unit"]["participant_allowlist"]
    old_payer = expense["payments"][0]["participant_ref"]
    new_payer = next(ref for ref in allowed if ref != old_payer)
    amount = expense["amount"]
    fields = broken["trace"][-1]["target"]["fields"]
    fields["original_amount"] = None
    fields["original_currency"] = None
    fields["payment_allocations"] = [{"participant_ref": new_payer, "amount": amount}]
    fields["split"] = None
    broken["trace"][-1]["context"]["input_text"] = (
        f"更正费用ref={expense['ref']}：原额{amount} {expense['currency']}；"
        f"付款[{new_payer}={amount}]。"
    )
    broken["scenario"]["target"] = copy.deepcopy(fields)
    broken["scenario"]["requested_values"] = {
        "expense_ref": expense["ref"], "payment_allocations": f"付款[{new_payer}={amount}]",
    }
    _finish_scenario_edit(broken)
    # The submitted payments total the visible old amount, but the old split
    # snapshot no longer merges to that amount.
    expense["splits"][0]["amount"] = "1.00"
    broken["operation_state_signature_sha256"] = operation_state_signature(
        broken["operation_state"], "expense.update"
    )
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


def test_title_only_change_is_not_a_positive_financial_update() -> None:
    record = _record("expense.update", 0)
    broken = copy.deepcopy(record)
    expense = broken["operation_state"]["expenses"][0]
    fields = broken["trace"][-1]["target"]["fields"]
    fields["original_amount"] = None
    fields["original_currency"] = None
    fields["payment_allocations"] = None
    fields["split"] = None
    fields["title"] = "新展示标题"
    broken["trace"][-1]["context"]["input_text"] = (
        f"更正费用ref={expense['ref']}：修改标题“新展示标题”。"
    )
    broken["scenario"]["target"] = copy.deepcopy(fields)
    broken["scenario"]["requested_values"] = {
        "expense_ref": expense["ref"], "title": "新展示标题",
    }
    _finish_scenario_edit(broken)
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


@pytest.mark.parametrize("damage", ["unit_inactive", "activity_archived", "member_inactive"])
def test_financial_write_requires_active_authorized_activity_and_unit(damage: str) -> None:
    record = _record("expense.create", 0)
    broken = copy.deepcopy(record)
    state = broken["operation_state"]
    if damage == "unit_inactive":
        state["ledger_unit"]["active"] = False
    elif damage == "activity_archived":
        next(row for row in state["activities"] if row["role"] == "current")["status"] = "archived"
    else:
        payer = broken["trace"][-1]["target"]["fields"]["payment_allocations"][0]["participant_ref"]
        next(row for row in state["participants"] if row["ref"] == payer)["active"] = False
    broken["operation_state_signature_sha256"] = operation_state_signature(state, "expense.create")
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


def test_large_child_write_rejects_a_payer_removed_from_its_allowlist() -> None:
    record = _record("expense.create", 13)
    broken = copy.deepcopy(record)
    unit = broken["operation_state"]["ledger_unit"]
    assert unit["role"] == "large_child"
    payer = broken["trace"][-1]["target"]["fields"]["payment_allocations"][0]["participant_ref"]
    unit["participant_allowlist"].remove(payer)
    broken["operation_state_signature_sha256"] = operation_state_signature(
        broken["operation_state"], "expense.create"
    )
    with pytest.raises(GoldGuardError, match="outside the ledger-unit participant scope"):
        validate_operation_gold(broken)


def test_legacy_unscoped_unit_is_valid_with_active_large_root_and_full_roster() -> None:
    record = _record("expense.create", 8)
    state = record["operation_state"]
    current = next(row for row in state["activities"] if row["role"] == "current")
    unit = state["ledger_unit"]
    assert current["kind"] == "large"
    assert unit["role"] == "legacy_unscoped"
    assert unit["parent_ref"] is not None
    assert unit["parent_role"] == "large_root"
    assert unit["parent_active"] is True
    assert set(unit["participant_allowlist"]) == set(current["member_allowlist"])
    validate_operation_gold(record)


@pytest.mark.parametrize(
    "mutation",
    ["missing_parent", "wrong_parent_role", "normal_activity", "partial_roster"],
)
def test_legacy_unscoped_unit_rejects_root_or_malformed_child_scope(mutation: str) -> None:
    record = _record("expense.create", 8)
    state = copy.deepcopy(record["operation_state"])
    unit = state["ledger_unit"]
    current = next(row for row in state["activities"] if row["role"] == "current")
    if mutation == "missing_parent":
        unit["parent_ref"] = None
        unit["parent_role"] = None
    elif mutation == "wrong_parent_role":
        unit["parent_role"] = "normal_root"
    elif mutation == "normal_activity":
        current["kind"] = "normal"
    else:
        unit["participant_allowlist"].pop()
    with pytest.raises(GoldGuardError):
        _operation_state_eligible(state, "expense.create")


@pytest.mark.parametrize(
    "mutation",
    ["missing_parent_role", "inactive_parent"],
)
def test_configured_large_child_requires_active_large_root_and_selected_subset(mutation: str) -> None:
    record = _record("expense.create", 12)
    state = copy.deepcopy(record["operation_state"])
    unit = state["ledger_unit"]
    current = next(row for row in state["activities"] if row["role"] == "current")
    if mutation == "missing_parent_role":
        unit["parent_role"] = None
    else:
        unit["parent_active"] = False
    with pytest.raises(GoldGuardError):
        _operation_state_eligible(state, "expense.create")


def test_configured_large_child_may_select_the_full_activity_roster() -> None:
    record = _record("expense.create", 12)
    state = copy.deepcopy(record["operation_state"])
    unit = state["ledger_unit"]
    current = next(row for row in state["activities"] if row["role"] == "current")
    unit["participant_allowlist"] = list(current["member_allowlist"])
    _operation_state_eligible(state, "expense.create")


def test_update_version_mutation_breaks_state_fixture_binding() -> None:
    record = _record("expense.update", 0)
    broken = copy.deepcopy(record)
    broken["operation_state"]["expenses"][0]["expense_version"] = "99"
    broken["operation_state_signature_sha256"] = operation_state_signature(
        broken["operation_state"], "expense.update"
    )
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


@pytest.mark.parametrize("currency_enabled", [False, True])
def test_nonbase_create_needs_visible_enabled_server_fx(currency_enabled: bool) -> None:
    record = _record("expense.create", 0 if not currency_enabled else 1)
    broken = copy.deepcopy(record)
    state = broken["operation_state"]
    state["multi_currency_enabled"] = currency_enabled
    base = state["activities"][0]["base_currency"]
    foreign = "USD" if base != "USD" else "EUR"
    context = broken["trace"][-1]["context"]
    old_currency = broken["trace"][-1]["target"]["fields"]["original_currency"]
    assert foreign != old_currency
    context["input_text"] = context["input_text"].replace(f" {old_currency}；", f" {foreign}；")
    fields = broken["trace"][-1]["target"]["fields"]
    fields["original_currency"] = foreign
    broken["scenario"]["target"] = copy.deepcopy(fields)
    broken["scenario"]["requested_values"]["currency"] = foreign
    broken["operation_state_signature_sha256"] = operation_state_signature(state, "expense.create")
    _finish_scenario_edit(broken)
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


@pytest.mark.parametrize("mutation", ["amount", "currency", "direction", "missing_citation", "substituted_citation"])
def test_read_debt_gold_checks_each_fact_and_its_citation(mutation: str) -> None:
    record = _record("read.debts", 0)
    broken = copy.deepcopy(record)
    answer = broken["trace"][-1]["target"]
    item = next(step for step in broken["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"][0]
    if mutation == "amount":
        answer["text"] = answer["text"].replace(item["amount"], "999.99", 1)
    elif mutation == "currency":
        wrong_currency = "USD" if item["currency"] != "USD" else "EUR"
        answer["text"] = answer["text"].replace(item["currency"], wrong_currency, 1)
    elif mutation == "direction":
        directed = f"{item['debtor_ref']}→{item['creditor_ref']}"
        reversed_direction = f"{item['creditor_ref']}→{item['debtor_ref']}"
        answer["text"] = answer["text"].replace(directed, reversed_direction, 1)
    elif mutation == "missing_citation":
        answer["citations"] = answer["citations"][1:]
    else:
        answer["citations"][0] = "fact_debt_16"
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


def test_cross_currency_debt_rows_cannot_be_aggregated_into_one_currency() -> None:
    record = _record("read.debts", 0)
    state_rows = record["operation_state"]["debts"]
    fixture_rows = record["fixture_state"]["debts"]
    assert len(state_rows) >= 2
    state_rows[1]["currency"] = "EUR" if state_rows[0]["currency"] != "EUR" else "USD"
    fixture_rows[1]["currency"] = state_rows[1]["currency"]
    _refresh_read_after_fixture_edit(record)
    _replay_debts_all_currencies(record)
    facts = next(step for step in record["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"]
    assert len({fact["currency"] for fact in facts}) > 1
    validate_operation_gold(record)
    answer = record["trace"][-1]["target"]
    first = facts[0]
    answer["text"] = (
        f"模拟查询得到1项：{first['debtor_ref']}→{first['creditor_ref']}："
        f"{sum(float(fact['amount']) for fact in facts):.2f} {first['currency']}。"
    )
    answer["citations"] = [first["evidence_ref"]]
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


def test_read_tool_body_must_be_a_deterministic_replay_of_its_fixture() -> None:
    record = _record("read.expenses", 0)
    broken = copy.deepcopy(record)
    tool = next(step for step in broken["trace"] if step["kind"] == "tool_result")
    tool["result"]["body"]["items"][0]["original_amount"] = "1.00"
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


def test_locked_expense_can_receive_display_only_update() -> None:
    record = _record("expense.presentation.update", 0)
    fields = record["trace"][-1]["target"]["fields"]
    expense_ref = fields["expense_ref"]
    expense = next(row for row in record["operation_state"]["expenses"] if row["ref"] == expense_ref)
    fixture_expense = next(row for row in record["fixture_state"]["expenses"]
                           if row["expense_ref"] == expense_ref)
    expense["locked"] = True
    fixture_expense["financial_locked"] = True
    _refresh_read_after_fixture_edit(record)
    assert expense["locked"] is True
    validate_operation_gold(record)
    broken = copy.deepcopy(record)
    fields = broken["trace"][-1]["target"]["fields"]
    fields["original_amount"] = "100.00"
    broken["scenario"]["target"] = copy.deepcopy(fields)
    _finish_scenario_edit(broken)
    with pytest.raises(GoldGuardError):
        validate_operation_gold(broken)


def test_ambiguous_presentation_is_strict_schema_and_gold_valid() -> None:
    record = _record("expense.presentation.update", 4)
    clarification = next(
        step for step in record["trace"]
        if step.get("kind") == "model" and step.get("target", {}).get("kind") == "clarify"
    )
    assert clarification["target"]["missing_slots"] == ["expense_ref"]
    initial = clarification["context"]["input_text"]
    query_title = record["scenario"]["requested_values"]["query_title"]
    assert f"标题为“{query_title}”" in initial
    assert len(next(step for step in record["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"]) >= 3
    validate_operation_gold(record)
    _, _, _, _, validator_module = baseline_modules()
    validator_module.validate_record(record, make_v2_validator())


def test_ambiguous_presentation_rejects_same_scope_but_different_title_candidate() -> None:
    record = _record("expense.presentation.update", 8)
    facts = next(step for step in record["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"]
    query_title = record["scenario"]["requested_values"]["query_title"]
    candidates = [fact for fact in facts if fact["title"] == query_title]
    assert len(candidates) >= 3
    other = candidates[-1]

    state_expense = next(row for row in record["operation_state"]["expenses"] if row["ref"] == other["expense_ref"])
    fixture_expense = next(row for row in record["fixture_state"]["expenses"]
                           if row["expense_ref"] == other["expense_ref"])
    state_expense["title"] = "另一笔可见费用"
    fixture_expense["title"] = "另一笔可见费用"
    _refresh_read_after_fixture_edit(record)
    refreshed_facts = next(
        step for step in record["trace"] if step["kind"] == "tool_result"
    )["result"]["body"]["items"]
    remaining = [fact for fact in refreshed_facts if fact["title"] == query_title]
    _presentation_clarification(record)["target"]["prompt"] = _presentation_clarification_text(
        query_title, remaining,
    )
    _select_presentation_expense(record, other["expense_ref"])

    # This is still a real ambiguity among the two remaining matching facts;
    # the chosen ref is another visible expense, but does not match the query.
    _, _, _, _, validator_module = baseline_modules()
    validator_module.validate_record(record, make_v2_validator())
    with pytest.raises(GoldGuardError, match="same-title candidates"):
        validate_operation_gold(record)


def test_ambiguous_presentation_rejects_a_missing_original_query_title() -> None:
    record = _record("expense.presentation.update", 4)
    clarification = next(
        step for step in record["trace"]
        if step.get("kind") == "model" and step.get("target", {}).get("kind") == "clarify"
    )
    phrase = f"标题为“{record['scenario']['requested_values']['query_title']}”"
    clarification["context"]["input_text"] = clarification["context"]["input_text"].replace(phrase, "这笔费用")
    final_context = record["trace"][-1]["context"]
    for message in final_context.get("recent_messages", []):
        if message.get("role") == "user":
            message["text"] = message["text"].replace(phrase, "这笔费用")
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


def test_ambiguous_presentation_rejects_a_stale_consumed_expense_version() -> None:
    record = _record("expense.presentation.update", 4)
    final_context = record["trace"][-1]["context"]
    final_context["read_results"][0]["body"]["items"][0]["expense_version"] = "stale"
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


@pytest.mark.parametrize("field", ["title", "icon_key"])
def test_ambiguous_presentation_target_must_preserve_requested_display_values(field: str) -> None:
    record = _record("expense.presentation.update", 4)
    fields = record["trace"][-1]["target"]["fields"]
    fields[field] = "not_requested" if field == "icon_key" else "未请求的展示标题"
    record["scenario"]["target"] = copy.deepcopy(fields)
    _finish_scenario_edit(record)
    _refresh_normalized_scenario_signature(record)

    # The changed proposal remains schema-valid and parseable as a protocol
    # decision; independent gold must catch its divergence from user intent.
    _, _, _, _, validator_module = baseline_modules()
    validator_module.validate_record(record, make_v2_validator())
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


@pytest.mark.parametrize("field", ["title", "icon_key"])
def test_ambiguous_presentation_requires_the_display_value_in_original_request(field: str) -> None:
    record = _record("expense.presentation.update", 4)
    requested = record["scenario"]["requested_values"]
    if field == "title":
        fragment = f"title=“{requested['title']}”"
    else:
        fragment = f"icon_key={requested['icon_key']}"
    for step in record["trace"]:
        if step.get("kind") != "model":
            continue
        context = step["context"]
        if context.get("input_text"):
            context["input_text"] = context["input_text"].replace(fragment, "")
        for message in context.get("recent_messages", []):
            if message.get("role") == "user":
                message["text"] = message["text"].replace(fragment, "")

    _, _, _, _, validator_module = baseline_modules()
    validator_module.validate_record(record, make_v2_validator())
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


def test_unique_title_presentation_binds_the_only_visible_match_without_clarifying() -> None:
    record = _record("expense.presentation.update", 0)
    facts = next(step for step in record["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"]
    query_title = record["scenario"]["requested_values"]["query_title"]
    matches = [fact for fact in facts if fact["title"] == query_title]
    assert len(matches) == 1
    assert not any(step.get("target", {}).get("kind") == "clarify" for step in record["trace"])
    assert record["trace"][-1]["target"]["fields"]["expense_ref"] == matches[0]["expense_ref"]
    assert record["scenario"]["interaction"] == "unique_title_match_direct_proposal"
    assert record["scenario"]["request_completed_across_turns"] is False
    validate_operation_gold(record)
    _, _, _, _, validator_module = baseline_modules()
    validator_module.validate_record(record, make_v2_validator())


def test_explicit_expense_reference_presentation_remains_a_valid_single_turn_request() -> None:
    record = _record("expense.presentation.update", 0)
    fields = record["trace"][-1]["target"]["fields"]
    expense_ref = fields["expense_ref"]
    query_title = record["scenario"]["requested_values"].pop("query_title")
    record["scenario"]["requested_values"]["expense_ref"] = expense_ref
    old_request = f"把标题为“{query_title}”的那笔费用"
    new_request = f"把展示费用ref={expense_ref}的费用"
    for step in record["trace"]:
        if step.get("kind") != "model":
            continue
        context = step["context"]
        if isinstance(context.get("input_text"), str):
            context["input_text"] = context["input_text"].replace(old_request, new_request)
        for message in context.get("recent_messages", []):
            if message.get("role") == "user":
                message["text"] = message["text"].replace(old_request, new_request)
    record["scenario"].pop("interaction", None)
    record["scenario"].pop("request_completed_across_turns", None)
    _finish_scenario_edit(record)
    _refresh_normalized_scenario_signature(record)
    validate_operation_gold(record)
    _, _, _, _, validator_module = baseline_modules()
    validator_module.validate_record(record, make_v2_validator())


def test_strict_schema_rejects_mixed_query_title_and_explicit_ref_modes() -> None:
    record = _record("expense.presentation.update", 0)
    expense_ref = record["trace"][-1]["target"]["fields"]["expense_ref"]
    record["scenario"]["requested_values"]["expense_ref"] = expense_ref
    for step in record["trace"]:
        if step.get("kind") == "model" and isinstance(step.get("context", {}).get("input_text"), str):
            step["context"]["input_text"] = f"展示费用ref={expense_ref}；" + step["context"]["input_text"]
    _finish_scenario_edit(record)
    _refresh_normalized_scenario_signature(record)
    _, _, _, _, validator_module = baseline_modules()
    with pytest.raises(ValidationError):
        validator_module.validate_record(record, make_v2_validator())


def test_unique_title_presentation_rejects_a_fake_clarification() -> None:
    record = _record("expense.presentation.update", 0)
    final_step = record["trace"][-1]
    original_request = final_step["context"]["input_text"]
    selected_ref = final_step["target"]["fields"]["expense_ref"]
    clarification_text = (
        _presentation_clarification_text(
            record["scenario"]["requested_values"]["query_title"],
            next(step for step in record["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"],
        )
    )
    clarification_context = copy.deepcopy(final_step["context"])
    clarification = {
        "kind": "model", "context": clarification_context,
        "target": {"kind": "clarify", "prompt": clarification_text, "missing_slots": ["expense_ref"]},
    }
    followup = f"expense_ref={selected_ref}。"
    final_step["context"]["input_text"] = followup
    final_step["context"]["recent_messages"] = [
        {"role": "user", "text": original_request},
        {"role": "assistant", "text": clarification_text},
        {"role": "user", "text": followup},
    ]
    record["trace"][-1:-1] = [clarification, {"kind": "user_followup", "text": followup}]
    record["scenario"]["interaction"] = "clarify_ambiguous_expense_ref_then_continue"
    record["scenario"]["request_completed_across_turns"] = True
    _finish_scenario_edit(record)
    with pytest.raises(GoldGuardError, match="unique visible title match"):
        validate_operation_gold(record)


@pytest.mark.parametrize("mutation", ["generic", "invented", "omitted", "currency", "participants", "lock"])
def test_ambiguous_clarification_must_consume_and_enumerate_all_visible_facts(mutation: str) -> None:
    record = _record("expense.presentation.update", 4)
    clarification = _presentation_clarification(record)
    prompt = clarification["target"]["prompt"]
    if mutation == "generic":
        clarification["target"]["prompt"] = "有多笔同名费用，请提供要调整展示的费用ref。"
    else:
        label = "候选(ref|currency|participant_refs|financial_locked)="
        head, rest = prompt.split(label, 1)
        candidate_text, tail = rest.split("；请回复其中一个expense_ref。", 1)
        rows = candidate_text.split("，")
        if mutation == "invented":
            rows.append("expense_99|EUR|participant_99|否")
        elif mutation == "omitted":
            assert len(rows) > 1
            rows.pop()
        elif mutation == "currency":
            ref, currency, participants, lock = rows[0].split("|")
            wrong_currency = "EUR" if currency != "EUR" else "USD"
            rows[0] = f"{ref}|{wrong_currency}|{participants}|{lock}"
        elif mutation == "participants":
            ref, currency, participants, lock = rows[0].split("|")
            wrong_refs = "participant_99" if participants != "participant_99" else "participant_98"
            rows[0] = f"{ref}|{currency}|{wrong_refs}|{lock}"
        elif mutation == "lock":
            ref, currency, participants, lock = rows[0].split("|")
            rows[0] = f"{ref}|{currency}|{participants}|{'否' if lock == '是' else '是'}"
        clarification["target"]["prompt"] = head + label + "，".join(rows) + "；请回复其中一个expense_ref。" + tail
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


def test_maximum_presentation_candidate_list_stays_within_clarification_limit() -> None:
    record = _record("expense.presentation.update", 59)
    prompt = _presentation_clarification(record)["target"]["prompt"]
    assert len(prompt) <= 1000
    assert len(_presentation_candidate_lines(
        [fact for fact in next(step for step in record["trace"] if step["kind"] == "tool_result")["result"]["body"]["items"]
         if fact["title"] == record["scenario"]["requested_values"]["query_title"]]
    )) == 15
    validate_operation_gold(record)


def test_presentation_final_turn_must_retain_the_original_display_request() -> None:
    record = _record("expense.presentation.update", 4)
    followup = next(step for step in record["trace"] if step.get("kind") == "user_followup")["text"]
    final_context = record["trace"][-1]["context"]
    final_context["input_text"] = followup
    final_context["recent_messages"] = [
        {"role": "user", "text": followup},
    ]
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)


def test_unique_title_presentation_rejects_a_target_outside_its_only_visible_match() -> None:
    record = _record("expense.presentation.update", 0)
    record["trace"][-1]["target"]["fields"]["expense_ref"] = "expense_99"
    record["scenario"]["target"] = copy.deepcopy(record["trace"][-1]["target"]["fields"])
    _finish_scenario_edit(record)
    _refresh_normalized_scenario_signature(record)
    with pytest.raises(GoldGuardError):
        validate_operation_gold(record)
