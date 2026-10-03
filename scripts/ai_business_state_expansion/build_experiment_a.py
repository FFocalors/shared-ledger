#!/usr/bin/env python3
"""Build the human-authored v0.2 business-state expansion from frozen train templates."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
CANON = ROOT / "docs/ai/dataset/canonical_training/v0.1"
NAMESPACE = uuid.UUID("b30d4b62-6b77-493c-8b11-9d17fa6bd2e2")
BASELINE = "55fb28a7c0660462e5842eeb5c71cfa763e5801"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(name: str, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_output_is_mutable() -> None:
    manifest = OUT / "dataset_manifest.json"
    if manifest.is_file() and read(manifest).get("status") == "frozen":
        raise SystemExit(f"Refusing to regenerate frozen Experiment A in place: {OUT}. Create a new dataset version.")


def stable_id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def remap(value, group: str, mapping: dict[str, str]):
    if isinstance(value, dict):
        return {k: remap(v, group, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, group, mapping) for v in value]
    if isinstance(value, str):
        if value not in mapping:
            if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,36}", value):
                mapping[value] = stable_id(group + "|" + value)
            elif value.startswith("result-"):
                mapping[value] = "result-v02-" + uuid.uuid5(NAMESPACE, group + "|" + value).hex[:12]
            elif value.startswith("screen-"):
                mapping[value] = "screen-" + uuid.uuid5(NAMESPACE, group + "|" + value).hex[:12]
            elif value.startswith("turn-") and value != "turn-current":
                mapping[value] = "turn-" + uuid.uuid5(NAMESPACE, group + "|" + value).hex[:12]
        return mapping.get(value, value)
    return value


def replace_tree(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {k: replace_tree(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_tree(v, replacements) for v in value]
    if isinstance(value, str):
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,36}", value):
            return value
        for old, new in replacements.items():
            value = value.replace(old, new)
    return value


def load_templates():
    scenarios = read(CANON / "scenarios.json")
    samples = read(CANON / "samples.json")
    sc_by_id = {x["scenario_id"]: x for x in scenarios}
    by_sample = {x["sample_id"]: x for x in samples if x.get("split") == "train" and x["source"]["surface_form_type"] == "human_authored"}
    return by_sample, sc_by_id


def make_pair(sample_id: str, scenario_id: str, sample_new: str, scenario_new: str, family: str, split_group: str,
              source_id: str, title: str, description: str, user: str, replacements: dict[str, str] | None = None):
    templates, sc_by_id = load_templates()
    sample = copy.deepcopy(templates[sample_id])
    scenario = copy.deepcopy(sc_by_id[sample["scenario_id"]])
    map_ids: dict[str, str] = {}
    sample = remap(sample, family, map_ids)
    scenario = remap(scenario, family, map_ids)
    replacements = replacements or {}
    sample = replace_tree(sample, replacements)
    scenario = replace_tree(scenario, replacements)

    old_scenario_id = sample["scenario_id"]
    sample["sample_id"] = sample_new
    sample["scenario_id"] = scenario_new
    sample["scenario_family_id"] = family
    sample["split_group_id"] = split_group
    sample["split"] = "unassigned"
    sample["example_only"] = False
    sample["dataset_version"] = "0.1"
    sample["source"] = {"surface_form_type": "human_authored", "generator": None, "source_reference": f"v0.2-experiment-a:{source_id}; derived from frozen business logic and runtime Context", "teacher": None}
    sample["trust"] = {"level": "SILVER", "ground_truth_locked": True, "surface_form_reviewed": False, "validation_evidence": [f"{scenario_new}#/ground_truth", f"{source_id} frozen business-rule anchor; awaits independent review"]}
    sample["surface_form"]["user_message"] = user
    sample["input"]["user_message"] = user
    sample["expected"]["ground_truth_pointer"] = f"{scenario_new}#/ground_truth"
    sample["dataset_metadata"]["normalization_key"] = f"surface:v02:{sample_new}"
    sample["dataset_metadata"]["dedup_key"] = f"sample:v02:{sample_new}"
    sample["dataset_metadata"]["semantic_group_key"] = f"semantic:v02:{family}:{sample_new}"
    sample["dataset_metadata"]["lifecycle_status"] = "draft"
    sample["dataset_metadata"]["deprecated_by_version"] = None
    sample["dataset_metadata"]["contains_production_data"] = False
    sample["dataset_metadata"]["contains_real_personal_data"] = False
    sample["dataset_metadata"]["review_notes"] = "Human-authored Experiment A sample; external training_eligible=false; unassigned; awaits independent review."

    scenario["scenario_id"] = scenario_new
    scenario["scenario_family_id"] = family
    scenario["split_group_id"] = split_group
    scenario["title"] = title
    scenario["description"] = description
    scenario["versions"] = copy.deepcopy(scenario["versions"])
    scenario["source"] = {"type": "business_logic", "reference": f"BUSINESS LOGIC FREEZE v1.2; AI Contract 0.1.2; Experiment A state construction; {source_id}", "source_id": source_id, "content_sha256": None}
    scenario["trust"] = {"level": "SILVER", "verification_methods": ["frozen_rule", "programmatic_invariant"], "business_validated": False, "evidence_refs": ["docs/backend/BUSINESS_LOGIC.md", "docs/ai/schema/intent_catalog.json"]}
    scenario["split"] = "unassigned"
    scenario["policy_status"] = "active"
    scenario["example_only"] = False
    scenario["lifecycle"] = {"status": "draft", "deprecated_by_version": None, "review_notes": "Unreviewed new Experiment A state; awaits independent review."}
    scenario["privacy"] = {"synthetic_identifiers_only": True, "contains_production_data": False, "contains_real_personal_data": False}
    scenario["deduplication"] = {"canonical_facts_sha256": hashlib.sha256(json.dumps(scenario["state"]["facts"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "dedup_key": f"scenario:v02:{scenario_new}" , "normalization_version": "0.1"}
    scenario["state"]["minimal_state_reason"] = "Minimum synthetic state needed for this distinct decision boundary; paired with its contrastive counterpart in the same Family and split group."
    # Cross-record truth is always the Scenario's sole canonical source.
    scenario["ground_truth"]["model_output"] = copy.deepcopy(sample["expected"]["model_output"])
    scenario["ground_truth"]["expected_output_type"] = sample["expected"]["output_type"]
    return scenario, sample


def main():
    ensure_output_is_mutable()
    OUT.mkdir(parents=True, exist_ok=True)
    # A1/A2 are added first to allow a fast schema/grounding preflight before the remaining closures.
    family, split_group = "family_v02_currency_sufficiency", "split_v02_currency_sufficiency"
    replacements = {"山野午餐": "溪边晚餐", "90": "128", "2026-09-12": "2026-09-14"}
    missing_scenario, missing_sample = make_pair(
        "sample_gs_p0_007", "scenario_gs_p0a_003", "sample_v02_a_currency_missing", "scenario_v02_a_currency_missing", family, split_group,
        "EXP-CREATE-001", "新支出的币种缺失", "除币种外的金额、付款人、时间与 AA 参与人已明确；按冻结 Scope 先澄清币种。",
        "9月14日的溪边晚餐记128，李四和我AA，我先付。", replacements)
    proposal_scenario, proposal_sample = make_pair(
        "sample_gs_p0_001", "scenario_gs_p0a_001", "sample_v02_a_currency_supplied", "scenario_v02_a_currency_supplied", family, split_group,
        "EXP-CREATE-001", "新支出的币种明确", "同一费用请求明确 CNY 后，所有创建所需字段均可解析为 CORE L1 提案。",
        "9月14日的溪边晚餐记128 CNY，李四和我AA，我先付。", replacements)
    # Make the missing side specifically about currency, retaining all other facts.
    gt = missing_sample["expected"]["model_output"]
    gt["missing_fields"] = ["original_currency"]
    gt["question"] = "这笔128的溪边晚餐使用什么币种？"
    missing_sample["expected"]["clarification_annotation"]["missing_fields"] = ["original_currency"]
    missing_sample["expected"]["clarification_annotation"]["question"] = gt["question"]
    mfacts = missing_scenario["state"]["facts"]
    mfacts["recorded_facts"] = [x for x in mfacts["recorded_facts"] if x["field"] != "original_currency"]
    mfacts["recorded_facts"].append({"field": "original_currency", "value": None, "source": "missing"})
    mfacts["recorded_facts"] = [x for x in mfacts["recorded_facts"] if x["field"] not in ("user_message", "payer")]
    mfacts["recorded_facts"].append({"field": "user_message", "value": missing_sample["input"]["user_message"], "source": "user_input"})
    mfacts["recorded_facts"].append({"field": "payer_name", "value": "我", "source": "user_input"})
    mfacts["recorded_facts"].append({"field": "payer_participant_id", "value": proposal_sample["input"]["user_context"]["claimed_participant_id"], "source": "user_selected"})
    mfacts["operation_arguments"] = {"activity_id": mfacts["activity_id"], "ledger_unit_id": mfacts["ledger_unit_id"], "title": "溪边晚餐", "original_amount": "128", "original_currency": None, "payer": None}
    missing_scenario["operation"]["arguments"] = copy.deepcopy(mfacts["operation_arguments"])
    missing_scenario["rule_tags"] = list(dict.fromkeys(missing_scenario["rule_tags"] + ["clarification"]))
    missing_scenario["ground_truth"]["model_output"] = copy.deepcopy(missing_sample["expected"]["model_output"])
    proposal_scenario["state"]["facts"]["recorded_facts"] = [x for x in proposal_scenario["state"]["facts"]["recorded_facts"] if x["field"] not in ("user_message", "title", "original_amount", "original_currency")]
    proposal_scenario["state"]["facts"]["recorded_facts"].extend([
        {"field": "user_message", "value": proposal_sample["input"]["user_message"], "source": "user_input"},
        {"field": "title", "value": "溪边晚餐", "source": "user_input"},
        {"field": "original_amount", "value": "128", "source": "user_input"},
        {"field": "original_currency", "value": "CNY", "source": "user_input"},
    ])
    # Update the core create operation's business facts in both canonical locations.
    args = proposal_sample["expected"]["model_output"]["operation"]["arguments"]
    args.update({"title": "溪边晚餐", "original_amount": "128", "original_currency": "CNY", "occurred_at": "2026-09-14T12:30:00+08:00"})
    args["occurred_at"] = "2026-09-14T12:30:00+08:00"
    proposal_sample["surface_form"]["user_message"] = "9月14日12:30的溪边晚餐记128 CNY，我付，和李四AA。"
    proposal_sample["input"]["user_message"] = proposal_sample["surface_form"]["user_message"]
    proposal_sample["expected"]["model_output"]["preview"]["summary"] = "拟新增一笔溪边晚餐支出。"
    proposal_sample["expected"]["model_output"]["preview"]["diff"][0]["after"] = copy.deepcopy(args)
    proposal_sample["expected"]["expected_diff"] = copy.deepcopy(proposal_sample["expected"]["model_output"]["preview"]["diff"])
    proposal_scenario["operation"]["arguments"] = copy.deepcopy(args)
    proposal_scenario["ground_truth"]["model_output"] = copy.deepcopy(proposal_sample["expected"]["model_output"])
    proposal_scenario["state"]["facts"]["operation_arguments"] = copy.deepcopy(args)
    # Current user sentence is authoritative for the supplied variant.
    # The unique participant lookup is explicitly present in model-visible Context.
    pids = [e["id"] for e in proposal_scenario["state"]["entities"] if e["type"] == "participant"]
    lookup_id = "result-v02-currency-pair"
    lookup_payload = {"status": "success", "result_id": lookup_id, "observed_at": "2026-09-30T10:00:00+08:00", "financial_version": None,
                      "data": {"items": [{"id": pids[-1], "activity_id": proposal_scenario["state"]["facts"]["activity_id"], "name": "李四", "participant_order": 2, "claimed_user_id": None, "is_deleted": False}], "next_cursor": None, "truncated": False}}
    proposal_sample["input"]["server_context"]["tool_results"] = [{"tool": "find_participants", "result": lookup_payload}]
    proposal_sample["input"]["server_context"]["verified_result_ids"] = [lookup_id]
    for fact in proposal_scenario["state"]["facts"]["recorded_facts"]:
        if fact["field"] == "user_message": fact["value"] = proposal_sample["input"]["user_message"]
        if fact["field"] == "occurred_at": fact["value"] = args["occurred_at"]
        if fact["field"] == "title": fact["value"] = "溪边晚餐"
        if fact["field"] == "original_amount": fact["value"] = "128"
        if fact["field"] == "original_currency": fact["value"] = "CNY"
    # Rebuild the missing-currency member from the same underlying state/context, changing only currency.
    missing_scenario["state"]["entities"] = copy.deepcopy(proposal_scenario["state"]["entities"])
    missing_scenario["state"]["facts"] = copy.deepcopy(proposal_scenario["state"]["facts"])
    missing_scenario["state"]["facts"]["operation_arguments"]["original_currency"] = None
    missing_scenario["state"]["facts"]["recorded_facts"] = [x for x in missing_scenario["state"]["facts"]["recorded_facts"] if x["field"] != "original_currency"]
    missing_scenario["state"]["facts"]["recorded_facts"].append({"field": "original_currency", "value": None, "source": "missing"})
    missing_scenario["state"]["facts"]["recorded_facts"] = [x for x in missing_scenario["state"]["facts"]["recorded_facts"] if x["field"] != "user_message"]
    missing_sample["input"] = copy.deepcopy(proposal_sample["input"])
    missing_sample["input"]["user_message"] = "9月14日12:30的溪边晚餐记128，我付，和李四AA。"
    missing_sample["surface_form"]["user_message"] = missing_sample["input"]["user_message"]
    missing_scenario["state"]["facts"]["recorded_facts"].append({"field": "user_message", "value": missing_sample["input"]["user_message"], "source": "user_input"})
    missing_scenario["state"]["facts"]["supporting_lookup_result"] = copy.deepcopy(proposal_scenario["state"]["facts"].get("supporting_lookup_result", {"tool": "find_participants", "candidate_ids": [pids[-1]], "resolution": "unique", "query": "李四", "source": "server_result", "result_id": lookup_id}))
    missing_scenario["state"]["facts"]["supporting_lookup_result"].update({"tool": "find_participants", "candidate_ids": [pids[-1]], "resolution": "unique", "query": "李四", "source": "server_result", "result_id": lookup_id})
    missing_scenario["operation"]["arguments"] = copy.deepcopy(missing_scenario["state"]["facts"]["operation_arguments"])
    missing_scenario["operation"]["description"] = "唯一参与人已由可见 read result 核验；请求唯一缺少 original_currency，因此澄清，不生成写提案。"
    missing_scenario["ground_truth"]["expected_business_result"] = {"missing_field": "original_currency", "resolved_participant_id": pids[-1]}
    missing_scenario["ground_truth"]["deterministic_assertions"] = ["币种缺失时不输出写 Proposal", "唯一参与人核验结果不消除币种缺失"]
    proposal_scenario["ground_truth"]["expected_business_result"] = {"supporting_lookup_result_id": lookup_id, "resolved_participant_id": pids[-1], "expected_diff": copy.deepcopy(proposal_sample["expected"]["expected_diff"]), "proposal_only": True}
    proposal_scenario["ground_truth"]["deterministic_assertions"] = ["原币币种来自用户明确输入 CNY", "付款参与人来自 claimed participant 与 verified unique participant result", "写操作只输出 L1 Proposal 并等待可信 UI 确认"]
    missing_scenario["ground_truth"]["model_output"] = copy.deepcopy(missing_sample["expected"]["model_output"])
    missing_scenario["ground_truth"]["expected_output_type"] = "clarification"
    proposal_scenario["state"]["facts"]["supporting_lookup_result"] = {"tool": "find_participants", "candidate_ids": [pids[-1]], "resolution": "unique", "query": "李四", "source": "server_result", "result_id": lookup_id}
    proposal_scenario["ground_truth"]["expected_business_result"]["supporting_lookup"] = copy.deepcopy(proposal_scenario["state"]["facts"]["supporting_lookup_result"])
    missing_scenario["ground_truth"]["expected_business_result"]["supporting_lookup"] = copy.deepcopy(missing_scenario["state"]["facts"]["supporting_lookup_result"])
    proposal_scenario["description"] = "同一费用、付款人、参与人和时间；明确 CNY 时生成 CORE L1 Proposal。"
    missing_scenario["description"] = "同一费用、付款人、参与人和时间；仅缺币种时必须澄清，不得猜测基准币种。"
    scenarios = [missing_scenario, proposal_scenario]
    samples = [missing_sample, proposal_sample]

    def add(sample_id, suffix, family, source_id, title, description, user, replacements=None):
        fam = "family_v02_" + family
        grp = "split_v02_" + family
        sc, sm = make_pair(sample_id, "unused", "sample_v02_" + suffix, "scenario_v02_" + suffix, fam, grp,
                           source_id, title, description, user, replacements)
        facts = sc["state"]["facts"]
        for fact in facts.get("recorded_facts", []):
            if fact["field"] == "user_message":
                fact["value"] = user
        if "ui_context" in facts:
            facts["ui_context"]["source"] = "ui_context"
        scenarios.append(sc)
        samples.append(sm)
        return sc, sm

    # B: Supporting Lookup lifecycle. All lookup outcomes are typed server results in runtime Context.
    bcall_sc, bcall_sm = add("sample_gs_p0_021", "b_lookup_not_run", "participant_lookup", "EXP-CREATE-001",
        "参与人查找尚未执行", "请求字段齐全但候选尚未核验；只能先发 read-only L0 Supporting Lookup。",
        "记一笔溪谷聚餐 86 CNY，我和周宁AA，今天我先付。", {"露营装备": "溪谷聚餐", "2026-09-20": "2026-09-25"})
    bcall_sc["scope"] = {"ai_scope": "CORE", "intent_ids": ["create_expense"], "tool_ids": ["find_participants", "create_expense"]}
    b_shared_message = "溪谷聚餐 86 CNY，我和周宁AA，今天我先付。"
    bcall_sm["surface_form"]["user_message"] = b_shared_message
    bcall_sm["input"]["user_message"] = b_shared_message
    bcall_sc["operation"] = {"type": "multi_step", "intent_ids": ["create_expense"], "tool_id": "find_participants", "arguments": {"activity_id": bcall_sc["state"]["facts"]["activity_id"], "query": "周宁"}, "description": "先查询同一 Activity 中周宁的可见参与人候选；这是 L0 只读查找，不改变 create_expense Intent。"}
    bcall_sc["state"]["facts"]["operation_arguments"] = copy.deepcopy(bcall_sc["operation"]["arguments"])
    bcall_sc["state"]["facts"].pop("supporting_lookup_result", None)
    bcall_sc["state"]["entities"] = [e for e in bcall_sc["state"]["entities"] if e["type"] in ("activity", "ledger_unit")]
    bcall_sm["scope"] = copy.deepcopy(bcall_sc["scope"])
    bcall_sm["expected"]["output_type"] = "tool_call"
    bcall_sm["expected"]["model_output"] = {"type": "tool_call", "intent_id": "create_expense", "tool": "find_participants", "arguments": copy.deepcopy(bcall_sc["operation"]["arguments"])}
    bcall_sm["expected"]["execution"] = {"execution_allowed": False, "confirmation_level": 0, "confirmation_required": False, "final_authorization": "not_applicable", "successful_execution_label_allowed": False}
    bcall_sm["expected"]["entity_resolution"] = []
    bcall_sm["expected"]["evidence_result_ids"] = []
    bcall_sc["ground_truth"]["model_output"] = copy.deepcopy(bcall_sm["expected"]["model_output"])
    bcall_sc["ground_truth"]["expected_output_type"] = "tool_call"
    bcall_sc["ground_truth"]["intent_ids"] = ["create_expense"]
    bcall_sm["input"]["server_context"]["enabled_tools"] = ["find_participants", "create_expense"]
    # A verified result sample: unique/multiple/zero result cardinality is explicit, not asserted from hidden State.
    def install_lookup(sc, sm, resolution, names):
        activity = sc["state"]["facts"]["activity_id"]
        pids = [e["id"] for e in sc["state"]["entities"] if e["type"] == "participant"]
        result_id = "result-v02-lookup-" + hashlib.sha256(sm["sample_id"].encode("utf-8")).hexdigest()[:12]
        items = [{"id": pid, "activity_id": activity, "name": name, "participant_order": i, "claimed_user_id": None, "is_deleted": False}
                 for i, (pid, name) in enumerate(zip(pids[-len(names):] if names else [], names))]
        result = {"status": "success", "result_id": result_id, "observed_at": "2026-09-30T10:00:00+08:00", "financial_version": None,
                  "data": {"items": items, "next_cursor": None, "truncated": False}}
        sm["input"]["server_context"]["tool_results"] = [{"tool": "find_participants", "result": result}]
        sm["input"]["server_context"]["verified_result_ids"] = [result_id]
        facts = sc["state"]["facts"]
        facts["supporting_lookup_result"] = {"tool": "find_participants", "candidate_ids": [x["id"] for x in items], "resolution": resolution, "query": "周宁", "source": "server_result", "result_id": result_id}
        sc["ground_truth"]["expected_business_result"]["supporting_lookup"] = copy.deepcopy(facts["supporting_lookup_result"])
        for fact in facts.get("recorded_facts", []):
            if fact["field"] == "user_message": fact["value"] = sm["input"]["user_message"]
        sm["expected"]["evidence_result_ids"] = []
    bmultiple_sc, bmultiple_sm = add("sample_gs_p0_060", "b_lookup_multiple", "participant_lookup", "EXP-CREATE-001",
        "参与人查找命中多个候选", "相同 create expense 请求在已执行 lookup 后得到两个同名候选，必须让用户选择。",
        "溪谷聚餐 86 CNY，我和周宁AA，今天我先付。")
    install_lookup(bmultiple_sc, bmultiple_sm, "multiple", ["周宁", "周宁"])
    bzero_sc, bzero_sm = add("sample_gs_p0_007", "b_lookup_zero", "participant_lookup", "EXP-CREATE-001",
        "参与人查找没有结果", "相同请求的 Supporting Lookup 返回零参与人；不得猜测 ID，需澄清如何继续。",
        "溪谷聚餐 86 CNY，我和周宁AA，今天我先付。")
    install_lookup(bzero_sc, bzero_sm, "zero", [])
    bzero_sm["expected"]["model_output"].update({"reason": "unresolved_reference", "missing_fields": ["participants"], "question": "没有找到可确认的周宁参与人。你想选择其他参与人，还是先不登记这笔支出？", "candidates": []})
    bzero_sm["expected"]["clarification_annotation"] = {"reason": "unresolved_reference", "missing_fields": ["participants"], "candidate_entity_ids": [], "question": bzero_sm["expected"]["model_output"]["question"]}
    bzero_sc["ground_truth"]["model_output"] = copy.deepcopy(bzero_sm["expected"]["model_output"])
    bzero_sc["state"]["facts"]["operation_arguments"] = {"activity_id": bzero_sc["state"]["facts"]["activity_id"], "query": "周宁"}
    bzero_sc["operation"]["arguments"] = copy.deepcopy(bzero_sc["state"]["facts"]["operation_arguments"])
    # A unique verified match enables the proposal, and the Context carries its exact result ID and payload.
    bunique_sc, bunique_sm = add("sample_gs_p0_001", "b_lookup_unique", "participant_lookup", "EXP-CREATE-001",
        "参与人查找唯一命中后提案", "相同 create expense 请求在 L0 lookup 唯一命中后，可以绑定候选并形成 L1 Proposal。",
        "溪谷聚餐 86 CNY，我和周宁AA，今天我先付。")
    install_lookup(bunique_sc, bunique_sm, "unique", ["周宁"])

    # C: user claim binding boundary.
    add("sample_gs_p0_007", "c_payer_unbound", "payer_binding", "EXP-CREATE-001", "付款人主张未绑定", "用户用‘我付’指代付款人，但该 Activity 没有已声明的 claimed participant，需澄清。", "昨晚的木桥晚餐记74 CNY，我付，和陈一AA。", {"山野午餐": "木桥晚餐", "90": "74"})
    add("sample_gs_p0_001", "c_payer_bound", "payer_binding", "EXP-CREATE-001", "付款人主张已绑定", "相同‘我付’请求只有在 Context 明确 claimed participant 时才能绑定付款人并生成提案。", "昨晚的木桥晚餐记74 CNY，我付，和陈一AA。", {"山野午餐": "木桥晚餐", "90": "74"})
    # D: Activity target resolution in UI.
    add("sample_gs_p0_060", "d_activity_ambiguous", "activity_ui_target", "ACT-002", "Activity UI 目标不唯一", "首页未激活 Activity 且可见多个候选时，不得把创建请求静默归入任一 Activity。", "把湖畔晚饭 92 CNY记上，我先付，和陈一AA。", {"山野午餐": "湖畔晚饭", "90": "92"})
    add("sample_gs_p0_001", "d_activity_selected", "activity_ui_target", "EXP-CREATE-001", "Activity UI 目标唯一", "相同请求在当前 Activity 与 Ledger Unit 已明确时可以生成 L1 Proposal。", "把湖畔晚饭 92 CNY记上，我先付，和陈一AA。", {"山野午餐": "湖畔晚饭", "90": "92"})
    # E: recent action must be successful and bind one entity; failed action is not a stable reference.
    add("sample_gs_p0_058", "e_recent_failed", "recent_action_reference", "ICTX-008", "最近操作失败不可作实体依据", "‘刚才那笔’对应的 recent action 状态为 failed 且没有 Entity；不能编造目标或金额。", "刚才那笔费用改成120 CNY。")
    add("sample_gs_p0_025", "e_recent_succeeded", "recent_action_reference", "EXP-READ-003", "最近操作成功并绑定唯一费用", "同一指代仅在 recent action succeeded 并携带单一 expense ID 时可触发 get_expense 只读查询。", "刚才那笔费用是谁付的？")
    # F: verified read answer control; source evidence must exist in actual runtime Context.
    fsc, fsm = add("sample_gs_p0_045", "f_verified_expense_answer", "verified_expense_answer", "EXP-READ-003", "核验读结果解释", "回答付款参与人 ID；值必须来自序列化后的 get_expense Tool Result。", "这笔溪边停车费是谁付的？请把付款参与人 ID 告诉我。", {"设备维修": "溪边停车费", "120": "43"})
    fsc["scope"]["intent_ids"] = ["query_expense"]
    fsm["scope"]["intent_ids"] = ["query_expense"]
    fsc["ground_truth"]["intent_ids"] = ["query_expense"]
    fsc["operation"]["intent_ids"] = ["query_expense"]
    # G: presentation-only L1 vs financial D4 on the same existing expense.
    add("sample_gs_p0_019", "g_presentation_l1", "expense_update_boundary", "EXP-EDIT-004", "修改已存在费用的图标", "唯一请求变化为 presentation icon；标题、备注等 before 值来自可见 verified expense read。", "把这笔费用的图标换成餐饮。")
    add("sample_gs_p0_015", "g_financial_d4", "expense_update_boundary", "EXP-EDIT-001", "修改已存在费用的金额", "同一被核验费用改金额时输出完整 D4 diff，execution_allowed=false。", "把这笔费用金额改成135 CNY。", {"120": "135"})
    # H: L2 delete target ambiguity must be resolved before any destructive proposal.
    add("sample_gs_p0_043", "h_gated_delete_l2", "gated_delete", "DEL-001", "删除目标有多个候选", "同名费用查询返回两个对象；在用户选择前不得生成 L2 删除方案。", "帮我把设备租赁这笔费用删掉。", {"设备维修": "设备租赁"})

    # Rebuild C around a single source example; the only state change is current-user binding.
    c_unbound_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_c_payer_unbound")
    c_unbound_sm = next(x for x in samples if x["sample_id"] == "sample_v02_c_payer_unbound")
    c_bound_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_c_payer_bound")
    c_bound_sm = next(x for x in samples if x["sample_id"] == "sample_v02_c_payer_bound")
    c_bound_sm["surface_form"]["user_message"] = "2026-09-12 12:30 木桥晚餐 74 CNY，我付，和李四AA。"
    c_bound_sm["input"]["user_message"] = c_bound_sm["surface_form"]["user_message"]
    for f in c_bound_sc["state"]["facts"].get("recorded_facts", []):
        if f["field"] == "user_message": f["value"] = c_bound_sm["input"]["user_message"]
        if f["field"] == "occurred_at": f["value"] = "2026-09-12T12:30:00+08:00"
    c_bound_sc["state"]["facts"]["operation_arguments"]["occurred_at"] = "2026-09-12T12:30:00+08:00"
    c_bound_sc["operation"]["arguments"] = copy.deepcopy(c_bound_sc["state"]["facts"]["operation_arguments"])
    c_bound_sm["expected"]["model_output"]["operation"]["arguments"]["occurred_at"] = "2026-09-12T12:30:00+08:00"
    c_bound_sm["expected"]["model_output"]["preview"]["diff"][0]["after"] = copy.deepcopy(c_bound_sm["expected"]["model_output"]["operation"]["arguments"])
    c_bound_sm["expected"]["expected_diff"] = copy.deepcopy(c_bound_sm["expected"]["model_output"]["preview"]["diff"])
    c_bound_sc["ground_truth"]["model_output"] = copy.deepcopy(c_bound_sm["expected"]["model_output"])
    # Participant resolution for 李四 is an actual, typed runtime result shared by the pair.
    install_lookup(c_bound_sc, c_bound_sm, "unique", ["李四"])
    c_bound_sc["state"]["facts"]["supporting_lookup_result"]["query"] = "李四"
    c_bound_sc["ground_truth"]["expected_business_result"]["supporting_lookup"] = copy.deepcopy(c_bound_sc["state"]["facts"]["supporting_lookup_result"])
    c_unbound_sm["input"] = copy.deepcopy(c_bound_sm["input"])
    c_unbound_sm["surface_form"]["user_message"] = c_bound_sm["surface_form"]["user_message"]
    c_unbound_sm["input"]["user_message"] = c_bound_sm["input"]["user_message"]
    c_unbound_sm["input"]["user_context"]["claimed_participant_id"] = None
    c_unbound_sm["input"]["user_context"]["role_hint"] = c_bound_sm["input"]["user_context"].get("role_hint")
    c_unbound_sc["state"] = copy.deepcopy(c_bound_sc["state"])
    c_unbound_sc["state"]["facts"]["recorded_facts"] = [f for f in c_unbound_sc["state"]["facts"]["recorded_facts"] if f["field"] not in ("payer_participant_id", "user_message")]
    c_unbound_sc["state"]["facts"]["recorded_facts"].extend([
        {"field": "payer_name", "value": "我", "source": "user_input"},
        {"field": "payer_participant_id", "value": None, "source": "missing"},
        {"field": "user_message", "value": c_unbound_sm["input"]["user_message"], "source": "user_input"},
    ])
    c_unbound_sc["state"]["facts"]["recorded_facts"] = list({(f["field"], json.dumps(f["value"], ensure_ascii=False, sort_keys=True)): f for f in c_unbound_sc["state"]["facts"]["recorded_facts"]}.values())
    c_unbound_sc["state"]["facts"]["operation_arguments"] = {"activity_id": c_unbound_sc["state"]["facts"]["activity_id"], "ledger_unit_id": c_unbound_sc["state"]["facts"]["ledger_unit_id"], "title": "木桥晚餐", "original_amount": "74", "original_currency": "CNY", "payer_participant_id": None}
    c_unbound_sc["operation"] = {"type": "clarify", "intent_ids": ["create_expense"], "tool_id": None, "arguments": copy.deepcopy(c_unbound_sc["state"]["facts"]["operation_arguments"]), "description": "用户称自己付款但该 Activity 缺少 claimed participant 绑定，因此澄清付款人。"}
    c_unbound_sm["scope"] = copy.deepcopy(c_bound_sm["scope"])
    c_unbound_sm["expected"]["output_type"] = "clarification"
    c_unbound_sm["expected"]["model_output"] = {"type": "clarification", "intent_id": "create_expense", "reason": "missing_fields", "missing_fields": ["payer"], "question": "此 Activity 中‘我’对应哪位参与人？", "candidates": []}
    c_unbound_sm["expected"]["clarification_annotation"] = {"reason": "missing_fields", "missing_fields": ["payer"], "candidate_entity_ids": [], "question": c_unbound_sm["expected"]["model_output"]["question"]}
    c_unbound_sm["expected"]["execution"] = {"execution_allowed": False, "confirmation_level": 1, "confirmation_required": False, "final_authorization": "not_applicable", "successful_execution_label_allowed": False}
    c_unbound_sc["ground_truth"]["model_output"] = copy.deepcopy(c_unbound_sm["expected"]["model_output"])
    c_unbound_sc["ground_truth"]["expected_output_type"] = "clarification"
    c_unbound_sc["ground_truth"]["expected_business_result"] = {"missing_field": "payer", "lookup_result_id": c_bound_sc["state"]["facts"]["supporting_lookup_result"]["result_id"]}
    c_unbound_sc["ground_truth"]["deterministic_assertions"] = ["缺少 claimed participant 时不把‘我’绑定到付款人 ID。"]

    # D compares one visible current Activity against no active target and two UI-visible Activity candidates.
    d_amb_sc, d_amb_sm = make_pair("sample_gs_p0_021", "unused", "sample_v02_d_activity_ambiguous", "scenario_v02_d_activity_ambiguous", "family_v02_activity_ui_target", "split_v02_activity_ui_target", "ACT-002", "Activity 目标未唯一", "首页可见两个 Activity 且没有当前选择；同一个查询必须澄清目标。", "找一下上周的湖畔晚餐费用。")
    d_sel_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_d_activity_selected")
    d_sel_sm = next(x for x in samples if x["sample_id"] == "sample_v02_d_activity_selected")
    d_sel_sc, d_sel_sm = make_pair("sample_gs_p0_021", "unused", "sample_v02_d_activity_selected", "scenario_v02_d_activity_selected", "family_v02_activity_ui_target", "split_v02_activity_ui_target", "ACT-002", "当前 Activity 已明确", "当前 Activity 唯一时，对同一费用查询调用只读 find_expenses。", "找一下上周的湖畔晚餐费用。")
    d_act1, d_act2 = stable_id("v02-activity-a"), stable_id("v02-activity-b")
    d_ledger1, d_ledger2 = stable_id("v02-ledger-a"), stable_id("v02-ledger-b")
    d_amb_sm["input"]["ui_context"].update({"route": "home", "page_type": "home", "activity_id": None, "ledger_unit_id": None, "selected_entity": None})
    d_amb_sm["input"]["conversation_context"]["active_activity_id"] = None
    d_amb_sm["input"]["page_state"]["visible_entities"] = [
        {"type": "activity", "id": d_act1, "activity_id": d_act1}, {"type": "activity", "id": d_act2, "activity_id": d_act2}]
    d_amb_sc["state"]["entities"] = [
        {"alias": "A001", "id": d_act1, "type": "activity", "display_name": "湖畔活动", "activity_id": d_act1},
        {"alias": "A002", "id": d_act2, "type": "activity", "display_name": "山路活动", "activity_id": d_act2}]
    d_amb_sc["state"]["facts"].update({"activity_id": None, "ledger_unit_id": None, "operation_arguments": {"query": "2026-09-14的湖畔晚餐"}, "ui_context": {"page_type": "home", "active_activity_id": None, "visible_activity_ids": [d_act1, d_act2], "source": "ui_context"}})
    d_amb_sc["operation"] = {"type": "clarify", "intent_ids": ["find_expenses"], "tool_id": None, "arguments": {"query": "2026-09-14的湖畔晚餐"}, "description": "首页没有唯一 Activity 目标，不能运行活动内费用查询。"}
    d_amb_sc["ground_truth"]["intent_ids"] = ["find_expenses"]
    d_amb_sc["scope"] = {"ai_scope": "CORE", "intent_ids": ["find_expenses"], "tool_ids": ["find_expenses"]}
    d_amb_sc["rule_tags"] = list(dict.fromkeys(d_amb_sc["rule_tags"] + ["clarification", "ui_context", "entity_resolution"]))
    d_amb_sm["scope"] = copy.deepcopy(d_amb_sc["scope"])
    d_amb_sm["expected"]["output_type"] = "clarification"
    d_amb_sm["expected"]["model_output"] = {"type": "clarification", "intent_id": "find_expenses", "reason": "ambiguous_entity", "missing_fields": ["activity_id"], "question": "当前有两个活动目标；请选择列表中的第一个还是第二个活动。", "candidates": [{"label": "列表中的第一个活动", "entity": {"type": "activity", "id": d_act1, "activity_id": d_act1}}, {"label": "列表中的第二个活动", "entity": {"type": "activity", "id": d_act2, "activity_id": d_act2}}]}
    d_amb_sm["expected"]["clarification_annotation"] = {"reason": "ambiguous_entity", "missing_fields": ["activity_id"], "candidate_entity_ids": [d_act1, d_act2], "question": d_amb_sm["expected"]["model_output"]["question"]}
    d_amb_sm["expected"]["execution"] = {"execution_allowed": False, "confirmation_level": 0, "confirmation_required": False, "final_authorization": "not_applicable", "successful_execution_label_allowed": False}
    d_amb_sc["ground_truth"]["model_output"] = copy.deepcopy(d_amb_sm["expected"]["model_output"])
    d_amb_sc["ground_truth"]["expected_output_type"] = "clarification"
    d_sel_sm["input"]["user_message"] = d_sel_sm["surface_form"]["user_message"] = "找一下2026-09-14的湖畔晚餐费用。"
    d_sel_sc["state"]["facts"]["recorded_facts"] = [{"field": "user_message", "value": d_sel_sm["input"]["user_message"], "source": "user_input"}]
    d_sel_sc["state"]["facts"]["recorded_facts"].append({"field": "query", "value": "2026-09-14的湖畔晚餐", "source": "user_input"})
    d_amb_sc["state"]["facts"]["recorded_facts"] = [{"field": "user_message", "value": d_amb_sm["input"]["user_message"], "source": "user_input"}, {"field": "query", "value": "2026-09-14的湖畔晚餐", "source": "user_input"}]
    d_sel_sm["input"]["ui_context"].update({"route": "activity/" + d_sel_sc["state"]["facts"]["activity_id"], "page_type": "normal_activity"})
    d_sel_sm["input"]["conversation_context"]["active_activity_id"] = d_sel_sc["state"]["facts"]["activity_id"]
    d_sel_sm["input"]["page_state"]["visible_entities"] = [{"type": "activity", "id": d_sel_sc["state"]["facts"]["activity_id"], "activity_id": d_sel_sc["state"]["facts"]["activity_id"]}]
    d_sel_sc["state"]["facts"]["operation_arguments"] = {"activity_id": d_sel_sc["state"]["facts"]["activity_id"], "query": "2026-09-14的湖畔晚餐"}
    d_sel_sc["operation"]["arguments"] = copy.deepcopy(d_sel_sc["state"]["facts"]["operation_arguments"])
    d_sel_sm["expected"]["model_output"]["arguments"] = copy.deepcopy(d_sel_sc["operation"]["arguments"])
    d_sel_sc["ground_truth"]["model_output"] = copy.deepcopy(d_sel_sm["expected"]["model_output"])
    d_sel_sc["ground_truth"]["intent_ids"] = ["find_expenses"]
    d_sel_sc["scope"] = {"ai_scope": "CORE", "intent_ids": ["find_expenses"], "tool_ids": ["find_expenses"]}
    d_sel_sc["state"]["entities"] = [e for e in d_sel_sc["state"]["entities"] if e["type"] in ("activity", "ledger_unit")]
    d_sel_sm["scope"] = copy.deepcopy(d_sel_sc["scope"])

    # E: same current question; only the recent action's success/entity binding changes.
    e_failed_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_e_recent_failed")
    e_failed_sm = next(x for x in samples if x["sample_id"] == "sample_v02_e_recent_failed")
    e_success_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_e_recent_succeeded")
    e_success_sm = next(x for x in samples if x["sample_id"] == "sample_v02_e_recent_succeeded")
    e_message = "刚才那笔费用是谁付的？"
    for sm in (e_failed_sm, e_success_sm):
        sm["surface_form"]["user_message"] = e_message
        sm["input"]["user_message"] = e_message
        sm["input"]["ui_context"].update({"route": "activity/" + sm["input"]["ui_context"]["activity_id"], "page_type": "normal_activity", "selected_entity": None})
        sm["input"]["client_context"]["sent_at"] = "2026-09-30T09:31:00+08:00"
        sm["input"]["server_context"]["generated_at"] = "2026-09-30T09:31:00+08:00"
    recent_action_id = stable_id("v02-recent-action")
    recent_at = "2026-09-30T09:30:00+08:00"
    expense_id = e_success_sc["operation"]["arguments"]["expense_id"]
    activity_id = e_success_sc["state"]["facts"]["activity_id"]
    failed_action = {"action_id": stable_id("v02-recent-failed"), "intent_id": "query_expense", "entity": None, "activity_id": activity_id, "occurred_at": recent_at, "status": "failed", "result_id": None, "financial_version_hint": None}
    success_action = {"action_id": recent_action_id, "intent_id": "query_expense", "entity": {"type": "expense", "id": expense_id, "activity_id": activity_id}, "activity_id": activity_id, "occurred_at": recent_at, "status": "succeeded", "result_id": "result-v02-recent-success", "financial_version_hint": "3"}
    e_failed_sm["input"]["recent_actions"] = [failed_action]
    e_success_sm["input"]["recent_actions"] = [success_action]
    # Hold system/context/history/current-user input constant except the recent action state.
    failed_action_copy = copy.deepcopy(failed_action)
    e_failed_sm["input"] = copy.deepcopy(e_success_sm["input"])
    e_failed_sm["input"]["recent_actions"] = [failed_action_copy]
    e_failed_sm["surface_form"]["conversation"] = copy.deepcopy(e_success_sm["surface_form"]["conversation"])
    e_failed_sm["surface_form"]["context_turn_count"] = e_success_sm["surface_form"]["context_turn_count"]
    e_failed_sc["state"]["facts"]["recent_actions"] = [copy.deepcopy(failed_action)]
    e_success_sc["state"]["facts"]["recent_actions"] = [copy.deepcopy(success_action)]
    e_failed_sc["state"]["facts"].pop("interaction_context", None)
    e_success_sc["state"]["facts"]["ui_context"] = {"page_type": "normal_activity", "selected_entity": None, "source": "ui_context"}
    e_failed_sc["operation"] = {"type": "clarify", "intent_ids": ["clarify_reference"], "tool_id": None, "arguments": {"reference": "刚才那笔"}, "description": "最近查询失败且没有实体或结果，不能把自然语言指代解析成费用。"}
    e_failed_sc["state"]["facts"]["operation_arguments"] = copy.deepcopy(e_failed_sc["operation"]["arguments"])
    e_failed_sc["ground_truth"]["intent_ids"] = ["query_expense"]
    e_failed_sc["scope"] = {"ai_scope": "CORE", "intent_ids": ["query_expense"], "tool_ids": ["get_expense"]}
    e_failed_sm["scope"] = copy.deepcopy(e_failed_sc["scope"])
    e_failed_sc["operation"]["intent_ids"] = ["query_expense"]
    e_failed_sm["expected"]["output_type"] = "clarification"
    e_failed_sm["expected"]["model_output"] = {"type": "clarification", "intent_id": "query_expense", "reason": "unresolved_reference", "missing_fields": ["expense_id"], "question": "刚才的费用查询没有成功。请重新打开或描述那笔费用。", "candidates": []}
    e_failed_sm["expected"]["clarification_annotation"] = {"reason": "unresolved_reference", "missing_fields": ["expense_id"], "candidate_entity_ids": [], "question": e_failed_sm["expected"]["model_output"]["question"]}
    e_failed_sm["expected"]["execution"] = {"execution_allowed": False, "confirmation_level": 0, "confirmation_required": False, "final_authorization": "not_applicable", "successful_execution_label_allowed": False}
    e_failed_sc["ground_truth"]["model_output"] = copy.deepcopy(e_failed_sm["expected"]["model_output"])
    e_failed_sc["ground_truth"]["expected_output_type"] = "clarification"
    e_failed_sc["ground_truth"]["expected_business_result"] = {"reference_resolved": False, "recent_action_status": "failed"}
    e_success_sc["operation"]["description"] = "最近成功操作提供唯一 Expense ID；只读 get_expense 可按该 ID 查询。"
    e_success_sc["state"]["facts"]["operation_arguments"] = copy.deepcopy(e_success_sc["operation"]["arguments"])
    e_success_sc["ground_truth"]["model_output"] = copy.deepcopy(e_success_sm["expected"]["model_output"])

    def make_expense(expense_id, activity_id, ledger_id, title, amount, payer_id, split_id, occurred_at, icon="money", version="1"):
        return {"id": expense_id, "activity_id": activity_id, "ledger_unit_id": ledger_id, "title": title,
                "original": {"amount": amount, "currency": "CNY"}, "base": {"amount": amount, "currency": "CNY"},
                "fx_snapshot": {"rate": "1", "source": "base_currency", "observed_at": None}, "split_method": "manual",
                "payments": [{"participant_id": payer_id, "amount": amount}], "splits": [{"participant_id": split_id, "amount": amount}],
                "occurred_at": occurred_at, "note": None, "icon_key": icon, "original_expense_id": None,
                "financial_locked": False, "version": version, "is_deleted": False}

    # F answer cites a typed get_expense result, including the payer identifier needed by the question.
    f_expense_id = fsm["input"]["ui_context"]["selected_entity"]["id"]
    f_activity = fsm["input"]["ui_context"]["activity_id"]
    f_ledger = fsm["input"]["ui_context"]["ledger_unit_id"]
    f_participants = [e["id"] for e in fsc["state"]["entities"] if e["type"] == "participant"]
    f_title, f_amount, f_result = "溪边停车费", "43", "result-v02-expense-answer"
    f_expense = make_expense(f_expense_id, f_activity, f_ledger, f_title, f_amount, f_participants[0], f_participants[-1], "2026-09-14T10:30:00+08:00")
    fsm["input"]["server_context"]["tool_results"] = [{"tool": "get_expense", "result": {"status": "success", "result_id": f_result, "observed_at": "2026-09-30T10:00:00+08:00", "financial_version": "4", "data": {"expense": f_expense, "repayment_progress": []}}}]
    fsm["input"]["server_context"]["verified_result_ids"] = [f_result]
    fsm["expected"]["model_output"]["content"] = f"这笔“{f_title}”的付款参与人 ID 是 {f_participants[0]}。"
    fsm["expected"]["model_output"]["evidence_result_ids"] = [f_result]
    fsm["expected"]["evidence_result_ids"] = [f_result]
    fsc["state"]["facts"]["supporting_lookup_result"] = {"tool": "get_expense", "arguments": {"expense_id": f_expense_id, "activity_id": f_activity}, "result_id": f_result, "source": "server_result", "expense": f_expense}
    fsc["ground_truth"]["expected_business_result"] = {"result_id": f_result, "expense_title": f_title, "original_amount": f_amount, "original_currency": "CNY", "payer_participant_id": f_participants[0]}
    fsc["ground_truth"]["model_output"] = copy.deepcopy(fsm["expected"]["model_output"])
    fsc["ground_truth"]["expected_business_result"]["evidence_result_ids"] = [f_result]
    fsc["operation"]["type"] = "query"
    fsc["operation"]["intent_ids"] = ["query_expense"]

    # D4's financial before-values are copied from its verified read into visible runtime Tool Result.
    g_d4_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_g_financial_d4")
    g_d4_sm = next(x for x in samples if x["sample_id"] == "sample_v02_g_financial_d4")
    d4_read = g_d4_sc["state"]["facts"]["verified_read_result"]
    d4_result = {"status": "success", "result_id": d4_read["result_id"], "observed_at": "2026-09-30T10:00:00+08:00", "financial_version": d4_read["financial_version"], "data": {"expense": d4_read["expense"], "repayment_progress": d4_read.get("repayment_progress", [])}}
    g_d4_sm["input"]["server_context"]["tool_results"] = [{"tool": "get_expense", "result": d4_result}]
    g_d4_sm["input"]["server_context"]["verified_result_ids"] = [d4_read["result_id"]]
    g_d4_sm["input"]["server_context"]["enabled_tools"] = ["get_expense"]
    g_d4_sc["state"]["facts"]["recorded_facts"] = [f for f in g_d4_sc["state"]["facts"].get("recorded_facts", []) if f["field"] not in ("user_message", "expense.original_amount")]
    g_d4_sc["state"]["facts"]["recorded_facts"].extend([
        {"field": "user_message", "value": g_d4_sm["input"]["user_message"], "source": "user_input"},
        {"field": "expense.original_amount", "value": d4_read["expense"]["original"]["amount"], "source": "server_result"}])
    g_d4_sc["state"]["facts"]["operation_arguments"] = copy.deepcopy(g_d4_sm["expected"]["model_output"]["operation"]["arguments"])
    g_d4_sc["operation"]["arguments"] = copy.deepcopy(g_d4_sc["state"]["facts"]["operation_arguments"])
    g_d4_sc["ground_truth"]["model_output"] = copy.deepcopy(g_d4_sm["expected"]["model_output"])
    g_d4_sc["ground_truth"]["expected_business_result"]["expected_diff"] = copy.deepcopy(g_d4_sm["expected"]["expected_diff"])

    # Presentation-only update reads the current complete values and changes only icon_key.
    g_pres_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_g_presentation_l1")
    g_pres_sm = next(x for x in samples if x["sample_id"] == "sample_v02_g_presentation_l1")
    pres_activity, pres_ledger = g_d4_sc["state"]["facts"]["activity_id"], g_d4_sc["state"]["facts"]["ledger_unit_id"]
    pres_expense = d4_read["expense"]["id"]
    pres_entities = [e["id"] for e in g_d4_sc["state"]["entities"] if e["type"] == "participant"]
    if not pres_entities:
        pres_entities = [stable_id("v02-presentation-payer"), stable_id("v02-presentation-split")]
        g_pres_sc["state"]["entities"].extend([
            {"alias": "P003", "id": pres_entities[0], "type": "participant", "display_name": "周宁", "activity_id": pres_activity},
            {"alias": "P004", "id": pres_entities[1], "type": "participant", "display_name": "陈一", "activity_id": pres_activity}])
    pres_data = copy.deepcopy(d4_read["expense"])
    pres_title = pres_data["title"]
    pres_result = "result-v02-presentation-read"
    g_pres_sm["input"]["server_context"]["enabled_tools"] = ["get_expense", "update_expense_presentation"]
    g_pres_sm["scope"]["tool_ids"] = ["update_expense_presentation"]
    g_pres_sc["scope"]["tool_ids"] = ["update_expense_presentation"]
    g_pres_sm["input"]["server_context"]["tool_results"] = [{"tool": "get_expense", "result": {"status": "success", "result_id": pres_result, "observed_at": "2026-09-30T10:00:00+08:00", "financial_version": "2", "data": {"expense": pres_data, "repayment_progress": []}}}]
    g_pres_sm["input"]["server_context"]["verified_result_ids"] = [pres_result]
    pres_args = {"activity_id": pres_activity, "expense_id": pres_expense, "title": pres_title, "note": pres_data["note"], "icon_key": "dining", "expected_version": pres_data["version"]}
    g_pres_sm["expected"]["model_output"]["operation"]["arguments"] = pres_args
    g_pres_sm["expected"]["model_output"]["preview"]["summary"] = "拟仅将这笔费用的图标改为餐饮。"
    g_pres_sm["expected"]["model_output"]["preview"]["diff"] = [{"field": "icon_key", "before": "money", "after": "dining"}]
    g_pres_sm["expected"]["expected_diff"] = copy.deepcopy(g_pres_sm["expected"]["model_output"]["preview"]["diff"])
    g_pres_sm["input"]["user_message"] = g_pres_sm["surface_form"]["user_message"] = "把这笔费用的图标换成餐饮。"
    g_pres_sm["input"]["ui_context"].update({"activity_id": pres_activity, "ledger_unit_id": pres_ledger, "selected_entity": {"type": "expense", "id": pres_expense, "activity_id": pres_activity}, "route": f"expense-detail/{pres_expense}"})
    g_pres_sc["state"]["entities"] = copy.deepcopy(g_d4_sc["state"]["entities"])
    g_pres_sc["state"]["facts"].update({"activity_id": pres_activity, "ledger_unit_id": pres_ledger})
    g_pres_sc["state"]["facts"]["verified_read_result"] = {"tool": "get_expense", "result_id": pres_result, "financial_version": str(pres_data["version"]), "expense": pres_data, "source": "server_result"}
    g_pres_sc["state"]["facts"]["ui_context"] = {"page_type": "expense_detail", "activity_id": pres_activity, "ledger_unit_id": pres_ledger, "selected_entity": {"type": "expense", "id": pres_expense, "activity_id": pres_activity}, "source": "ui_context"}
    g_pres_sc["state"]["facts"]["recorded_facts"] = [
        {"field": "user_message", "value": g_pres_sm["input"]["user_message"], "source": "user_input"},
        {"field": "requested_icon", "value": "餐饮", "source": "user_input"},
        {"field": "ui_context.selected_entity", "value": pres_expense, "source": "ui_context"},
        {"field": "expense.title", "value": pres_title, "source": "server_result"},
        {"field": "expense.icon_key", "value": pres_data["icon_key"], "source": "server_result"},
        {"field": "expense.version", "value": str(pres_data["version"]), "source": "server_result"},
    ]
    g_pres_sc["state"]["facts"]["operation_arguments"] = copy.deepcopy(pres_args)
    g_pres_sc["operation"]["arguments"] = copy.deepcopy(pres_args)
    g_pres_sc["operation"]["tool_id"] = "update_expense_presentation"
    g_pres_sc["ground_truth"]["model_output"] = copy.deepcopy(g_pres_sm["expected"]["model_output"])
    g_pres_sc["ground_truth"]["expected_business_result"] = {"result_id": pres_result, "changed_field": "icon_key", "before": "money", "after": "dining", "confirmation_level": 1}

    # H is deliberately rebuilt as a genuinely new L2 boundary: a verified multiple match
    # requires target clarification before any delete proposal. v0.1 train already covers
    # unique selected-target L2 proposals, so repeating that state would add no new signal.
    h_sc = next(x for x in scenarios if x["scenario_id"] == "scenario_v02_h_gated_delete_l2")
    h_sm = next(x for x in samples if x["sample_id"] == "sample_v02_h_gated_delete_l2")
    h_activity = h_sc["state"]["facts"]["activity_id"]
    h_ledger = h_sc["state"]["facts"]["ledger_unit_id"]
    h_pids = [e["id"] for e in h_sc["state"]["entities"] if e["type"] == "participant"]
    if not h_pids:
        h_pids = [stable_id("v02-delete-payer"), stable_id("v02-delete-split")]
        h_sc["state"]["entities"].extend([
            {"alias": "P005", "id": h_pids[0], "type": "participant", "display_name": "周宁", "activity_id": h_activity},
            {"alias": "P006", "id": h_pids[1], "type": "participant", "display_name": "陈一", "activity_id": h_activity}])
    h_ids = [stable_id("v02-delete-candidate-1"), stable_id("v02-delete-candidate-2")]
    h_expenses = [
        make_expense(h_ids[0], h_activity, h_ledger, "设备租赁", "100", h_pids[0], h_pids[1], "2026-09-10T10:00:00+08:00", version="1"),
        make_expense(h_ids[1], h_activity, h_ledger, "设备租赁", "125", h_pids[0], h_pids[1], "2026-09-12T10:00:00+08:00", version="1")]
    h_result = "result-v02-delete-multiple"
    h_user = "帮我把设备租赁这笔费用删掉。"
    h_sm["input"]["user_message"] = h_sm["surface_form"]["user_message"] = h_user
    h_sm["input"]["ui_context"].update({"route": "activity/" + h_activity, "page_type": "normal_activity", "activity_id": h_activity, "ledger_unit_id": h_ledger, "selected_entity": None, "form_mode": None})
    h_sm["input"]["conversation_context"]["active_activity_id"] = h_activity
    h_sm["input"]["server_context"]["enabled_tools"] = ["find_expenses"]
    h_sm["input"]["server_context"]["tool_results"] = [{"tool": "find_expenses", "result": {"status": "success", "result_id": h_result, "observed_at": "2026-09-30T10:00:00+08:00", "financial_version": "1", "data": {"items": h_expenses, "next_cursor": None, "truncated": False}}}]
    h_sm["input"]["server_context"]["verified_result_ids"] = [h_result]
    h_sm["input"]["page_state"]["visible_entities"] = []
    h_candidates = [{"label": "设备租赁（100 CNY，2026-09-10）", "entity": {"type": "expense", "id": h_ids[0], "activity_id": h_activity}}, {"label": "设备租赁（125 CNY，2026-09-12）", "entity": {"type": "expense", "id": h_ids[1], "activity_id": h_activity}}]
    h_output = {"type": "clarification", "intent_id": "delete_expense", "reason": "ambiguous_entity", "missing_fields": ["expense_id"], "question": "查到两笔“设备租赁”，你要删除哪一笔？", "candidates": h_candidates}
    h_sm["expected"]["output_type"] = "clarification"
    h_sm["expected"]["model_output"] = copy.deepcopy(h_output)
    h_sm["expected"]["clarification_annotation"] = {"reason": "ambiguous_entity", "missing_fields": ["expense_id"], "candidate_entity_ids": h_ids, "question": h_output["question"]}
    h_sm["expected"]["execution"] = {"execution_allowed": False, "confirmation_level": 2, "confirmation_required": False, "final_authorization": "not_applicable", "successful_execution_label_allowed": False}
    h_sm["expected"].pop("expected_diff", None)
    h_sm["expected"]["evidence_result_ids"] = [h_result]
    h_sc["state"]["facts"].update({"activity_id": h_activity, "ledger_unit_id": h_ledger,
        "ui_context": {"page_type": "normal_activity", "active_activity_id": h_activity, "selected_entity": None, "source": "ui_context"},
        "operation_arguments": {"activity_id": h_activity, "query": "设备租赁"},
        "supporting_lookup_result": {"tool": "find_expenses", "arguments": {"activity_id": h_activity, "query": "设备租赁"}, "result_id": h_result, "source": "server_result", "status": "success", "cardinality": "multiple", "items": h_expenses}})
    h_sc["state"]["entities"] = [e for e in h_sc["state"]["entities"] if e["type"] in ("activity", "ledger_unit", "participant")]
    h_sc["state"]["entities"].extend([{"alias": f"E{i+1:03}", "id": e["id"], "type": "expense", "display_name": e["title"], "activity_id": h_activity} for i,e in enumerate(h_expenses)])
    h_sc["operation"] = {"type": "clarify", "intent_ids": ["delete_expense"], "tool_id": None, "arguments": {"activity_id": h_activity, "query": "设备租赁"}, "description": "已验证查询命中两笔同名费用；必须由用户选择目标后才能评估 L2 删除提案。"}
    h_sc["rule_tags"] = list(dict.fromkeys(h_sc["rule_tags"] + ["clarification", "entity_resolution"]))
    h_sc["scope"] = {"ai_scope": "SUPPORTED_BUT_GATED", "intent_ids": ["delete_expense"], "tool_ids": ["find_expenses", "delete_expense"]}
    h_sm["scope"] = copy.deepcopy(h_sc["scope"])
    h_sc["ground_truth"].update({"intent_ids": ["delete_expense"], "expected_output_type": "clarification", "model_output": copy.deepcopy(h_output), "execution_policy": {"execution_allowed": False, "confirmation_level": 2, "confirmation_required": False, "final_authorization": "not_applicable", "successful_execution_label_allowed": False}, "expected_business_result": {"result_id": h_result, "lookup_cardinality": "multiple", "candidate_expense_ids": h_ids, "selected_expense_id": None, "delete_scope": "L2"}})
    h_sc["state"]["facts"]["recorded_facts"] = [{"field": "user_message", "value": h_user, "source": "user_input"}, {"field": "query", "value": "设备租赁", "source": "user_input"}]
    h_sc["state"]["facts"].pop("permission_context", None)
    h_sm["expected"]["execution"]["confirmation_level"] = 2

    # B's four states share one precisely grounded request; update all authoritative facts from that message.
    b_message = "2026-09-29 10:00 溪谷聚餐 86 CNY，我和周宁AA，我先付。"
    for sc, sm in ((bcall_sc, bcall_sm), (bmultiple_sc, bmultiple_sm), (bzero_sc, bzero_sm), (bunique_sc, bunique_sm)):
        sm["surface_form"]["user_message"] = b_message
        sm["input"]["user_message"] = b_message
        facts = sc["state"]["facts"]
        facts["recorded_facts"] = [
            {"field": "user_message", "value": b_message, "source": "user_input"},
            {"field": "title", "value": "溪谷聚餐", "source": "user_input"},
            {"field": "original_amount", "value": "86", "source": "user_input"},
            {"field": "original_currency", "value": "CNY", "source": "user_input"},
            {"field": "occurred_at", "value": "2026-09-29T10:00:00+08:00", "source": "user_input"},
            {"field": "split_method", "value": "aa", "source": "user_input"},
            {"field": "payer_name", "value": "我", "source": "user_input"},
            {"field": "other_participant_name", "value": "周宁", "source": "user_input"},
        ]
        if "supporting_lookup_result" in facts:
            facts["supporting_lookup_result"]["query"] = "周宁"
        if sm["expected"]["output_type"] == "proposal":
            args = sm["expected"]["model_output"]["operation"]["arguments"]
            args.update({"title": "溪谷聚餐", "original_amount": "86", "original_currency": "CNY", "occurred_at": "2026-09-29T10:00:00+08:00"})
            if args.get("payments"):
                args["payments"][0]["amount"] = "86"
            sm["expected"]["model_output"]["preview"]["summary"] = "拟新增一笔溪谷聚餐支出。"
            sm["expected"]["model_output"]["preview"]["diff"][0]["after"] = copy.deepcopy(args)
            sm["expected"]["expected_diff"] = copy.deepcopy(sm["expected"]["model_output"]["preview"]["diff"])
            facts["operation_arguments"] = copy.deepcopy(args)
            sc["operation"]["arguments"] = copy.deepcopy(args)
            sc["ground_truth"]["expected_business_result"]["expected_diff"] = copy.deepcopy(sm["expected"]["expected_diff"])
            sc["ground_truth"]["model_output"] = copy.deepcopy(sm["expected"]["model_output"])
        else:
            for f in facts["recorded_facts"]:
                pass
        if sc["source"]["source_id"] == "EXP-CREATE-001":
            for e in sc["state"]["entities"]:
                if e["type"] == "participant" and e.get("alias") != "P001": e["display_name"] = "周宁"
    for sm in (bmultiple_sm, bunique_sm):
        items = sm["input"]["server_context"]["tool_results"][0]["result"]["data"]["items"]
        for item in items: item["name"] = "周宁"
    # Keep scenario/tool operation arguments aligned after the request rewrite.
    for sc in (bcall_sc, bmultiple_sc, bzero_sc):
        sc["state"]["facts"]["operation_arguments"] = copy.deepcopy(sc["operation"]["arguments"])
    # Keep every B request fact fixed; only the verified lookup state/cardinality changes.
    b_claim = bunique_sm["input"]["user_context"].get("claimed_participant_id")
    b_activity = bcall_sm["input"]["ui_context"]["activity_id"]
    b_ledger = bcall_sm["input"]["ui_context"]["ledger_unit_id"]
    b_ui = {"route": "activity/" + b_activity, "page_type": "normal_activity", "screen_instance_id": stable_id("v02-b-common-screen"), "activity_id": b_activity, "ledger_unit_id": b_ledger, "selected_entity": None, "form_mode": None, "focused_field": None}
    for sm in (bcall_sm, bmultiple_sm, bzero_sm, bunique_sm):
        sm["input"]["user_context"]["claimed_participant_id"] = b_claim
        sm["input"]["user_context"]["role_hint"] = "member"
        sm["input"]["ui_context"] = copy.deepcopy(b_ui)
        sm["input"]["conversation_context"]["active_activity_id"] = b_activity
        sm["input"]["server_context"]["enabled_tools"] = ["find_participants", "create_expense"]
    for sc in (bmultiple_sc, bzero_sc, bunique_sc):
        sc["ground_truth"]["expected_business_result"]["supporting_lookup"] = copy.deepcopy(sc["state"]["facts"]["supporting_lookup_result"])
    # Activity-selection comparison is a read-only query with an exact date, not a relative-time guess.
    for sc, sm in ((d_amb_sc, d_amb_sm), (d_sel_sc, d_sel_sm)):
        sm["surface_form"]["user_message"] = sm["input"]["user_message"] = "找一下2026-09-14的湖畔晚餐费用。"
        sc["state"]["facts"]["recorded_facts"] = [{"field": "user_message", "value": sm["input"]["user_message"], "source": "user_input"}]

    # Replace the draft Activity pair with its exact same-user-message read-query contrast.
    scenario_by_id = {x["scenario_id"]: x for x in scenarios}
    sample_by_id = {x["sample_id"]: x for x in samples}
    scenario_by_id[d_amb_sc["scenario_id"]] = d_amb_sc
    scenario_by_id[d_sel_sc["scenario_id"]] = d_sel_sc
    sample_by_id[d_amb_sm["sample_id"]] = d_amb_sm
    sample_by_id[d_sel_sm["sample_id"]] = d_sel_sm
    scenarios = list(scenario_by_id.values())
    samples = list(sample_by_id.values())

    # Mark the no-result and ambiguity cases with the actual lookup result and exact result IDs.
    bmultiple_sm["expected"]["model_output"]["candidates"] = [
        {"label": f"周宁（第{i + 1}位）", "entity": {"type": "participant", "id": x["id"], "activity_id": x["activity_id"]}}
        for i, x in enumerate(bmultiple_sm["input"]["server_context"]["tool_results"][0]["result"]["data"]["items"])]
    bmultiple_sm["expected"]["model_output"]["question"] = "查到两位同名参与人。你想和哪一位一起 AA？"
    bmultiple_sm["expected"]["clarification_annotation"] = {"reason": "ambiguous_entity", "missing_fields": [], "candidate_entity_ids": [x["entity"]["id"] for x in bmultiple_sm["expected"]["model_output"]["candidates"]], "question": bmultiple_sm["expected"]["model_output"]["question"]}
    bmultiple_sc["ground_truth"]["model_output"] = copy.deepcopy(bmultiple_sm["expected"]["model_output"])
    bmultiple_sc["state"]["facts"]["operation_arguments"] = {"activity_id": bmultiple_sc["state"]["facts"]["activity_id"], "query": "周宁"}
    bmultiple_sc["operation"]["arguments"] = copy.deepcopy(bmultiple_sc["state"]["facts"]["operation_arguments"])
    # Keep every B request fact fixed; only the verified lookup state/cardinality changes.
    b_claim = bunique_sm["input"]["user_context"].get("claimed_participant_id")
    b_activity = bcall_sm["input"]["ui_context"]["activity_id"]
    b_ledger = bcall_sm["input"]["ui_context"]["ledger_unit_id"]
    b_ui = {"route": "activity/" + b_activity, "page_type": "normal_activity", "screen_instance_id": stable_id("v02-b-common-screen"), "activity_id": b_activity, "ledger_unit_id": b_ledger, "selected_entity": None, "form_mode": None, "focused_field": None}
    for sm in (bcall_sm, bmultiple_sm, bzero_sm, bunique_sm):
        sm["input"]["user_context"]["claimed_participant_id"] = b_claim
        sm["input"]["user_context"]["role_hint"] = "member"
        sm["input"]["ui_context"] = copy.deepcopy(b_ui)
        sm["input"]["conversation_context"]["active_activity_id"] = b_activity
        sm["input"]["server_context"]["enabled_tools"] = ["find_participants", "create_expense"]
    for sc in (bmultiple_sc, bzero_sc, bunique_sc):
        sc["ground_truth"]["expected_business_result"]["supporting_lookup"] = copy.deepcopy(sc["state"]["facts"]["supporting_lookup_result"])
    # Case-specific task/challenge labels and refreshed recorded user-message evidence.
    scenario_specific_assertions = {
        "scenario_v02_b_lookup_not_run": ["候选尚未核验时只调用 find_participants 只读查询，工具参数中的 query 来自用户所称姓名。"],
        "scenario_v02_b_lookup_multiple": ["两个同名候选均来自已核验 Tool Result；用户选择前不绑定任一 payer，也不生成 create_expense Proposal。"],
        "scenario_v02_b_lookup_zero": ["已核验参与人查询 items 为空；不输出 Participant ID，并询问如何选择或补充参与人。"],
        "scenario_v02_b_lookup_unique": ["唯一候选 ID 与可见 Tool Result 一致；Proposal 将该候选绑定为 AA 参与人。"],
        "scenario_v02_c_payer_unbound": ["claimed_participant_id 为空时不能从‘我付’推定付款人 ID，必须询问绑定对象。"],
        "scenario_v02_c_payer_bound": ["claimed_participant_id 指向当前 Activity Participant 后，‘我付’绑定该付款人并形成待确认 Proposal。"],
        "scenario_v02_d_activity_ambiguous": ["当前没有唯一 Activity 目标；不得把创建请求静默绑定到某个可见活动。"],
        "scenario_v02_d_activity_selected": ["活动页面中的当前唯一 Activity 和 Ledger Unit 是 Proposal 的目标。"],
        "scenario_v02_e_recent_failed": ["失败的 recent action 没有稳定 Expense Entity；不得把‘刚才那笔’解析为该目标。"],
        "scenario_v02_e_recent_succeeded": ["成功的 recent action 明确携带单一 Expense ID；get_expense 只读参数与其 ID 一致。"],
        "scenario_v02_f_verified_expense_answer": ["用户明确询问付款参与人 ID；答案 ID 与可见已验证 get_expense Tool Result 的 payments[0].participant_id 一致。"],
        "scenario_v02_g_presentation_l1": ["请求只改变 presentation icon；Proposal diff 不改变金额、付款或分摊事实。"],
        "scenario_v02_g_financial_d4": ["金额修改保留 verified before 值并输出 D4 diff；execution_allowed 必须为 false。"],
        "scenario_v02_h_gated_delete_l2": ["同一 Activity 的已验证 lookup 返回两个同名 Expense；选择目标前不得输出 L2 删除 Proposal。"],
    }
    for sc, sm in zip(scenarios, samples):
        sm["input"]["client_context"]["sent_at"] = "2026-09-30T10:01:00+08:00"
        sm["input"]["server_context"]["generated_at"] = "2026-09-30T10:01:00+08:00"
        if sc["scenario_id"] in ("scenario_v02_a_currency_missing", "scenario_v02_a_currency_supplied"):
            date_prefix = "2026年9月14日12:30的"
            for key in ("surface_form", "input"):
                sm[key]["user_message"] = date_prefix + sm[key]["user_message"].replace("9月14日12:30的", "")
        for fact in sc["state"]["facts"].get("recorded_facts", []):
            if fact["field"] == "user_message": fact["value"] = sm["input"]["user_message"]
        # Remove stale template assertions; keep scenario-specific, human-checkable invariants.
        if sc["scenario_id"] in scenario_specific_assertions:
            sc["ground_truth"]["deterministic_assertions"] = scenario_specific_assertions[sc["scenario_id"]]
        sc["deduplication"]["canonical_facts_sha256"] = hashlib.sha256(json.dumps(sc["state"]["facts"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # Zero-result means there is no resolved participant entity in State.
    bzero_sc["state"]["entities"] = [e for e in bzero_sc["state"]["entities"] if e["type"] != "participant"]
    bzero_sc["state"]["facts"]["recorded_facts"] = [f for f in bzero_sc["state"]["facts"].get("recorded_facts", []) if f["field"] not in ("payer_participant_id", "other_participant_id")]
    bzero_sc["deduplication"]["canonical_facts_sha256"] = hashlib.sha256(json.dumps(bzero_sc["state"]["facts"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    write("scenarios.json", scenarios)
    write("samples.json", samples)
    group_specs = [
        ("family_v02_currency_sufficiency", "split_v02_currency_sufficiency", "original_currency absent vs explicitly supplied"),
        ("family_v02_participant_lookup", "split_v02_participant_lookup", "lookup state/cardinality not_run → multiple/zero/unique; only unique binds a proposal"),
        ("family_v02_payer_binding", "split_v02_payer_binding", "current-user participant binding absent vs explicit"),
        ("family_v02_activity_ui_target", "split_v02_activity_ui_target", "no unique Activity target vs current selected Activity"),
        ("family_v02_recent_action_reference", "split_v02_recent_action_reference", "same read query with failed/no entity vs succeeded/exact entity"),
        ("family_v02_verified_expense_answer", "split_v02_verified_expense_answer", "verified typed expense payload grounds the requested payer answer"),
        ("family_v02_expense_update_boundary", "split_v02_expense_update_boundary", "same visible expense: presentation-only L1 vs financial D4 preview"),
        ("family_v02_gated_delete", "split_v02_gated_delete", "verified multiple delete candidates require clarification before L2 proposal"),
    ]
    group_records = [{"family_id": fid, "split_group_id": sgid, "scenario_ids": [s["scenario_id"] for s in scenarios if s["scenario_family_id"] == fid], "decision_boundary": boundary} for fid, sgid, boundary in group_specs]
    write("decision_state_coverage.json", {"baseline": {"train_samples": 171, "train_scenarios": 36, "train_decision_states": 36, "gold_surfaces": 65, "teacher_surfaces": 106, "decision_signature_counts": {"proposal": 10, "clarification": 11, "tool_call": 5, "answer": 9, "unsupported": 1}}, "experiment_a": {"new_scenarios": len(scenarios), "new_distinct_ground_truths": len(scenarios), "new_business_states": len(scenarios), "new_samples": len(samples), "new_families": len(group_records), "groups": group_records}, "interpretation": "Scenario/GT state counts represent business decision states; Teacher surface variants in frozen train do not add distinct decision states. Family/split_group closure is preserved; no split is assigned."})


if __name__ == "__main__":
    main()
