# Teacher Generator Phase 1 and Bounded Live Pilot

This tool builds a versioned Teacher Request and an isolated Candidate Sample from the frozen P0 Gold Seed. Its default path is deterministic mock generation. The opt-in `live-pilot` command supports a small, bounded OpenAI-compatible provider run and writes artifacts only below `runs/live-pilot/`; it never edits or appends to the frozen Gold Seed.

## Frozen inputs and flow

The generator verifies `docs/ai/dataset/gold_seed/v0.1/p0/dataset_manifest.json` is `frozen` and that its Scenario and Sample artifact hashes match before planning. It also records SHA-256 fingerprints for the Coverage Matrix, AI Contract, AI Scope, Intent and Tool Catalogs, Model Output and Context Envelope schemas, Dataset Scenario/Sample schemas, and Validation Rules. Family IDs must resolve through the canonical Scenario, an approved GOLD Sample, and the corresponding Coverage Matrix row. FIN-002 has no Gold Sample and therefore cannot be selected. The deterministic flow is:

`Family → frozen Gold Seed → Variant Plan → Teacher Request → parsed Surface Form → Candidate Sample`

Variant Plan records a stable seed, Matrix target, source Sample and split group, inherited difficulty, safe style options (colloquial, ASR-like, pronoun/ellipsis, or existing multi-turn), and the actual available UI/interaction/conversation context profile. A style that is unsupported by the selected seed is rejected. The seed selects from sorted family samples, so repeated planning is stable.

The provider payload carries the seed wording/context and metadata-free locked business facts plus an anonymized `locked_expected_output` anchor. UUIDs and opaque result IDs are replaced with symbolic aliases; local Scenario, Family, Sample IDs, file paths, hashes, Matrix metadata, run IDs, and Dataset version remain only in local request trace data. Prompt v1.0.0 permits only a Surface Form response. Parsing rejects missing/extra keys, output-shaped responses, changed turn IDs/roles/count, and malformed text. The candidate's `expected` is copied locally from the frozen seed and deep-compared; Teacher output cannot supply or change Ground Truth.

Candidate lifecycle is `generated`, trust is `SILVER`, `surface_form_reviewed=false`, and `example_only=true`; it retains the Scenario, Family, split group, split and all business/context fields except the permitted user wording and corresponding conversation message text. Provenance captures provider/model, run, prompt version, seed, fixed mock time, request/source Sample reference and generator version. A mock Candidate is rejected by the Dataset Validator if marked GOLD, approved, assigned to a split, or not example-only. Candidate validation also checks it against the entire frozen Sample set so exact/normalized duplicates and semantic-group review warnings remain visible. Warnings mark a run `candidate_review_required`; they require human review even when schema/contract validation succeeds. The Candidate is never appended to the frozen P0 Dataset.

## Commands

From the repository root:

```powershell
python scripts/ai_teacher_generator/cli.py plan --family family_exp_create_001 --seed 19 --style colloquial
python scripts/ai_teacher_generator/cli.py request --family family_exp_create_001 --seed 19 --style colloquial --out scripts/ai_teacher_generator/runs/request-preview.json
python scripts/ai_teacher_generator/cli.py mock-dry-run --families family_exp_create_001 family_conv_001 --seed 19 --out-dir scripts/ai_teacher_generator/runs/mock-dry-run
python scripts/ai_teacher_generator/cli.py validate --candidate scripts/ai_teacher_generator/runs/mock-dry-run/mock-ce5fda2faa2afaa7/candidate_sample.json --scenario docs/ai/dataset/gold_seed/v0.1/p0/scenarios.json
```

`validate` accepts one canonical Scenario object or the combined index and selects the matching `scenario_id`. Repeating `mock-dry-run` with the same family/seed overwrites the same deterministic run directory with byte-identical artifacts. Each run contains `request.json`, `response.json`, `candidate_sample.json`, and `run_manifest.json`; the manifest says `training_eligible=false` and `remote_provider_called=false`. Generated runs are ignored by default; the checked-in `runs/mock-dry-run/` tree is the explicit non-training acceptance fixture and can be deleted/regenerated independently.

The prompt template is [surface-variant-v1.0.0.md](prompts/surface-variant-v1.0.0.md). Install the local validator dependency if needed with `python -m pip install -r scripts/ai_teacher_generator/requirements.txt`. Run its focused tests and the existing Validator suite with:

```powershell
python -m unittest discover -s scripts/ai_teacher_generator/tests -v
python -m unittest discover -s scripts/ai_dataset_validator/tests -v
```

## Provider configuration and live pilot

The ignored local file is `scripts/ai_teacher_generator/.env`; `.env.example` lists `TEACHER_PROVIDER`, `TEACHER_MODEL`, `TEACHER_API_KEY`, `TEACHER_BASE_URL`, and `TEACHER_TEMPERATURE`. The live pilot reads the key only in memory and sends it as the Authorization header. Requests identify this generator with `User-Agent: shared-ledger-teacher-generator/0.1.2` and use a stable, non-sensitive `x-opencode-session` value for the duration of a run. Headers and the key are never written into requests, responses, audits, or manifests. HTTP error bodies are checked for the configured key and redacted before persistence.

Run the explicitly authorized bounded pilot with:

```powershell
python scripts/ai_teacher_generator/cli.py live-pilot --timeout 75
```

The plan is 8 representative Families × 3 variants (24 requests); each request may have at most one retry, and only for transient transport/status failures, with a hard total ceiling of 32 attempts. Use `probe-live` for one no-retry connection and response-contract check before a fresh pilot. Every call retains its request, raw response or sanitized failure, parsed response/candidate when available, and audit record. The run manifest includes provider/model, usage/cost when reported, frozen source hashes, and `training_eligible=false`. Candidates remain SILVER/generated/unassigned and require independent human review; they are never part of the Gold Seed or training dataset. OpenCode Go accepts either the base `https://opencode.ai/zen/go` or the full documented `/zen/go/v1/chat/completions` endpoint.
