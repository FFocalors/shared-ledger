# Offline Dataset Validator v0.1

Read-only validation gate for Shared Ledger Scenario, Sample, Dataset, and Manifest JSON. The validator performs no network access, model calls, database access, or input-file writes. Frozen `$id` references are registered from the repository files before JSON Schema validation, so `shared-ledger.invalid` is never fetched.

Install the one declared dependency once in the Python environment used by the pipeline:

```powershell
python -m pip install -r scripts/ai_dataset_validator/requirements.txt
```

The dependency is `jsonschema[format]`, which validates Draft 2020-12 schemas and UUID/date-time formats. No project Python dependency manager existed when this tool was added. Python 3.9+ and the repository checkout are required.

## Run

```powershell
python scripts/ai_dataset_validator/cli.py validate examples
python scripts/ai_dataset_validator/cli.py validate dataset path\to\dataset
python scripts/ai_dataset_validator/cli.py validate scenario path\to\scenario.json
python scripts/ai_dataset_validator/cli.py validate sample path\to\sample.json
python scripts/ai_dataset_validator/cli.py validate manifest path\to\dataset_manifest.json
python scripts/ai_dataset_validator/cli.py validate examples --json-report
```

Dataset directories contain `scenarios.json`, `samples.json`, and optionally `manifest.json` (the bundled `examples/` folder uses `dataset_manifest.json`). Manifest artifact paths are relative to the Dataset root. A report contains `valid`, `errors`, `warnings`, `info`, and recomputed `statistics`. Exit code is `0` with no errors, `1` when validation finds errors, and `2` for an invalid CLI/input path. Warnings do not change `valid` or the exit code.

## Checks

The validator runs the frozen Scenario, Sample, Manifest, ContextEnvelope, and Model Output Draft 2020-12 schemas first. It then checks version/SHA and catalog references, Scope and Tool exposure, output-to-intent/tool mapping, proposal arguments/diffs/confirmation policy, D4 restrictions, clarification/entity annotations, context consistency, lifecycle approval evidence and audit notes, Teacher provenance and candidate governance, privacy flags, canonical Ground Truth, pending policy, family/split leakage, exact and normalized duplicate surfaces, and recomputed Manifest counts, statistics, and artifact hashes. Model-visible Sample input is checked for production Dataset/Family/Scenario/Sample metadata; typed `result_id`, `verified_result_ids`, and recent-action `action_id` remain valid business evidence. Canonical Scenario checks also enforce operation argument mirrors, unique declared entity IDs, declared references for formal entity fields and lookup candidates, recorded-fact shape/source/uniqueness, and lookup resolution cardinality; aggregate Scenario statistics include unique/multiple/zero lookup counts. The content-authenticity preflight applies to `business_logic`-sourced Canonical Scenarios: it rejects exact Family/Matrix-title reuse, user-facing training metadata, workflow labels in business titles/queries, low-quality evidence lines, unused declared entities, clarification/D4/context tag-state mismatches, and duplicate normalized assertions. Other source types such as schema-fixture `manual` examples keep their existing fixture role and are not treated as Gold Seed candidates.

`ERROR` blocks publication/training. This includes schema/reference failures, D4 execution, DEFERRED actions, confirmation bypass, Ground Truth changes, split leakage, duplicate samples, pending records assigned to a split, privacy flags, and Manifest mismatches. `WARNING` is currently used for normalized surface duplicates and repeated semantic group keys within the same split, including deliberate same-utterance UI comparisons; it requires review but does not block. Cross-split normalized or semantic-group repetition is an error. `INFO` is reserved for non-blocking summaries and is empty unless a future rule adds it.

Canonical Training Dataset v0.1 manifests explicitly declare `assembly_mode=canonical_training_v0.1`. In that mode, the exact frozen Scenario snapshot remains at source `split=unassigned`; split authority is the hash-verified `split_assignment.json` and assembled Samples. The validator verifies every assembled Sample against its frozen Gold/Teacher source record, requires full source-ID/hash traceability, approved reviewed Samples, active/pending split policy, and closed Family/split_group assignments. It also rejects NFKC/casefold/whitespace-normalized Surface pairs with `SequenceMatcher >= 0.90` across different splits. Other Dataset modes retain the ordinary Scenario/Sample split agreement rules.

## Teacher pipeline

The batch interface accepts Dataset directories and JSON reports for orchestration:

```text
Teacher output → samples.json → validate dataset <directory> --json-report → human review → approved
```

Teacher samples must start in `generated`, include provider/model/run/prompt/time/temperature provenance, and keep canonical Ground Truth unchanged. The validator never promotes lifecycle state or edits/repairs the Dataset.

## Offline limits

Deterministic checks cover structured invariants only. General meaning-level paraphrase detection, privacy identification from arbitrary prose, whether context is semantically minimal, and whether an explanation is factually adequate require human review. The Canonical Training assembly uses a fixed string-similarity threshold only as a cross-split leakage guard; it is not a general semantic equivalence detector.

Tool roles are derived from the Intent Catalog: `possible_tools` are PRIMARY, while `supporting_lookup_tools` are explicitly authorized read-only L0 lookups for that business Intent. The bundled examples use `query_expense → find_expenses` and `create_expense → find_participants`; the Validator applies the same mapping rules to every record and has no record-ID exceptions. An unrelated read Tool remains invalid.

Run the compact offline regression suite (55 focused positive/negative cases, including Supporting Lookup roles, canonical-state, expected-result, expected-diff, frozen UI enum, authenticity checks, approved-Sample evidence, mock-candidate governance, model-visible metadata rejection, canonical-training source trace/split checks, and the bundled Example baseline check) with:

```powershell
python -m unittest discover -s scripts/ai_dataset_validator/tests -v
```

## P0 Gold Sample production checks

When the complete P0 Family scenario set from the Coverage Matrix is supplied, dataset validation checks each P0 `sample_target` against the formal Gold Seed subset (`surface_form_type=human_authored`, `trust.level=GOLD`, and `lifecycle_status=approved`), rejects such samples for `SYNTHETIC_UNVERIFIED` scenarios, and compares each complete Sample Model Output with its Canonical Scenario output. Teacher-generated SILVER candidate pools are validated normally but do not count toward or against Gold Seed quotas; a mixed batch reconciles quotas using only its formal Gold Seed subset. An empty Sample batch still reports missing P0 quotas. Partial datasets, Examples, and nonempty Teacher-only candidate pools do not trigger the Gold Seed quota gate. Manifest scope statistics include zero-count frozen scopes, so P0 batches with no DEFERRED records still match the Dataset Manifest Schema.
