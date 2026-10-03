#!/usr/bin/env python3
"""Check the frozen 73 held-out model outputs against the offline contract schemas."""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import evaluate_generation as evaluator
root=Path(__file__).resolve().parents[2]
samples=evaluator.load_json(root/'docs/ai/dataset/canonical_training/v0.1/samples.json')
schema=evaluator.load_json(evaluator.SCHEMA_PATH); catalog=evaluator.load_json(evaluator.CATALOG_PATH)
selected=[x for x in samples if x['split'] in ('validation','test','hard_test')]
errors=[]; by_type=Counter()
for sample in selected:
 out=sample['expected']['model_output']; errs=evaluator.validate_schema(out,schema,schema,catalog)
 by_type[sample['expected']['output_type']]+=1
 if errs: errors.append({'sample_id':sample['sample_id'],'errors':errs[:10]})
report={'checked':len(selected),'by_split':{s:sum(x['split']==s for x in selected) for s in ('validation','test','hard_test')},'by_output_type':dict(by_type),'schema_errors':len(errors),'errors':errors}
out=Path(sys.argv[1]) if len(sys.argv)>1 else Path.cwd()/'expected_schema_report.json'
out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(1 if errors else 0)
