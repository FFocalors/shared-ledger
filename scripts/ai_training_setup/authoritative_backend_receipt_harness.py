#!/usr/bin/env python3
"""Transaction-isolated local Backend receipt harness for v0.2.

Only catalog-backed read projections are emitted. Scenario state is fixture seed
input; receipt data always comes back from SQL and the catalog-named RPCs.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_backend_receipts"
SCENARIOS = [
    ROOT / "docs/ai/dataset/gold_seed/v0.1/p0a/scenarios.json",
    ROOT / "docs/ai/dataset/gold_seed/v0.1/p0b/scenarios.json",
]
CATALOG = ROOT / "docs/ai/schema/tool_catalog.json"
MIGRATIONS = [
    ROOT / "supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql",
    ROOT / "supabase/migrations/20260920142845_multi_currency_prepayment_final_settlement_core.sql",
    ROOT / "supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql",
]
AI_CONTRACT = ROOT / "docs/ai/AI_MODEL_CONTRACT.md"
NAMESPACE = uuid.UUID("5dcf0b89-84fa-56c5-9f14-a7e2bc4a162e")
PILOTS = [("scenario_gs_p0a_009", "get_expense"), ("scenario_gs_p0a_012", "find_expenses")]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authoritative_source_paths() -> list[Path]:
    paths = {CATALOG, AI_CONTRACT}
    paths.update(SCENARIOS)
    paths.update(p for p in (ROOT / "supabase/migrations").glob("*.sql") if p.is_file())
    v1_root = ROOT / "docs/ai/dataset"
    paths.update(p for p in v1_root.rglob("*") if p.is_file() and "v0.1" in p.parts)
    previous = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_result_fixtures"
    paths.update(p for p in previous.rglob("*") if p.is_file())
    return sorted(paths)


def load_scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in SCENARIOS:
        for row in json.loads(path.read_text(encoding="utf-8")):
            out[row["scenario_id"]] = row
    return out


def mapped_id(scenario_id: str, alias: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{scenario_id}:{alias}"))


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def pilot_sql(scenario: dict[str, Any], tool: str, result_id: str) -> str:
    scenario_id = scenario["scenario_id"]
    facts = scenario["state"]["facts"]
    src = facts["verified_read_result"] if tool == "get_expense" else facts["supporting_lookup_result"]
    expense = src["expense"]
    entity_aliases = {x["id"]: x["alias"] for x in scenario["state"]["entities"]}
    activity = mapped_id(scenario_id, entity_aliases.get(facts["activity_id"], "activity"))
    ledger = mapped_id(scenario_id, entity_aliases.get(facts["ledger_unit_id"], "ledger-unit"))
    user = mapped_id(scenario_id, "harness-actor")
    participants = {x["participant_id"]: mapped_id(scenario_id, entity_aliases.get(x["participant_id"], x["participant_id"])) for x in expense["payments"] + expense["splits"]}
    expense_id = mapped_id(scenario_id, entity_aliases.get(expense["id"], "expense"))
    join_code = f"{int(hashlib.sha256(scenario_id.encode()).hexdigest()[:12], 16) % 100000000:08d}"
    occurred = expense["occurred_at"]
    actor_name = "receipt-harness-local"
    # The test-only seed follows the catalog DTO and exact source record. It is
    # rolled back with the complete SQL transaction after the real read RPC.
    setup = f"""INSERT INTO auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
VALUES ('00000000-0000-0000-0000-000000000000',{sql_quote(user)},'authenticated','authenticated',{sql_quote(actor_name + '@example.invalid')},crypt('x',gen_salt('bf')),now(),'{{}}','{{}}',now(),now());
INSERT INTO public.activities(id,join_code,name,type,base_currency,multi_currency_enabled,created_by{',financial_version' if src.get('financial_version') is not None else ''})
VALUES ({sql_quote(activity)},{sql_quote(join_code)},'Receipt harness fixture','normal',{sql_quote(facts.get('base_currency','CNY'))},true,{sql_quote(user)}{',' + str(int(src['financial_version'])) if src.get('financial_version') is not None else ''});
INSERT INTO public.activity_members(activity_id,user_id) VALUES ({sql_quote(activity)},{sql_quote(user)});
INSERT INTO public.ledger_units(id,activity_id,name,type) VALUES ({sql_quote(ledger)},{sql_quote(activity)},'Default','default');
""" + "\n".join(
        f"INSERT INTO public.participants(id,activity_id,name,participant_order) VALUES ({sql_quote(pid)},{sql_quote(activity)},{sql_quote('fixture-' + str(i + 1))},{i});"
        for i, pid in enumerate(dict.fromkeys(participants.values()))
    ) + f"""
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,note,original_expense_id,created_by,updated_by,version,is_deleted,fx_rate_source,fx_rate_observed_at,icon_key,financial_locked)
VALUES ({sql_quote(expense_id)},{sql_quote(ledger)},{sql_quote(expense['title'])},{sql_quote(expense['original']['amount'])},{sql_quote(expense['original']['currency'])},{sql_quote(expense['fx_snapshot']['rate'])},{sql_quote(expense['base']['amount'])},{sql_quote(expense['split_method'])},{sql_quote(occurred)},{'NULL' if expense['note'] is None else sql_quote(expense['note'])},{'NULL' if expense['original_expense_id'] is None else sql_quote(mapped_id(PILOT_SCENARIO, expense['original_expense_id']))},{sql_quote(user)},{sql_quote(user)},{int(expense['version'])},false,{sql_quote('same_currency' if expense['fx_snapshot']['source'] == 'base_currency' else expense['fx_snapshot']['source'])},{'NULL' if expense['fx_snapshot']['observed_at'] is None else sql_quote(expense['fx_snapshot']['observed_at'])},{sql_quote(expense['icon_key'])},{str(bool(expense['financial_locked'])).lower()});
""" + "\n".join(
        f"INSERT INTO public.{table}(expense_id,participant_id,amount,base_amount) VALUES ({sql_quote(expense_id)},{sql_quote(participants[row['participant_id']])},{sql_quote(row['amount'])},({sql_quote(row['amount'])}::numeric*{sql_quote(expense['fx_snapshot']['rate'])}::numeric));"
        for table, rows in (("payments", expense["payments"]), ("splits", expense["splits"]))
        for row in rows
    )
    expense_json = f"""jsonb_build_object(
      'id',e.id::text,'activity_id',a.id::text,'ledger_unit_id',e.ledger_unit_id::text,'title',e.title,
      'original',jsonb_build_object('amount',e.original_amount::text,'currency',e.original_currency::text),
      'base',jsonb_build_object('amount',e.base_amount::text,'currency',a.base_currency::text),
      'fx_snapshot',jsonb_build_object('rate',e.fx_rate::text,'source',CASE WHEN e.fx_rate_source='same_currency' THEN 'base_currency' ELSE e.fx_rate_source END,'observed_at',e.fx_rate_observed_at),
      'split_method',e.split_method::text,
      'payments',(SELECT coalesce(jsonb_agg(jsonb_build_object('participant_id',p.participant_id::text,'amount',p.amount::text) ORDER BY p.participant_id),'[]'::jsonb) FROM public.payments p WHERE p.expense_id=e.id),
      'splits',(SELECT coalesce(jsonb_agg(jsonb_build_object('participant_id',sp.participant_id::text,'amount',sp.amount::text) ORDER BY sp.participant_id),'[]'::jsonb) FROM public.splits sp WHERE sp.expense_id=e.id),
      'occurred_at',e.occurred_at,'note',e.note,'icon_key',e.icon_key,'original_expense_id',e.original_expense_id::text,
      'financial_locked',e.financial_locked,'version',e.version::text,'is_deleted',e.is_deleted
    )"""
    if tool == "get_expense":
        query = f"""SELECT jsonb_build_object('rpc','public.get_expense_repayment_progress','rows',coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb))
FROM public.get_expense_repayment_progress({sql_quote(activity)},{sql_quote(expense_id)}) r;
SELECT jsonb_build_object(
  'status','success','result_id',{sql_quote(result_id)},
  'observed_at',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
  'financial_version',(SELECT financial_version::text FROM public.activities WHERE id={sql_quote(activity)}),
  'data',jsonb_build_object(
    'expense',(SELECT {expense_json} FROM public.expenses e JOIN public.ledger_units lu ON lu.id=e.ledger_unit_id JOIN public.activities a ON a.id=lu.activity_id WHERE e.id={sql_quote(expense_id)}),
    'repayment_progress',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'expense_id',r.expense_id::text,'debtor_participant_id',r.debtor_participant_id::text,'creditor_participant_id',r.creditor_participant_id::text,
      'currency',r.debt_currency::text,'base_currency',a.base_currency::text,
      'owed_original_amount',r.debt_original_amount::text,'owed_base_amount',r.debt_base_amount::text,
      'reverse_offset_original_amount',r.offset_original_amount::text,'reverse_offset_base_amount',r.offset_base_amount::text,
      'settled_transfer_original_amount',r.settled_original_amount::text,'settled_transfer_base_amount',r.settled_base_amount::text,
      'prepayment_original_amount',r.prepayment_original_amount::text,'prepayment_base_amount',r.prepayment_base_amount::text,
      'remaining_original_amount',r.remaining_original_amount::text,'remaining_base_amount',r.remaining_base_amount::text
    ) ORDER BY r.debtor_participant_id,r.creditor_participant_id),'[]'::jsonb) FROM public.get_expense_repayment_progress({sql_quote(activity)},{sql_quote(expense_id)}) r JOIN public.activities a ON a.id={sql_quote(activity)})
  )
);"""
    else:
        query = f"""SELECT jsonb_build_object('query','public.expenses + ledger_units + activities', 'rows',coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.occurred_at DESC,e.id),'[]'::jsonb))
FROM public.expenses e JOIN public.ledger_units lu ON lu.id=e.ledger_unit_id JOIN public.activities a ON a.id=lu.activity_id WHERE a.id={sql_quote(activity)} AND e.is_deleted=false AND lu.is_deleted=false AND e.title ILIKE '%'||{sql_quote(src['arguments'].get('query',''))}||'%';
SELECT jsonb_build_object(
  'status','success','result_id',{sql_quote(result_id)},
  'observed_at',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
  'financial_version',(SELECT financial_version::text FROM public.activities WHERE id={sql_quote(activity)}),
  'data',jsonb_build_object(
    'items',(SELECT coalesce(jsonb_agg({expense_json} ORDER BY e.occurred_at DESC,e.id),'[]'::jsonb) FROM public.expenses e JOIN public.ledger_units lu ON lu.id=e.ledger_unit_id JOIN public.activities a ON a.id=lu.activity_id WHERE a.id={sql_quote(activity)} AND e.is_deleted=false AND lu.is_deleted=false AND e.title ILIKE '%'||{sql_quote(src['arguments'].get('query',''))}||'%'),
    'next_cursor',null,'truncated',false
  )
);"""
    return f"""\\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout = '30s';
{setup}
SET LOCAL ROLE service_role;
DO $fixture_auth$ BEGIN PERFORM set_config('request.jwt.claims',jsonb_build_object('sub',{sql_quote(user)},'role','service_role')::text,true); END $fixture_auth$;
SELECT private.rebuild_activity_debt_projection({sql_quote(activity)});
{query}
ROLLBACK;
"""


def run_local_sql(sql: str) -> dict[str, Any]:
    # Container identity is checked before any mutating transaction.
    label = subprocess.run(["docker", "inspect", "supabase_db_shared-ledger", "--format", "{{index .Config.Labels \"com.supabase.cli.workdir\"}}"], capture_output=True, text=True, check=True).stdout.strip()
    if Path(label).resolve() != ROOT.resolve():
        raise RuntimeError(f"Local DB container workdir does not match repository: {label}")
    host_port = subprocess.run(["docker", "inspect", "supabase_db_shared-ledger", "--format", "{{(index (index .NetworkSettings.Ports \"5432/tcp\") 0).HostPort}}"], capture_output=True, text=True, check=True).stdout.strip()
    if host_port != "54322":
        raise RuntimeError(f"Expected repository local DB port 54322; got {host_port}")
    proc = subprocess.run(["docker", "exec", "-i", "supabase_db_shared-ledger", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "postgres"], input=sql, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode:
        raise RuntimeError(f"Local transaction failed: {proc.stderr.strip()}")
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    expected = 1 if "$assert_reject$" in sql else 2
    if len(rows) != expected:
        raise RuntimeError(f"Expected {expected} JSON result lines, got {len(rows)}; stdout={proc.stdout!r}")
    return {"receipt": rows[-1], "raw_rpc": rows[0] if expected == 2 else None}


def validate_receipt(tool: str, receipt: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    entry = next(t for t in catalog["tools"] if t["tool_name"] == tool)
    schema = entry["output_schema"]
    validator = Draft202012Validator({"$schema": schema["$schema"], "$defs": catalog["$defs"], "oneOf": schema["oneOf"]}, format_checker=FormatChecker())
    return [e.message for e in validator.iter_errors(receipt)]


def dynamic_refund_probe() -> dict[str, Any]:
    """Exercise the real refund-limit trigger using harness-only events.

    The synthetic events here validate database calculation behavior only and
    are never attributed to a frozen Scenario or used as Sample receipts.
    """
    sid = "__harness_dynamic_refund_probe__"
    actor, activity, ledger, parent, refund_a, refund_b, rejected = [mapped_id(sid, x) for x in ("actor", "activity", "ledger", "parent-expense", "refund-a", "refund-b", "over-limit-refund")]
    join_code = f"{int(hashlib.sha256(sid.encode()).hexdigest()[:12],16)%100000000:08d}"
    sql = f"""\\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout='30s';
INSERT INTO auth.users(instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,created_at,updated_at)
VALUES ('00000000-0000-0000-0000-000000000000',{sql_quote(actor)},'authenticated','authenticated','harness-refund@example.invalid',crypt('x',gen_salt('bf')),now(),'{{}}','{{}}',now(),now());
INSERT INTO public.activities(id,join_code,name,type,base_currency,created_by) VALUES ({sql_quote(activity)},{sql_quote(join_code)},'Harness dynamic refund probe','normal','CNY',{sql_quote(actor)});
INSERT INTO public.ledger_units(id,activity_id,name,type) VALUES ({sql_quote(ledger)},{sql_quote(activity)},'Default','default');
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,created_by,updated_by,fx_rate_source,icon_key)
VALUES ({sql_quote(parent)},{sql_quote(ledger)},'probe original',100,'CNY',1,100,'manual',now(),{sql_quote(actor)},{sql_quote(actor)},'same_currency','money');
INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,original_expense_id,created_by,updated_by,fx_rate_source,icon_key)
VALUES ({sql_quote(refund_a)},{sql_quote(ledger)},'probe refund A',-40,'CNY',1,-40,'manual',now(),{sql_quote(parent)},{sql_quote(actor)},{sql_quote(actor)},'same_currency','money'),
       ({sql_quote(refund_b)},{sql_quote(ledger)},'probe refund B',-60,'CNY',1,-60,'manual',now(),{sql_quote(parent)},{sql_quote(actor)},{sql_quote(actor)},'same_currency','money');
DO $assert_reject$
BEGIN
  BEGIN
    INSERT INTO public.expenses(id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,split_method,occurred_at,original_expense_id,created_by,updated_by,fx_rate_source,icon_key)
    VALUES ({sql_quote(rejected)},{sql_quote(ledger)},'probe over limit',-1,'CNY',1,-1,'manual',now(),{sql_quote(parent)},{sql_quote(actor)},{sql_quote(actor)},'same_currency','money');
    RAISE EXCEPTION 'backend refund limit unexpectedly accepted over-cap event';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $assert_reject$;
SELECT jsonb_build_object('aggregate_original_refund_amount',coalesce(sum(abs(r.original_amount)),0)::text,'refund_events',count(*),'over_limit_insert_rejected',true,'computed_by','public expense refund-limit trigger predicate from migration 20260923032928')
FROM public.expenses r WHERE r.original_expense_id={sql_quote(parent)} AND NOT r.is_deleted;
ROLLBACK;
"""
    (OUT / "dynamic_refund_db_probe.sql").write_text(sql, encoding="utf-8")
    result = run_local_sql(sql)["receipt"]
    rollback_count = subprocess.run(["docker","exec","supabase_db_shared-ledger","psql","-X","-qAt","-U","postgres","-d","postgres","-c",f"select count(*) from public.activities where id='{activity}';"],capture_output=True,text=True,check=True).stdout.strip()
    return {"scenario_coverage": False, "harness_only": True, "dynamic_result": result, "setup_sql_path":"docs/ai/dataset/experiments/v0.2/authoritative_backend_receipts/dynamic_refund_db_probe.sql", "setup_sql_sha256":sha(OUT / "dynamic_refund_db_probe.sql"), "rollback_verified": rollback_count == "0", "rollback_row_count_after_run": int(rollback_count), "note": "SYNTHETIC_TEST_ONLY. This validates live database aggregation and cap enforcement using a controlled synthetic event ledger; the six target Samples remain blocked because their original refund event IDs/amounts are absent from frozen Scenario facts.", "source_sha256": sha(MIGRATIONS[2])}


def build() -> dict[str, Any]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = load_scenarios()
    fixtures = []
    errors = []
    for scenario_id, tool in PILOTS:
        scenario = scenarios[scenario_id]
        rid = str(uuid.uuid5(NAMESPACE, f"result:{scenario_id}:{tool}"))
        sql = pilot_sql(scenario, tool, rid)
        (OUT / f"{scenario_id}__{tool}.sql").write_text(sql, encoding="utf-8")
        run = run_local_sql(sql)
        receipt = run["receipt"]
        schema_errors = validate_receipt(tool, receipt, catalog)
        errors.extend(f"{scenario_id}/{tool}: {e}" for e in schema_errors)
        sql_rel = f"docs/ai/dataset/experiments/v0.2/authoritative_backend_receipts/{scenario_id}__{tool}.sql"
        sql_hash = hashlib.sha256((OUT / f"{scenario_id}__{tool}.sql").read_bytes()).hexdigest()
        rollback_rows = subprocess.run(["docker", "exec", "supabase_db_shared-ledger", "psql", "-X", "-qAt", "-U", "postgres", "-d", "postgres", "-c", f"select count(*) from public.activities where id='{mapped_id(scenario_id, next(e['alias'] for e in scenario['state']['entities'] if e['id']==scenario['state']['facts']['activity_id']))}';"], capture_output=True, text=True, check=True).stdout.strip()
        fact_record = scenario["state"]["facts"].get("verified_read_result") or scenario["state"]["facts"].get("supporting_lookup_result")
        entity_aliases = {x["id"]: x["alias"] for x in scenario["state"]["entities"]}
        fixtures.append({"scenario_id": scenario_id, "tool": tool, "legacy_result_id": fact_record["result_id"], "result": receipt, "raw_backend_result": run["raw_rpc"], "schema_errors": schema_errors, "source_record_sha256": hashlib.sha256(json.dumps(fact_record, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), "setup_sql_path": sql_rel, "setup_sql_sha256": sql_hash, "mapping": {e["alias"]: mapped_id(scenario_id, e["alias"]) for e in scenario["state"]["entities"]} | {"harness_actor": mapped_id(scenario_id,"harness-actor")}, "rpc": "public.get_expense_repayment_progress(uuid,uuid)" if tool == "get_expense" else None, "adapter": "catalog_query_composition_sql", "rollback_verified": rollback_rows == "0", "rollback_row_count_after_run": int(rollback_rows)})
    sources = authoritative_source_paths()
    result = {"status": "pilot_complete" if not errors else "pilot_blocked_schema_mismatch", "fixtures": fixtures, "schema_errors": errors, "source_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in sources}, "reproducible": {"command": "python scripts/ai_training_setup/authoritative_backend_receipt_harness.py", "database": "repository-owned local container only; host mapping 127.0.0.1:54322; no linked connection", "transaction": "one SQL transaction per scenario, explicit ROLLBACK"}}
    (OUT / "pilot_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dynamic_probe = dynamic_refund_probe()
    result["dynamic_refund_engine_probe"] = dynamic_probe
    (OUT / "pilot_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    blockers = json.loads((ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_result_fixtures/sample_blockers.json").read_text(encoding="utf-8"))["blockers"]
    covered_pairs = {(f["scenario_id"],f["tool"]) for f in fixtures}
    covered_samples = [x for x in blockers if all((x["scenario_id"], r["tool"]) in covered_pairs for r in x["result_sources"])]
    fixture_doc = {"schema_version":"v0.2-authoritative-backend-receipts-1","fixtures":fixtures}
    (OUT / "backend_result_fixtures.json").write_text(json.dumps(fixture_doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    old_registry = json.loads((ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_result_fixtures/fixture_registry.json").read_text(encoding="utf-8"))
    id_registry = {"policy":"A result ID binds to one exact Scenario + Tool pair. Legacy aliases with multiple bindings are rejected unless resolved by exact pair.","bindings":[{"scenario_id":f["scenario_id"],"tool":f["tool"],"legacy_result_id":f["legacy_result_id"],"result_id":f["result"]["result_id"]} for f in fixtures],"reserved_alias_bindings":old_registry.get("reserved_alias_bindings",[]),"legacy_conflicts":old_registry.get("legacy_id_conflicts",[]),"cross_scope_reuse_allowed":False}
    (OUT / "result_id_registry.json").write_text(json.dumps(id_registry,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tool_sources = []
    for tool_name in sorted({x["tool"] for x in fixtures}):
        tool = next(x for x in catalog["tools"] if x["tool_name"] == tool_name)
        tool_sources.append({"tool":tool_name,"backend_mapping":tool["backend_mapping"],"receipt_schema_sha256":hashlib.sha256(json.dumps(tool["output_schema"],sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
    source_inventory = {"sources":[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p)} for p in sources],"source_scope":{"frozen_v0_1":"all regular files beneath docs/ai/dataset path segments containing v0.1","prior_authoritative_result_fixture_package":"all regular files in v0.2/authoritative_result_fixtures","backend":"all supabase/migrations/*.sql","contract_and_schema":["docs/ai/AI_MODEL_CONTRACT.md","docs/ai/schema/tool_catalog.json"]},"tool_mappings":tool_sources,"rpc_pointers":{"public.get_expense_repayment_progress":"supabase/migrations/20260921051720_targeted_expense_repayment_contract.sql#public.get_expense_repayment_progress(uuid,uuid)","refund_limit_trigger":"supabase/migrations/20260923032928_refund_limits_and_legacy_rpc_permissions.sql#active_refund_total"},"db_identity":{"container":"supabase_db_shared-ledger","compose_workdir":str(ROOT),"host":"127.0.0.1","port":54322,"database":"postgres","server_version":"17.6"}}
    (OUT / "authoritative_sources.json").write_text(json.dumps(source_inventory,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    coverage = []
    reason_by_scenario = {
      "scenario_gs_p0b_004":"Recorded Expense seed omits catalog-required ledger_unit_id, base, fx_snapshot, split_method, occurred_at, note, icon_key and original_expense_id; cannot synthesize those historical facts.",
      "scenario_gs_p0a_015":"Balance result omits base_reference; prepayment result has a non-contract account currency field and lacks an event-backed balance state. No underlying expense/debt/prepayment event ledger is recorded.",
      "scenario_gs_p0b_010":"Only one bilateral amount/currency row is recorded; full bilateral debt DTO and expense_progress history are absent.",
      "scenario_gs_p0a_011":"Transfer source contains only transfer_id and is_voided; required payment, participants, time, recorder and component/allocation details are absent.",
      "scenario_gs_p0b_012":"Original Expense source omits catalog-required ledger, base, FX snapshot, split method, time, note and icon; full repayment progress is also absent.",
      "scenario_gs_p0b_016":"Expense search candidates contain only IDs/title/locked/refund IDs; amount, base/FX, payments and splits for complete Expense DTO are absent.",
      "scenario_gs_p0b_017":"Expense source has only ID/title/original/payments/splits; remaining required Expense DTO fields are absent.",
      "scenario_gs_p0b_018":"Expense source has only ID/activity/title/original/payments/splits/lock/version/deleted; required DTO fields are absent.",
      "scenario_gs_p0b_019":"Search candidate source has only ID/title/locked/deleted; complete Expense DTO fields are absent.",
      "scenario_gs_p0b_020":"Expense source has only ID/activity/title/original/payments/splits/lock/version/deleted; required DTO fields are absent.",
      "scenario_gs_p0b_022":"Search result contains candidate IDs/query/resolution only; complete Expense DTOs and pagination result are absent.",
      "scenario_gs_p0b_025":"Participant lookup contains candidate IDs/resolution only; full Participant DTOs and query-result ordering fields are absent.",
      "scenario_gs_p0b_037":"The six dynamic samples include no original expense identity or prior refund event ledger. The database can compute totals, but target source events cannot be reconstructed without inventing refund history."
    }
    for row in blockers:
        pair_ok = all((row["scenario_id"],r["tool"]) in covered_pairs for r in row["result_sources"])
        coverage.append({"sample_id":row["sample_id"],"scenario_id":row["scenario_id"],"tools":[r["tool"] for r in row["result_sources"]],"reconstructable":pair_ok,"result_ids":[next((f["result"]["result_id"] for f in fixtures if f["scenario_id"]==row["scenario_id"] and f["tool"]==r["tool"]),None) for r in row["result_sources"]],"blocker":None if pair_ok else reason_by_scenario.get(row["scenario_id"],"No complete authority-backed seed for every required DB field.")})
    setup_requirements = {
      "get_expense":"Activity + ledger unit + complete Expense row + payments/splits + FX snapshot + actor references; call get_expense_repayment_progress using verified Activity/Expense scope.",
      "find_expenses":"Activity + ledger unit + all matching Expense rows with full nested DTO source fields; run catalog filters, ordering and pagination against DB.",
      "get_participant_balance":"Activity + participant + source expense/payment/split/debt/transfer/prepayment events sufficient to recalculate participant_financial_status.",
      "get_prepayment_accounts":"Activity + owner/custodian participants + source prepayment/return/usage transfers sufficient for real account balance and usage projections.",
      "get_debt":"Activity + debtor/creditor participants + exact bilateral debt facts + expense debt and repayment events sufficient for progress RPC rows.",
      "get_transfer":"Activity + participants + transfer + payment/components/disputes/source allocation rows.",
      "find_participants":"Activity + participant rows and claims needed for exact matching and ordered result DTOs.",
      "lookup_business_rule":"Frozen rule passage can be looked up directly; any claim about current cumulative refund additionally needs original Expense identity and all active linked refund event rows."
    }
    scenario_plan = []
    reason_scenarios = sorted({x["scenario_id"] for x in blockers})
    source_scenarios = load_scenarios()
    for sid in reason_scenarios:
        rows = [x for x in blockers if x["scenario_id"] == sid]
        tools = sorted({r["tool"] for x in rows for r in x["result_sources"]})
        fact = source_scenarios[sid]["state"]["facts"]
        scenario_plan.append({"scenario_id":sid,"tools":tools,"recorded_seed_paths":sorted({r["authoritative_source_path"] for x in rows for r in x["result_sources"]}),"minimum_database_preconditions":[setup_requirements[t] for t in tools],"seed_source_sha256":hashlib.sha256(json.dumps(fact,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),"disposition":"executed_and_reconstructed" if all((sid,t) in covered_pairs for t in tools) else "blocked_missing_authoritative_seed_fields_or_events","blocker":next((x["blocker"] for x in coverage if x["scenario_id"]==sid and x["blocker"]),None)})
    batch = {"status":"partial","target_blocked_samples":len(blockers),"reconstructable_samples":len(covered_samples),"blocked_samples":len(blockers)-len(covered_samples),"scenario_count":len(set(x["scenario_id"] for x in blockers)),"executed_fixture_count":len(fixtures),"sample_coverage":coverage,"scenario_setup_plans":scenario_plan,"dynamic_refund_probe":dynamic_probe}
    (OUT / "batch_coverage.json").write_text(json.dumps(batch,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"status": result["status"], "fixture_count": len(fixtures), "schema_errors": errors, "fixture_keys": [(f["scenario_id"],f["tool"],f["result"]["result_id"]) for f in fixtures], "reconstructable_samples": len(covered_samples), "blocked_samples": len(blockers)-len(covered_samples), "dynamic_probe":dynamic_probe["dynamic_result"]}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
