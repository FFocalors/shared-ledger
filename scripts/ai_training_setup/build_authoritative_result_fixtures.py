#!/usr/bin/env python3
"""Build independent v0.2 fixtures from frozen authoritative sources only.

The rule adapter performs a real read of frozen policy documents at materialization.
It does not imitate a database/Gateway query. Existing read receipts are copied only
when they already have a complete source-backed Tool Catalog receipt.
"""
from __future__ import annotations
import copy, hashlib, json, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_result_fixtures"
SCENARIOS = ROOT / "docs/ai/dataset/canonical_training/v0.1/scenarios.json"
AUDIT = ROOT / "docs/ai/dataset/experiments/v0.2/experiment_b/grounding_audit.json"
CATALOG = ROOT / "docs/ai/schema/tool_catalog.json"
# Selectors depend on the user's lookup query's subject and frozen document headings,
# never on Expected GT text. Each selector returns an exact paragraph from authority.
RULE_SELECTORS = {
 "scenario_gs_p0b_009": ("docs/backend/BUSINESS_LOGIC.md", "12. Prepayment", "投影先扣有效真实"),
 "scenario_gs_p0b_033": ("docs/backend/BUSINESS_LOGIC.md", "7. AA", "AA 原币金额"),
 "scenario_gs_p0b_034": ("docs/backend/BUSINESS_LOGIC.md", "12. Prepayment", "投影先扣有效真实"),
 "scenario_gs_p0b_035": ("docs/backend/BUSINESS_LOGIC.md", "13. Refund", "只要曾经存在 linked refund"),
 "scenario_gs_p0b_036": ("docs/ai/AI_MODEL_CONTRACT.md", "", "可信 UI 确认"),
 "scenario_gs_p0b_038": ("docs/ai/AI_MODEL_CONTRACT.md", "", "页面、Activity、selected entity"),
 "scenario_gs_p0b_039": ("docs/backend/BUSINESS_LOGIC.md", "18. completed 与 archive", "Activity Creator 可手动 archive/unarchive"),
}


def sha(path: Path) -> str:
 return hashlib.sha256(path.read_bytes()).hexdigest()


def source_record(scenario: dict[str, Any], dotted: str) -> Any:
 cur: Any = scenario
 for part in re.split(r"\.(?![^\[]*\])", dotted):
  m = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
  if not m: raise ValueError(f"invalid source path {dotted!r}")
  cur = cur[m.group(1)]
  if m.group(2) is not None: cur = cur[int(m.group(2))]
 return cur


def paragraph(lines: list[str], index: int, marker: str) -> tuple[str, int, int]:
 start = index
 while start > 0 and lines[start-1].strip(): start -= 1
 end = index
 while end + 1 < len(lines) and lines[end+1].strip(): end += 1
 text = "\n".join(lines[start:end+1]).strip()
 if marker not in text: raise ValueError(f"selector marker {marker!r} not in selected paragraph")
 return text, start + 1, end + 1


def extract_authority(path: Path, heading: str, marker: str) -> tuple[str, str, str, str, str]:
 text = path.read_text(encoding="utf-8")
 lines = text.splitlines()
 start = 0
 if heading:
  start = next(i for i, line in enumerate(lines) if line.startswith("## ") and heading in line)
  end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
 else:
  end = len(lines)
 index = next(i for i in range(start, end) if marker in lines[i])
 para, first, last = paragraph(lines, index, marker)
 return para, f"{path.relative_to(ROOT).as_posix()}#L{first}-L{last}", sha(path), path.relative_to(ROOT).as_posix(), text


def build() -> dict[str, Any]:
 if (OUT/"result_fixtures.json").exists() and json.loads((OUT/"result_fixtures.json").read_text(encoding="utf-8")).get("fixtures"):
  raise RuntimeError("fixtures already capture real observation events; preserve their timestamps and edit only through reviewed migration")
 scenarios = {x["scenario_id"]:x for x in json.loads(SCENARIOS.read_text(encoding="utf-8"))}
 audit=json.loads(AUDIT.read_text(encoding="utf-8")); catalog=json.loads(CATALOG.read_text(encoding="utf-8"))
 registry=json.loads((OUT/"fixture_registry.json").read_text(encoding="utf-8"))
 alias={(x["scenario_id"],x["tool"],x["legacy_result_id"]):x["reserved_unique_fixture_id"] for x in registry["reserved_alias_bindings"]}
 fixtures=[]
 for sid,(rel,heading,marker) in RULE_SELECTORS.items():
  sc=scenarios[sid]; old=sc["state"]["facts"]["supporting_lookup_result"]
  if old.get("tool")!="lookup_business_rule": raise ValueError(f"unexpected source Tool for {sid}")
  source=ROOT/rel
  passage,source_ref,source_hash,source_path,doc_text=extract_authority(source,heading,marker)
  if not heading:
   lines=doc_text.splitlines(); ln=int(re.search(r"#L(\d+)", source_ref).group(1))
   section=next((lines[i][3:].strip() for i in range(ln-1,-1,-1) if lines[i].startswith("## ")), "AI_MODEL_CONTRACT")
  else:
   section=heading
  observed_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
  rid=alias[(sid,"lookup_business_rule",old["result_id"])]
  tool=next(x for x in catalog["tools"] if x["tool_name"]=="lookup_business_rule")
  baseline=tool["output_schema"]["oneOf"][0]["properties"]["data"]["properties"]["baseline_commit"]["const"]
  result={"status":"success","result_id":rid,"observed_at":observed_at,"financial_version":None,
          "data":{"baseline_commit":baseline,"passages":[{"section":section,"text":passage,"source":source_ref}]}}
  fixtures.append({"scenario_id":sid,"tool":"lookup_business_rule","legacy_result_id":old["result_id"],"result":result,
      "provenance":{"kind":"new_frozen_document_read_fixture","observation_event":"source document was read and exact matching section paragraph selected by fixed query-to-section selector during fixture build","source_path":source_path,"source_sha256":source_hash,"source_pointer":source_ref,"selection_rule":{"heading":heading,"exact_text_marker":marker},"sample_time_used":False,"expected_gt_used":False,"production_gateway_executed":False}})
 # The only formerly catalog-valid source pair noted by the earlier audit
 # (p0b014/get_final_settlement) fails the full nested Tool Catalog DTO check:
 # required payment/ordinary/prepayment-return/is_prepayment_return/path_currency/
 # source_financial_version are absent. It is intentionally not materialized.
 fixture_doc={"schema_version":"v0.2-authoritative-results-1","fixtures":fixtures}
 (OUT/"result_fixtures.json").write_text(json.dumps(fixture_doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 # Mark registry aliases materialized exactly when provenance was sourced and schema-checked.
 fixture_keys={(f["scenario_id"],f["tool"],f["legacy_result_id"]) for f in fixtures}
 for b in registry["reserved_alias_bindings"]:
  key=(b["scenario_id"],b["tool"],b["legacy_result_id"])
  b["materialized"]=key in fixture_keys
  b["usable_as_model_result_id"]=key in fixture_keys
  if key in fixture_keys: b["reason"]="Materialized fixture uses this collision-free pair-scoped result_id; sample source reference remains unchanged and is resolved by the v0.2 Scenario/Tool alias registry."
 registry["status"]="partial_fixtures_blocked_remaining_receipts"
 registry["fixture_ids_materialized"]=len(fixtures)
 (OUT/"fixture_registry.json").write_text(json.dumps(registry,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 # Row-level audit: policy-only fixture coverage is insufficient when the claim
 # requires a dynamic amount or another source without a materialized receipt.
 source_index={(x["scenario_id"],x["result_id"]):x for x in audit["result_source_inventory"]}
 fixture_index={(x["scenario_id"],x["tool"],x["legacy_result_id"]):x for x in fixtures}
 rows=[]
 for sample in audit["samples"]:
  if not sample["expected_external_result_facts_required"]: continue
  refs=[]
  for ref in sample["result_refs"]:
   source=source_index.get((sample["scenario_id"],ref["result_id"]))
   if source is None: continue
   fixture=fixture_index.get((source["scenario_id"],source["tool"],source["result_id"]))
   refs.append({"legacy_result_id":source["result_id"],"tool":source["tool"],"authoritative_source_path":source["source_path"],"source_record_sha256":source["source_record_sha256"],"fixture_result_id":fixture["result"]["result_id"] if fixture else None,"new_model_visible_result_content":fixture["result"] if fixture else None,"fixture_source":fixture["provenance"] if fixture else None,"schema_gaps":source["contract_shape"]["errors"] if not fixture else []})
  rebuilt=bool(refs) and all(x["fixture_result_id"] for x in refs)
  if sample["scenario_id"]=="scenario_gs_p0b_037" and not rebuilt:
   blocker="Frozen policy documents establish the refund cap rule but not this Scenario's current cumulative refund amount; the user supplies only original Expense amount. This dynamic financial state cannot be inferred."
  else:
   blocker=None if rebuilt else "No complete authoritative fixture for every source; missing state/DTO cannot be inferred or filled from Expected GT."
  rows.append({"sample_id":sample["sample_id"],"scenario_id":sample["scenario_id"],"split":sample["split"],"expected_fact_claims":sample["fact_claims"],"result_sources":refs,"rebuildable":rebuilt,"blocker":blocker})
 covered=[x for x in rows if x["rebuildable"]]; blocked=[x for x in rows if not x["rebuildable"]]
 rebuildability={"status":"partial_fixtures_blocked_remaining_receipts","method":"Every source for each Expected external fact must have a schema-valid fixture bound by Scenario, Tool and legacy result ID.","summary":{"body_dependent_samples":len(rows),"rebuildable_samples":len(covered),"blocked_samples":len(blocked)},"samples":rows}
 (OUT/"sample_rebuildability.json").write_text(json.dumps(rebuildability,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 (OUT/"sample_blockers.json").write_text(json.dumps({"status":"blocked_remaining_authority","summary":{"body_dependent_samples":len(rows),"rebuildable":len(covered),"not_rebuildable":len(blocked)},"blockers":blocked},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 return {"fixture_count":len(fixtures),"rule_document_fixtures":len(RULE_SELECTORS),"rebuildable_samples":len(covered),"blocked_samples":len(blocked)}

if __name__=="__main__": print(json.dumps(build(),ensure_ascii=False,indent=2))
