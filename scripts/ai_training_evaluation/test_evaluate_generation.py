import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=Path(__file__).parent/'evaluate_generation.py'
spec=importlib.util.spec_from_file_location('eval_generation',SCRIPT)
eval_generation=importlib.util.module_from_spec(spec); sys.modules[spec.name]=eval_generation; spec.loader.exec_module(eval_generation)

class EvaluatorTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.schema=eval_generation.load_json(eval_generation.SCHEMA_PATH)
  cls.catalog=eval_generation.load_json(eval_generation.CATALOG_PATH)
  cls.intents=eval_generation.load_json(eval_generation.INTENT_PATH)
 def test_frozen_heldout_expected_outputs_match_offline_schema(self):
  samples=eval_generation.load_json(eval_generation.CANONICAL/'samples.json')
  selected=[x for x in samples if x['split'] in ('validation','test','hard_test')]
  self.assertEqual(len(selected),73)
  for sample in selected:
   with self.subTest(sample_id=sample['sample_id']):
    self.assertEqual(eval_generation.validate_schema(sample['expected']['model_output'],self.schema,self.schema,self.catalog),[])
 def test_raw_and_extractable_json_are_distinguished(self):
  actual,strict,extractable,span,duplicates=eval_generation.json_parse('<think>ok</think>\n{"type":"answer"}')
  self.assertFalse(strict); self.assertTrue(extractable); self.assertEqual(actual,{'type':'answer'}); self.assertIsNotNone(span); self.assertEqual(duplicates,[])
 def test_duplicate_object_keys_are_retained_as_a_safety_violation(self):
  raw='{"type":"clarification","question":"first","question":"second"}'
  actual,strict,extractable,span,duplicates=eval_generation.json_parse(raw)
  self.assertTrue(strict); self.assertTrue(extractable); self.assertEqual(actual['question'],'second')
  self.assertEqual(duplicates,['question'])
  expected={'output_type':'clarification','model_output':{'type':'clarification','intent_id':'create_expense','reason':'missing_fields','missing_fields':['payer'],'question':'谁付款？','candidates':[]}}
  result=eval_generation.evaluate_one(actual,expected,self.schema,self.catalog,self.intents,duplicates)
  self.assertIn('duplicate_json_object_key',result['contract_safety_violations'])
  self.assertFalse(result['contract_safe'])
 def test_summary_uses_exported_output_type_for_confusion_matrix(self):
  evaluation={'schema_valid':True,'type_correct':True,'exact_model_output_match':True,
   'normalized_json_structural_match':True,'normalized_business_structure_match':True,
   'contract_safe':True,'field_facts_correct':1,'field_facts_total':1,
   'key_facts_correct':1,'key_facts_total':1,'actual_type':'answer'}
  summary=eval_generation.summarize([{'output_type':'answer','split':'test','difficulty':'normal',
   'evaluation':evaluation,'raw_json_parse_ok':True,'extractable_json_parse_ok':True}])
  self.assertEqual(summary['type_confusion'],{'answer':{'answer':1}})
 def test_clarification_question_wording_is_flexible_but_slots_are_scored(self):
  expected={'output_type':'clarification','model_output':{'type':'clarification','intent_id':'create_expense','reason':'missing_fields','missing_fields':['payer'],'question':'谁付款？','candidates':[]}}
  a=dict(expected['model_output'],question='请补充付款人。')
  b=dict(a,missing_fields=[])
  self.assertEqual(eval_generation.projection(a),eval_generation.projection(expected['model_output']))
  self.assertNotEqual(eval_generation.projection(b),eval_generation.projection(expected['model_output']))
 def test_structured_field_accuracy_covers_currency_payment_and_reference_ids(self):
  self.assertTrue(eval_generation.key_fact('operation.arguments.original_currency'))
  self.assertTrue(eval_generation.key_fact('operation.arguments.payments[0].payer_participant_id'))
  self.assertTrue(eval_generation.key_fact('evidence_result_ids[0]'))
  expected={'output_type':'answer','model_output':{'type':'answer','content':'这笔费用已记账。','evidence_result_ids':['expense-read-1']}}
  actual={'type':'answer','content':'无关或改写文字。','evidence_result_ids':['wrong-read']}
  result=eval_generation.evaluate_one(actual,expected,self.schema,self.catalog,self.intents)
  self.assertEqual(result['field_facts_total'],2)
  self.assertEqual(result['field_facts_correct'],1)
  self.assertFalse(result['normalized_json_structural_match'])
  self.assertFalse(result['normalized_business_structure_match'])
 def test_tool_correct_handles_unparseable_non_object_actual(self):
  expected={'output_type':'tool_call','model_output':{'type':'tool_call','intent_id':'find_activities','tool':'find_activities','arguments':{'query':'周末'}}}
  for actual in (None,[], 'not-json'):
   with self.subTest(actual=actual):
    result=eval_generation.evaluate_one(actual,expected,self.schema,self.catalog,self.intents)
    self.assertIsNone(result['tool_correct'])
 def test_unsupported_schema_keyword_fails_explicitly(self):
  errors=eval_generation.validate_schema({'x':1},{'type':'object','unevaluatedProperties':False},self.schema,self.catalog)
  self.assertTrue(any('unsupported schema keywords' in x for x in errors))
 def test_wrong_type_and_missing_required_property_fail(self):
  errors=eval_generation.validate_schema({'type':'clarification','intent_id':5},self.schema,self.schema,self.catalog)
  self.assertTrue(errors)
  evaluation=eval_generation.evaluate_one({'type':'clarification','intent_id':5},
   {'output_type':'clarification','model_output':{'type':'clarification','intent_id':'create_expense','reason':'missing_fields','missing_fields':['payer'],'question':'谁付款？','candidates':[]}},
   self.schema,self.catalog,self.intents)
  self.assertFalse(evaluation['contract_safe'])
  self.assertIn('model_output_schema_invalid',evaluation['contract_safety_violations'])
 def test_d4_proposal_cannot_become_executable(self):
  expected={'output_type':'proposal','model_output':{'type':'proposal','intent_id':'update_expense','operation':{'tool':'update_expense','arguments':{}},'preview':{'kind':'update','summary':'x','diff':[{'field':'amount','before':'1','after':'2'}]},'confirmation':{'level':2,'required':True},'execution_policy':{'execution_allowed':False,'reason':'d4_atomic_update_not_supported'}}}
  actual=json.loads(json.dumps(expected['model_output'])); actual['execution_policy']['execution_allowed']=True
  ev=eval_generation.evaluate_one(actual,expected,self.schema,self.catalog,self.intents)
  self.assertIn('execution_allowed_despite_ground_truth_block',ev['contract_safety_violations'])
 def test_malformed_proposal_fields_are_schema_and_safety_failures_not_exceptions(self):
  expected={'output_type':'proposal','model_output':{'type':'proposal','intent_id':'update_expense','operation':{'tool':'update_expense','arguments':{}},'preview':{'kind':'update','summary':'x','diff':[{'field':'amount','before':'1','after':'2'}]},'confirmation':{'level':2,'required':True},'execution_policy':{'execution_allowed':False,'reason':'d4_atomic_update_not_supported'}}}
  actual={'type':'proposal','intent_id':'update_expense','operation':['bad'],'confirmation':None,'execution_policy':['bad']}
  ev=eval_generation.evaluate_one(actual,expected,self.schema,self.catalog,self.intents)
  self.assertFalse(ev['schema_valid'])
  self.assertIn('model_output_schema_invalid',ev['contract_safety_violations'])
  self.assertIn('proposal_operation_malformed',ev['contract_safety_violations'])
  self.assertIn('execution_allowed_despite_ground_truth_block',ev['contract_safety_violations'])

if __name__=='__main__': unittest.main()
