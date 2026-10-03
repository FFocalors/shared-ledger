#!/usr/bin/env python3
"""Independent, input-only checks for Training v0.2 Experiment A review packet."""
import hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PKG=ROOT/'docs/ai/dataset/business_state_expansion/v0.2/experiment_a'
sys.path.insert(0,str(ROOT/'scripts/ai_training_setup'))
from export_dataset import export_record

def load(name): return json.loads((PKG/name).read_text(encoding='utf-8'))
def require(ok,msg):
    if not ok: raise AssertionError(msg)
def sample(sid): return next(x for x in SAMPLES if x['sample_id']==sid)
def scenario(sid): return next(x for x in SCENARIOS if x['scenario_id']==sid)
def input_text(s):
    rec,_=export_record(s)
    return rec['system']+'\n'+'\n'.join(m['content'] for m in rec['conversations'] if m['role']!='assistant')

def result(s,tool):
    return next(r['result'] for r in s['input']['server_context']['tool_results'] if r['tool']==tool)

SCENARIOS=load('scenarios.json'); SAMPLES=load('samples.json')
require(len(SCENARIOS)==len(SAMPLES)==16,'packet count !=16')
require(len({s['scenario_id'] for s in SCENARIOS})==16,'duplicate scenario ids')
require(len({s['sample_id'] for s in SAMPLES})==16,'duplicate sample ids')
BY_SC={s['scenario_id']:s for s in SAMPLES}
for sc in SCENARIOS:
    sm=BY_SC[sc['scenario_id']]
    require(sc['ground_truth']['expected_output_type']==sm['expected']['output_type'],sc['scenario_id']+' output mismatch')
    require(sc['ground_truth']['model_output']==sm['expected']['model_output'],sc['scenario_id']+' GT mismatch')

# A: explicit currency is the only requested-value sufficiency change.
a0=sample('sample_v02_a_currency_missing'); a1=sample('sample_v02_a_currency_supplied')
require(a0['expected']['output_type']=='clarification' and a1['expected']['output_type']=='proposal','currency boundary')
require('original_currency' in a0['expected']['model_output']['missing_fields'],'currency clarification missing')
require(a1['expected']['model_output']['operation']['arguments']['original_currency'] in input_text(a1),'supplied currency absent from serialized request')

# B: not-run/zero/multiple/unique are real typed lookup states; only cardinality/execution changes.
bids=['sample_v02_b_lookup_not_run','sample_v02_b_lookup_multiple','sample_v02_b_lookup_zero','sample_v02_b_lookup_unique']
bs=[sample(x) for x in bids]
reqs=[s['input']['user_message'] for s in bs]
require(len(set(reqs))==1,'B requests differ')
for field in ('claimed_participant_id','role_hint'):
    require(len({s['input']['user_context'].get(field) for s in bs})==1,'B user context differs: '+field)
# After excluding the lookup result and its verification token, B serialized Context is identical.
from export_dataset import runtime_context
b_contexts=[]
for s in bs:
    c=runtime_context(s); c['runtime_policy']['tool_results']=[]; c['runtime_policy']['verified_result_ids']=[]; b_contexts.append(c)
require(all(c==b_contexts[0] for c in b_contexts),'B contains unrelated serialized-context differences')
require(not bs[0]['input']['server_context']['tool_results'],'B not-run unexpectedly has result')
for s,expected_count in zip(bs[1:],[2,0,1]):
    r=result(s,'find_participants'); items=r['data']['items']
    require(r['status']=='success' and len(items)==expected_count,'B typed result cardinality')
    require(r['result_id'] in s['input']['server_context']['verified_result_ids'],'B result not verified')
require(bs[1]['expected']['output_type']=='clarification' and len(bs[1]['expected']['model_output']['candidates'])==2,'B multiple must clarify with two candidates')
require(bs[2]['expected']['output_type']=='clarification','B zero must clarify')
unique=result(bs[3],'find_participants')['data']['items'][0]
proposal=bs[3]['expected']['model_output']['operation']['arguments']
require(proposal['payments'][0]['participant_id']==bs[3]['input']['user_context']['claimed_participant_id'],'B payer claim not bound to proposal')
require(unique['id'] in proposal['aa_participant_ids'],'B unique lookup candidate not bound to AA participants')
for s in bs[1:3]:
    require(s['expected']['model_output'].get('type')=='clarification','B nonunique state must not propose')

# C: only the explicit current-user participant binding changes.
c0=sample('sample_v02_c_payer_unbound'); c1=sample('sample_v02_c_payer_bound')
require(c0['input']['user_message']==c1['input']['user_message'],'C request mismatch')
require(c0['input']['user_context']['role_hint']==c1['input']['user_context']['role_hint'],'C role hint changes with binding')
require(c0['input']['user_context']['claimed_participant_id'] is None and c1['input']['user_context']['claimed_participant_id'],'C binding contrast absent')
require(c0['expected']['output_type']=='clarification' and c1['expected']['output_type']=='proposal','C boundary output')

# D: a selected Activity enables only a read tool; exact user date is preserved.
d0=sample('sample_v02_d_activity_ambiguous'); d1=sample('sample_v02_d_activity_selected')
require(d0['input']['user_message']==d1['input']['user_message'],'D request mismatch')
require(d0['input']['ui_context']['activity_id'] is None and len(d0['input']['page_state']['visible_entities'])==2,'D ambiguity not visible')
require(d1['input']['ui_context']['activity_id'] and d1['input']['ui_context']['page_type']=='normal_activity','D selected activity missing')
require(d1['expected']['output_type']=='tool_call','D selected state must read')
require('2026-09-14' in d1['expected']['model_output']['arguments']['query'],'D date lost')

# E: exact same serialized input except recent_actions; success binds exact Expense ID.
e0=sample('sample_v02_e_recent_failed'); e1=sample('sample_v02_e_recent_succeeded')
require(e0['input']['user_message']==e1['input']['user_message'],'E request mismatch')
i0=e0['input'].copy(); i1=e1['input'].copy(); i0.pop('recent_actions'); i1.pop('recent_actions')
require(i0==i1,'E has non-recent-action input differences')
action=e1['input']['recent_actions'][0]
require(action['status']=='succeeded' and action['entity']['id']==e1['expected']['model_output']['arguments']['expense_id'],'E result-to-query entity binding')
require(e0['expected']['output_type']=='clarification' and e1['expected']['output_type']=='tool_call','E boundary output')

# F: answer payer id is read from verified, complete get_expense payload and exact entity.
f=sample('sample_v02_f_verified_expense_answer'); fr=result(f,'get_expense'); fe=fr['data']['expense']; payer=fe['payments'][0]['participant_id']
require(fr['result_id'] in f['input']['server_context']['verified_result_ids'],'F result is not verified')
require(payer in f['expected']['model_output']['content'],'F answer payer absent from visible payload')
require(fe['id']==f['input']['ui_context']['selected_entity']['id'],'F result/entity binding')

# G: selected UI target equals complete verified DTO target; L1 vs D4 is driven by requested field.
g1=sample('sample_v02_g_presentation_l1'); g4=sample('sample_v02_g_financial_d4')
for s in (g1,g4):
    read=result(s,'get_expense'); exp=read['data']['expense']
    require(read['result_id'] in s['input']['server_context']['verified_result_ids'],'G read not verified')
    require(exp['id']==s['input']['ui_context']['selected_entity']['id'],'G UI/DTO entity binding mismatch')
    require(exp['id']==s['expected']['model_output']['operation']['arguments']['expense_id'],'G expected target not read-bound')
require(g1['expected']['model_output']['preview']['diff'][0]['before']==result(g1,'get_expense')['data']['expense']['icon_key'],'G L1 before diff mismatch')
require(g4['expected']['model_output']['preview']['diff'][0]['before']==result(g4,'get_expense')['data']['expense']['original']['amount'],'G D4 before diff mismatch')
require(g4['expected']['model_output']['execution_policy']['execution_allowed'] is False,'G D4 must be non-executable')

# H: typed multiple lookup is complete; no selected target or hidden actor fact; clarify before L2.
h=sample('sample_v02_h_gated_delete_l2'); hr=result(h,'find_expenses'); hi=hr['data']['items']; ho=h['expected']['model_output']
require(len(hi)==2 and len(ho['candidates'])==2 and ho['type']=='clarification','H multiple-result clarification')
require(hr['result_id'] in h['input']['server_context']['verified_result_ids'],'H result not verified')
require(h['input']['ui_context']['selected_entity'] is None and not h['input']['page_state']['visible_entities'],'H has selected target')
require({x['id'] for x in hi}=={x['entity']['id'] for x in ho['candidates']},'H candidates not bound to visible rows')
require('delete_expense' in h['scope']['intent_ids'] and h['scope']['ai_scope']=='SUPPORTED_BUT_GATED','H L2 scope lost')
require('permission_context' not in scenario('scenario_v02_h_gated_delete_l2')['state']['facts'],'H hidden permission fact retained')

# All originally enumerated external facts remain source-backed by the frozen serializer audit.
ga=load('grounding_audit.json')['automated_checks']
require(ga['samples_serialized']==16 and ga['metadata_leaks']==0 and ga['history_roundtrip_pass']==16,'serialization/metadata audit')
require(ga['expected_external_fact_count']==ga['visible_match_count'] and ga['missing_visible_source_count']==0,'external fact source gap')
# Recompute hashes for every frozen source entry and manifest-owned data artifact.
sh=load('source_hashes.json')['artifacts']
for rel,expected in sh.items():
    actual=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    require(actual==expected,'frozen source hash changed: '+rel)
manifest=load('dataset_manifest.json')
for a in manifest['artifacts']:
    actual=hashlib.sha256((PKG/a['path']).read_bytes()).hexdigest()
    require(actual==a['sha256'],'manifest hash mismatch: '+a['path'])
print(json.dumps({'scenarios_checked':16,'contrastive_pairs_checked':11,'binding_chains_checked':['B unique Participant lookup','E recent action → get_expense arguments','F verified DTO → answer','G UI selected → get_expense DTO → expected write target','H verified candidates → clarification'],'external_facts':ga['expected_external_fact_count'],'missing_sources':ga['missing_visible_source_count'],'frozen_sources_hash_checked':len(sh),'manifest_artifacts_hash_checked':len(manifest['artifacts']),'result':'PASS'},ensure_ascii=False,indent=2))
