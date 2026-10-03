#!/usr/bin/env python3
"""Deterministic generation and structured business-contract evaluation for local checkpoints."""
from __future__ import annotations
import argparse, json, math, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

ROOT=Path(__file__).resolve().parents[2]
SETUP=ROOT/'docs/ai/training_setup/v0.1'
CANONICAL=ROOT/'docs/ai/dataset/canonical_training/v0.1'
SCHEMA_PATH=ROOT/'docs/ai/schema/model_output.schema.json'
CATALOG_PATH=ROOT/'docs/ai/schema/tool_catalog.json'
INTENT_PATH=ROOT/'docs/ai/schema/intent_catalog.json'
NUMBER_RE=re.compile(r'^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$')
SUPPORTED_SCHEMA_KEYWORDS={
 '$ref','$schema','$id','$defs','title','description','examples','default','deprecated',
 'type','const','enum','properties','required','additionalProperties','items','anyOf','oneOf','allOf','not','if','then','else',
 'minLength','maxLength','pattern','minItems','maxItems','uniqueItems','format','minimum','maximum',
 'minProperties','maxProperties','multipleOf','exclusiveMinimum','exclusiveMaximum','$comment','readOnly','writeOnly',
 'x-ai-contract-version'
}


def load_json(path:Path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path:Path):
 import hashlib
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()

def resolve_ref(ref:str, base_uri:str, root_schema:dict, tool_catalog:dict):
 uri,_,fragment=ref.partition('#')
 resolved=urljoin(base_uri,uri) if uri else base_uri
 node=tool_catalog if resolved.rstrip('/').endswith('/tool_catalog.json') else root_schema
 if fragment:
  for part in fragment.lstrip('/').split('/'):
   part=part.replace('~1','/').replace('~0','~')
   node=node[int(part)] if isinstance(node,list) else node[part]
 return node

def _type_ok(value, kind):
 if kind=='object': return isinstance(value,dict)
 if kind=='array': return isinstance(value,list)
 if kind=='string': return isinstance(value,str)
 if kind=='boolean': return isinstance(value,bool)
 if kind=='null': return value is None
 if kind=='integer': return isinstance(value,int) and not isinstance(value,bool)
 if kind=='number': return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(float(value))
 return True

def validate_schema(instance:Any, schema:dict, root_schema:dict, tool_catalog:dict, base_uri:str|None=None, path:str='$') -> list[str]:
 base_uri=base_uri or root_schema.get('$id','')
 errors=[]
 unsupported=set(schema)-SUPPORTED_SCHEMA_KEYWORDS
 if unsupported: errors.append(f'{path}: unsupported schema keywords {sorted(unsupported)}')
 if '$ref' in schema:
  try: return validate_schema(instance,resolve_ref(schema['$ref'],base_uri,root_schema,tool_catalog),root_schema,tool_catalog,base_uri,path)
  except Exception as e: return [f'{path}: unresolved schema ref {schema["$ref"]}: {type(e).__name__}']
 if 'allOf' in schema:
  for sub in schema['allOf']: errors.extend(validate_schema(instance,sub,root_schema,tool_catalog,base_uri,path))
 if 'anyOf' in schema:
  options=[validate_schema(instance,sub,root_schema,tool_catalog,base_uri,path) for sub in schema['anyOf']]
  if all(options): errors.append(f'{path}: no anyOf schema matched')
 if 'oneOf' in schema:
  options=[validate_schema(instance,sub,root_schema,tool_catalog,base_uri,path) for sub in schema['oneOf']]
  if sum(not e for e in options)!=1: errors.append(f'{path}: expected exactly one oneOf schema match (found {sum(not e for e in options)})')
 if 'not' in schema and not validate_schema(instance,schema['not'],root_schema,tool_catalog,base_uri,path): errors.append(f'{path}: violates not schema')
 if 'if' in schema:
  condition_matches=not validate_schema(instance,schema['if'],root_schema,tool_catalog,base_uri,path)
  branch='then' if condition_matches else 'else'
  if branch in schema: errors.extend(validate_schema(instance,schema[branch],root_schema,tool_catalog,base_uri,path))
 if 'const' in schema and instance!=schema['const']: errors.append(f'{path}: expected const {schema["const"]!r}')
 if 'enum' in schema and instance not in schema['enum']: errors.append(f'{path}: value outside enum')
 kind=schema.get('type')
 if kind:
  kinds=kind if isinstance(kind,list) else [kind]
  if not any(_type_ok(instance,k) for k in kinds): return errors+[f'{path}: expected type {kind}']
 if isinstance(instance,str):
  if len(instance)<schema.get('minLength',0): errors.append(f'{path}: below minLength')
  if len(instance)>schema.get('maxLength',10**12): errors.append(f'{path}: exceeds maxLength')
  if 'pattern' in schema and not re.search(schema['pattern'],instance): errors.append(f'{path}: pattern mismatch')
  if schema.get('format')=='uuid':
   if not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}',instance): errors.append(f'{path}: invalid uuid')
  if schema.get('format')=='date-time':
   try: datetime.fromisoformat(instance.replace('Z','+00:00'))
   except ValueError: errors.append(f'{path}: invalid date-time')
 if isinstance(instance,(int,float)) and not isinstance(instance,bool):
  if instance<schema.get('minimum',-float('inf')): errors.append(f'{path}: below minimum')
  if instance>schema.get('maximum',float('inf')): errors.append(f'{path}: above maximum')
  if instance<=schema.get('exclusiveMinimum',-float('inf')): errors.append(f'{path}: not above exclusiveMinimum')
  if instance>=schema.get('exclusiveMaximum',float('inf')): errors.append(f'{path}: not below exclusiveMaximum')
  if schema.get('multipleOf') and instance % schema['multipleOf'] != 0: errors.append(f'{path}: multipleOf mismatch')
 if isinstance(instance,list):
  if len(instance)<schema.get('minItems',0): errors.append(f'{path}: below minItems')
  if len(instance)>schema.get('maxItems',10**12): errors.append(f'{path}: exceeds maxItems')
  if schema.get('uniqueItems'):
   keys=[json.dumps(v,sort_keys=True,ensure_ascii=False) for v in instance]
   if len(set(keys))!=len(keys): errors.append(f'{path}: duplicate items')
  if 'items' in schema:
   for i,value in enumerate(instance): errors.extend(validate_schema(value,schema['items'],root_schema,tool_catalog,base_uri,f'{path}[{i}]'))
 if isinstance(instance,dict):
  if len(instance)<schema.get('minProperties',0): errors.append(f'{path}: below minProperties')
  if len(instance)>schema.get('maxProperties',10**12): errors.append(f'{path}: exceeds maxProperties')
  for key in schema.get('required',[]):
   if key not in instance: errors.append(f'{path}.{key}: required property missing')
  props=schema.get('properties',{})
  for key,value in instance.items():
   if key in props: errors.extend(validate_schema(value,props[key],root_schema,tool_catalog,base_uri,f'{path}.{key}'))
   elif schema.get('additionalProperties') is False: errors.append(f'{path}.{key}: additional property forbidden')
   elif isinstance(schema.get('additionalProperties'),dict): errors.extend(validate_schema(value,schema['additionalProperties'],root_schema,tool_catalog,base_uri,f'{path}.{key}'))
 return errors

def json_parse(raw:str):
 duplicate_keys=[]
 def object_pairs(pairs):
  result={}
  for key,value in pairs:
   if key in result: duplicate_keys.append(key)
   result[key]=value
  return result
 decoder=json.JSONDecoder(object_pairs_hook=object_pairs)
 try: return decoder.decode(raw),True,True,None,sorted(set(duplicate_keys))
 except Exception: pass
 duplicate_keys.clear()
 for i,ch in enumerate(raw):
  if ch=='{':
   try:
    duplicate_keys.clear()
    val,end=decoder.raw_decode(raw[i:])
    return val,False,True,{'start':i,'end':i+end},sorted(set(duplicate_keys))
   except Exception: continue
 return None,False,False,None,[]

def normalize(value:Any):
 if isinstance(value,dict): return {k:normalize(v) for k,v in sorted(value.items())}
 if isinstance(value,list): return [normalize(v) for v in value]
 if isinstance(value,str):
  st=value.strip()
  if NUMBER_RE.fullmatch(st):
   try: return {'$decimal':format(Decimal(st).normalize(),'f')}
   except InvalidOperation: pass
  return st
 if isinstance(value,float) and math.isfinite(value): return {'$decimal':format(Decimal(str(value)).normalize(),'f')}
 return value

def projection(out:Any):
 if not isinstance(out,dict): return None
 t=out.get('type')
 if t=='proposal':
  prev=out.get('preview') if isinstance(out.get('preview'),dict) else {}
  return normalize({'type':t,'intent_id':out.get('intent_id'),'operation':out.get('operation'),
   'preview_kind':prev.get('kind'),'diff':prev.get('diff'),'confirmation':out.get('confirmation'),
   'execution_policy':out.get('execution_policy')})
 if t=='tool_call': return normalize({k:out.get(k) for k in ('type','intent_id','tool','arguments')})
 if t=='clarification': return normalize({k:out.get(k) for k in ('type','intent_id','reason','missing_fields','candidates')})
 if t=='answer': return normalize({'type':t,'evidence_result_ids':out.get('evidence_result_ids')})
 if t=='error': return normalize({'type':t,'code':out.get('code'),'evidence_result_ids':out.get('evidence_result_ids')})
 if t=='unsupported': return normalize({'type':t})
 return normalize(out)

def leaf_paths(value:Any,prefix=''):
 if isinstance(value,dict):
  for k,v in value.items(): yield from leaf_paths(v,f'{prefix}.{k}' if prefix else k)
 elif isinstance(value,list):
  for i,v in enumerate(value): yield from leaf_paths(v,f'{prefix}[{i}]')
 else: yield prefix,value

def key_fact(path:str):
 parts=re.split(r'[.\[\]]+',path.lower())
 return any(
  part in {'type','intent_id','tool','reason','code','level','required','execution_allowed','split_method','occurred_at','expected_financial_version'}
  or part.endswith(('_id','_ids'))
  or 'amount' in part
  or 'currency' in part
  or 'payment' in part
  or 'split' in part
  or part=='evidence_result_ids'
  for part in parts if part
 )

def natural_language_leaf(path:str):
 return path.rsplit('.',1)[-1].split('[',1)[0] in {'content','summary','question','suggested_action','message'}

def get_path(obj:Any,path:str):
 cur=obj
 for token in re.findall(r'[^.\[\]]+|(?<=\[)\d+(?=\])',path):
  try: cur=cur[int(token)] if isinstance(cur,list) else cur[token]
  except (KeyError,IndexError,TypeError,ValueError): return object()
 return cur

def evaluate_one(actual:Any, expected:dict, model_schema:dict, tool_catalog:dict, intent_catalog:dict, duplicate_json_keys:list[str]|None=None):
 actual_type=actual.get('type') if isinstance(actual,dict) else None
 exp=expected.get('model_output',{})
 expected_type=expected.get('output_type') or exp.get('type')
 schema_errs=validate_schema(actual,model_schema,model_schema,tool_catalog) if isinstance(actual,(dict,list,str,int,float,bool)) or actual is None else ['$: unsupported JSON value']
 type_ok=actual_type==expected_type
 exproj=projection(exp); acproj=projection(actual)
 exact=actual==exp
 normalized_json=normalize(actual)==normalize(exp)
 structural=acproj==exproj if acproj is not None else False
 expected_leaf=dict(leaf_paths(exp)); natural_suffixes=('.content','.summary','.question','.reason','.suggested_action')
 field_expected={p:v for p,v in expected_leaf.items() if not natural_language_leaf(p)}
 field_correct=sum(normalize(get_path(actual,p))==normalize(v) for p,v in field_expected.items())
 field_total=len(field_expected)
 key_expected={p:v for p,v in field_expected.items() if key_fact(p)}
 key_correct=sum(normalize(get_path(actual,p))==normalize(v) for p,v in key_expected.items())
 key_total=len(key_expected)
 intents={x['intent_id']:x for x in intent_catalog.get('intents',[])}
 tools={x['tool_name']:x for x in tool_catalog.get('tools',[])}
 safety=[]
 duplicate_json_keys=duplicate_json_keys or []
 if duplicate_json_keys: safety.append('duplicate_json_object_key')
 if schema_errs: safety.append('model_output_schema_invalid')
 if isinstance(actual,dict) and actual_type=='proposal':
  conf=actual.get('confirmation'); conf=conf if isinstance(conf,dict) else {}
  policy=actual.get('execution_policy'); policy=policy if isinstance(policy,dict) else {}
  if conf.get('required') is not True: safety.append('proposal_missing_required_confirmation')
  gt_policy=exp.get('execution_policy',{})
  if gt_policy.get('execution_allowed') is False and policy.get('execution_allowed') is not False: safety.append('execution_allowed_despite_ground_truth_block')
  if policy.get('execution_allowed') is True and conf.get('required') is not True: safety.append('execution_allowed_without_confirmation_gate')
  operation=actual.get('operation'); operation=operation if isinstance(operation,dict) else {}
  if not isinstance(actual.get('operation'),dict): safety.append('proposal_operation_malformed')
  if exp.get('intent_id')=='update_expense' and policy.get('execution_allowed') is not False: safety.append('d4_expense_edit_execution_not_blocked')
  if exp.get('intent_id')=='update_refund' and policy.get('execution_allowed') is not False: safety.append('d4_refund_edit_execution_not_blocked')
 if isinstance(actual,dict) and actual_type=='tool_call':
  it=intents.get(actual.get('intent_id')); tl=tools.get(actual.get('tool'))
  allowed=set((it or {}).get('possible_tools',[]))|set((it or {}).get('supporting_lookup_tools',[]))
  if not it or not it.get('first_release_tool_call_allowed'): safety.append('intent_tool_call_not_enabled')
  if actual.get('tool') not in allowed: safety.append('tool_not_mapped_to_intent')
  if not tl or not tl.get('enabled_after_decision'): safety.append('tool_not_enabled_after_decision')
  if tl and tl.get('mode')=='write' and expected_type!='tool_call': safety.append('write_tool_call_instead_of_ground_truth_response')
  if tl and tl.get('mode')=='write' and not tl.get('first_release_execution_allowed'): safety.append('write_tool_not_allowed_in_first_release')
 actual_operation=actual.get('operation') if isinstance(actual,dict) else None
 actual_operation=actual_operation if isinstance(actual_operation,dict) else {}
 return {
  'schema_valid':not schema_errs,'schema_errors':schema_errs[:12],
  'expected_type':expected_type,'actual_type':actual_type,'type_correct':type_ok,
  'intent_correct':isinstance(actual,dict) and actual.get('intent_id')==exp.get('intent_id') if exp.get('intent_id') is not None else None,
  'tool_correct':(actual.get('tool')==exp.get('tool') if exp.get('type')=='tool_call' and isinstance(actual,dict) else
                   actual_operation.get('tool')==exp.get('operation',{}).get('tool') if exp.get('type')=='proposal' and isinstance(actual,dict) else None),
  'exact_model_output_match':exact,'normalized_json_structural_match':normalized_json,'normalized_business_structure_match':structural,
  'field_facts_correct':field_correct,'field_facts_total':field_total,
  'field_fact_accuracy':(field_correct/field_total if field_total else None),
  'key_facts_correct':key_correct,'key_facts_total':key_total,
  'key_fact_accuracy':(key_correct/key_total if key_total else None),
  'natural_language_fields':{key:{'present':bool(isinstance(actual,dict) and isinstance(actual.get(key),str) and actual.get(key).strip()),'exact_match':actual.get(key)==exp.get(key) if isinstance(actual,dict) else False} for key in ('content','summary','question','reason','suggested_action') if key in exp},
  'duplicate_json_keys':duplicate_json_keys,
  'contract_safety_violations':safety,'contract_safe':not safety,
 }

def summarize(records:list[dict]):
 def rate(pred):
  n=sum(1 for r in records if pred(r)); return {'count':n,'total':len(records),'rate':n/len(records) if records else 0.0}
 groups={}
 for key in ('split','output_type','difficulty'):
  vals=sorted({str(r.get(key)) for r in records})
  groups[key]={}
  for value in vals:
   rr=[r for r in records if str(r.get(key))==value]
   groups[key][value]={'count':len(rr),'schema_valid':sum(r['evaluation']['schema_valid'] for r in rr),
    'type_correct':sum(r['evaluation']['type_correct'] for r in rr),
    'exact_model_output_match':sum(r['evaluation']['exact_model_output_match'] for r in rr),
    'normalized_json_structural_match':sum(r['evaluation']['normalized_json_structural_match'] for r in rr),
    'normalized_business_structure_match':sum(r['evaluation']['normalized_business_structure_match'] for r in rr),
    'contract_unsafe':sum(not r['evaluation']['contract_safe'] for r in rr),
    'extractable_json':sum(r['extractable_json_parse_ok'] for r in rr)}
 confusion=defaultdict(Counter)
 for r in records: confusion[str(r['output_type'])][str(r['evaluation']['actual_type'])]+=1
 fieldc=sum(r['evaluation']['field_facts_correct'] for r in records); fieldn=sum(r['evaluation']['field_facts_total'] for r in records)
 keyc=sum(r['evaluation']['key_facts_correct'] for r in records); keyn=sum(r['evaluation']['key_facts_total'] for r in records)
 safety_counts=Counter(v for r in records for v in r['evaluation']['contract_safety_violations'])
 return {'records':len(records),'raw_json_rate':rate(lambda r:r['raw_json_parse_ok']),
  'extractable_json_rate':rate(lambda r:r['extractable_json_parse_ok']),
  'exact_model_output_rate':rate(lambda r:r['evaluation']['exact_model_output_match']),
  'normalized_json_structural_rate':rate(lambda r:r['evaluation']['normalized_json_structural_match']),
  'schema_valid_rate':rate(lambda r:r['evaluation']['schema_valid']),
  'type_accuracy':rate(lambda r:r['evaluation']['type_correct']),
  'normalized_business_structure_accuracy':rate(lambda r:r['evaluation']['normalized_business_structure_match']),
  'field_fact_accuracy':{'correct':fieldc,'total':fieldn,'rate':fieldc/fieldn if fieldn else None},
  'contract_safe_rate':rate(lambda r:r['evaluation']['contract_safe']),
  'duplicate_json_key_records':sum(bool(r['evaluation'].get('duplicate_json_keys')) for r in records),
  'safety_violation_counts':dict(sorted(safety_counts.items())),
  'key_fact_accuracy':{'correct':keyc,'total':keyn,'rate':keyc/keyn if keyn else None},
  'grouped':groups,'type_confusion':{k:dict(v) for k,v in confusion.items()},
  'automated_metric_limitations':'Answer/summary/question/reason wording is not judged as semantically equivalent by string similarity. Clarification compares reason, missing_fields and candidates but not literal question text. Proposal compares tool arguments, kind, complete diff, confirmation and execution policy, but not summary wording. Results identify candidates for review and are not human business approval.'}

def run_eval(args):
 run_dir=Path(args.run_dir); run_dir.mkdir(parents=True,exist_ok=True)
 canonical=load_json(CANONICAL/'samples.json'); by_id={s['sample_id']:s for s in canonical}
 if args.summary_only:
  output_path=Path(args.output_jsonl)
  schema=load_json(SCHEMA_PATH); catalog=load_json(CATALOG_PATH); intents=load_json(INTENT_PATH)
  records=[json.loads(line) for line in output_path.read_text(encoding='utf-8').splitlines() if line.strip()]
  for record in records:
   actual,strict_ok,extract_ok,extract_span,duplicate_keys=json_parse(record.get('raw_output',''))
   record['raw_json_parse_ok']=strict_ok; record['extractable_json_parse_ok']=extract_ok; record['json_extract_span']=extract_span
   record['parsed_output']=actual
   expected={'output_type':record['output_type'],'model_output':record['expected_output']}
   record['evaluation']=evaluate_one(actual if extract_ok else None,expected,schema,catalog,intents,duplicate_keys)
  output_path.write_text(''.join(json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n' for x in records),encoding='utf-8')
  summary=summarize(records)
  report_path=Path(args.report_json)
  report=load_json(report_path) if report_path.exists() else {'run_name':args.run_name}
  report.update({'summary_recomputed_at':datetime.now().astimezone().isoformat(),'summary':summary,'records_file':str(output_path),
   'evaluation_version':'structured-contract-evaluator-v0.1.1'})
  report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({'completed_records':len(records),'summary_only':True,'summary':summary},ensure_ascii=False),flush=True)
  return
 sys.path.insert(0,str(Path(r'D:\AI\LlamaFactory\src')))
 from llamafactory.chat import ChatModel
 trace=load_json(SETUP/'traceability.json'); trace_by_id={x['sample_id']:x for x in trace}
 setup_manifest=load_json(SETUP/'manifest.json')
 data_by_split={}
 for split in args.splits.split(','):
  data=load_json(SETUP/'llamafactory'/f'{split}.json')
  data_by_split[split]=data
 model_args={'model_name_or_path':args.model_path,'trust_remote_code':True,'quantization_bit':4,'quantization_method':'bnb','quantization_type':'nf4','double_quantization':True,
  'stage':'sft','finetuning_type':'lora','infer_backend':'huggingface','template':'qwen3_5_nothink','enable_thinking':False,
  'do_sample':False,'temperature':0.0,'max_new_tokens':args.max_new_tokens}
 if args.adapter_path: model_args['adapter_name_or_path']=args.adapter_path
 model=ChatModel(model_args)
 output_path=Path(args.output_jsonl); output_path.parent.mkdir(parents=True,exist_ok=True)
 done=set()
 if args.resume and output_path.exists():
  for line in output_path.read_text(encoding='utf-8').splitlines():
   try: done.add(json.loads(line)['sample_id'])
   except Exception: pass
 schema=load_json(SCHEMA_PATH); catalog=load_json(CATALOG_PATH); intents=load_json(INTENT_PATH)
 num=0; started=time.perf_counter()
 with output_path.open('a' if args.resume else 'w',encoding='utf-8') as out:
   for split,rows in data_by_split.items():
    # Dataset registration preserves export order; use the matching per-split trace sequence.
    trace_rows=[t for t in trace if t['split']==split]
    if len(trace_rows)!=len(rows): raise ValueError(f'{split}: trace/data count mismatch')
    for i,(row,tr) in enumerate(zip(rows,trace_rows),1):
     sid=tr['sample_id']
     if sid in done: continue
     sample=by_id[sid]
     if sample['split']!=split: raise ValueError(f'{sid}: split trace mismatch')
     conversations=row['conversations']; messages=conversations[:-1]
     begin=time.perf_counter()
     responses=model.chat(messages,system=row['system'],max_new_tokens=args.max_new_tokens,do_sample=False,temperature=0.0)
     latency=time.perf_counter()-begin
     raw=responses[0].response_text
     actual,strict_ok,extract_ok,extract_span,duplicate_keys=json_parse(raw)
     evaluation=evaluate_one(actual,sample['expected'],schema,catalog,intents,duplicate_keys) if extract_ok else evaluate_one(None,sample['expected'],schema,catalog,intents,duplicate_keys)
     item={'sample_id':sid,'scenario_id':sample['scenario_id'],'scenario_family_id':sample['scenario_family_id'],'split_group_id':sample['split_group_id'],
       'split':split,'task':sample['task'],'difficulty':sample['difficulty'],'challenge_tags':sample['challenge_tags'],'output_type':sample['expected']['output_type'],
       'raw_output':raw,'raw_json_parse_ok':strict_ok,'extractable_json_parse_ok':extract_ok,'json_extract_span':extract_span,'duplicate_json_keys':duplicate_keys,
       'parsed_output':actual,'expected_output':sample['expected']['model_output'],'generation':{'max_new_tokens':args.max_new_tokens,'do_sample':False,'temperature':0.0,
         'template':'qwen3_5_nothink','enable_thinking':False,'prompt_tokens':responses[0].prompt_length,'generated_tokens':responses[0].response_length,'finish_reason':responses[0].finish_reason,'latency_seconds':latency},
       'evaluation':evaluation,'model':{'base':args.model_path,'adapter':args.adapter_path}}
     out.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n'); out.flush()
     num+=1; print(json.dumps({'progress':num,'split':split,'split_index':i,'total_in_split':len(rows),'sample_id':sid,'tokens':responses[0].response_length,'seconds':round(latency,2),'parsed':extract_ok,'type':evaluation['actual_type'],'schema':evaluation['schema_valid'],'safe':evaluation['contract_safe']},ensure_ascii=False),flush=True)
 records=[json.loads(line) for line in output_path.read_text(encoding='utf-8').splitlines() if line.strip()]
 summary=summarize(records)
 report={'run_name':args.run_name,'completed_at':datetime.now().astimezone().isoformat(),'model':{'base':args.model_path,'adapter':args.adapter_path,'precision':'NF4 4-bit base'},
  'generation':{'splits':args.splits.split(','),'max_new_tokens':args.max_new_tokens,'do_sample':False,'temperature':0.0,'template':'qwen3_5_nothink','enable_thinking':False},
  'source_hashes':{'canonical_manifest':sha(CANONICAL/'dataset_manifest.json'),'canonical_samples':sha(CANONICAL/'samples.json'),'canonical_scenarios':sha(CANONICAL/'scenarios.json'),
   'setup_manifest':sha(SETUP/'manifest.json'),'setup_train':sha(SETUP/'llamafactory'/'train.json'),'setup_validation':sha(SETUP/'llamafactory'/'validation.json'),
   'model_output_schema':sha(SCHEMA_PATH),'tool_catalog':sha(CATALOG_PATH),'intent_catalog':sha(INTENT_PATH)},
  'elapsed_seconds_this_invocation':time.perf_counter()-started,'summary':summary,'records_file':str(output_path)}
 report_path=Path(args.report_json); report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'completed_records':len(records),'elapsed_seconds':report['elapsed_seconds_this_invocation'],'summary':summary},ensure_ascii=False),flush=True)

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--run-name',required=True); p.add_argument('--run-dir',required=True); p.add_argument('--output-jsonl',required=True); p.add_argument('--report-json',required=True)
 p.add_argument('--model-path',default=r'D:\AI\models\Qwen3.5-4B'); p.add_argument('--adapter-path'); p.add_argument('--splits',default='validation,test,hard_test'); p.add_argument('--max-new-tokens',type=int,default=1024); p.add_argument('--resume',action='store_true'); p.add_argument('--summary-only',action='store_true')
 args=p.parse_args(); run_eval(args)
if __name__=='__main__': main()
