import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/'evaluate_generation.py'
spec=importlib.util.spec_from_file_location('eval_generation',SCRIPT)
eval_generation=importlib.util.module_from_spec(spec); sys.modules[spec.name]=eval_generation; spec.loader.exec_module(eval_generation)

class EvaluatorTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.schema=eval_generation.load_json(eval_generation.SCHEMA_PATH)
  cls.catalog=eval_generation.load_json(eval_generation.CATALOG_PATH)
  cls.intents=eval_generation.load_json(eval_generation.INTENT_PATH)
 def test_all_73_frozen_heldout_outputs_match_offline_schema(self):
  samples=eval_generation.load_json(eval_generation.CANONICAL/'samples.json')
  selected=[x for x in samples if x['split'] in ('validation','test','hard_test')]
  self.assertEqual(len(selected),73)
  for sample in selected:
   with self.subTest(sample_id=sample['sample_id']):
    self.assertEqual(eval_generation.validate_schema(sample['expected']['model_output'],self.schema,self.schema,self.catalog),[])
 def test_raw_and_extractable_json_are_distinguished(self):
  actual,strict,extractable,span=eval_generation.json_parse('<think>ok</think>\n{"type":"answer"}')
  self.assertFalse(strict); self.assertTrue(extractable); self.assertEqual(actual,{'type':'answer'}); self.assertIsNotNone(span)
 def test_clarification_question_is_flexible_but_slots_and_reason_are_scored(self):
  expected={'type':'clarification','intent_id':'create_expense','reason':'missing_fields','missing_fields':['payer'],'question':'谁付款？','candidates':[]}
  changed=dict(expected,question='请补充付款人。')
  wrong_slot=dict(changed,missing_fields=[])
  wrong_reason=dict(changed,reason='needs_explicit_financial_choice')
  self.assertEqual(eval_generation.projection(changed),eval_generation.projection(expected))
  self.assertNotEqual(eval_generation.projection(wrong_slot),eval_generation.projection(expected))
  self.assertNotEqual(eval_generation.projection(wrong_reason),eval_generation.projection(expected))
 def test_unsupported_schema_keyword_fails_explicitly(self):
  errors=eval_generation.validate_schema({'x':1},{'type':'object','unevaluatedProperties':False},self.schema,self.catalog)
  self.assertTrue(any('unsupported schema keywords' in x for x in errors))
 def test_wrong_type_and_missing_required_property_fail(self):
  errors=eval_generation.validate_schema({'type':'clarification','intent_id':5},self.schema,self.schema,self.catalog)
  self.assertTrue(errors)
 def test_d4_proposal_cannot_become_executable(self):
  expected={'output_type':'proposal','model_output':{'type':'proposal','intent_id':'update_expense','operation':{'tool':'update_expense','arguments':{}},'preview':{'kind':'update','summary':'x','diff':[{'field':'amount','before':'1','after':'2'}]},'confirmation':{'level':2,'required':True},'execution_policy':{'execution_allowed':False,'reason':'d4_atomic_update_not_supported'}}}
  actual=json.loads(json.dumps(expected['model_output'])); actual['execution_policy']['execution_allowed']=True
  ev=eval_generation.evaluate_one(actual,expected,self.schema,self.catalog,self.intents)
  self.assertIn('execution_allowed_despite_ground_truth_block',ev['contract_safety_violations'])

if __name__=='__main__': unittest.main()
