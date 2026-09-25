# Shared Ledger verification workflow

This small workflow runs hand-written business scenarios against an isolated local Supabase project and saves the operation trace and final business state. A separate DeepSeek Judge can compare a completed run with `docs/backend/BUSINESS_LOGIC.md`; it reports a business verdict but does not change the database or code.

Scenarios describe business actions through the published RPCs. There is no reference model, general-purpose test DSL, or production database support.

## Prepare the local environment

Use Python 3.12+ and the Supabase CLI. To start the repository-configured local stack, run this from the repository root:

On Windows, if `python` points to another version, use `py -3.12` in place of `python` in the commands below.

```powershell
supabase start
```

Use any isolated Supabase instance on this machine; the runner accepts loopback URLs using `localhost`, `127.0.0.1`, or `::1`. The URL in `.env.example` (`http://127.0.0.1:54321`) is only a default example. Before running, confirm the selected database has all migrations from this repository, including `20260923032928`; for the repository-configured local stack, check with `supabase migration list --local`. Shared local databases may lag behind; verify their migration state and do not casually reset a shared database. The runner signs up a new random test user for each run and uses the local anon key and published client RPCs, never a service-role key.

From `verification/`, install the package and create the ignored local environment file:

```powershell
python -m pip install -e .
Copy-Item .env.example .env
```

Get the local `ANON_KEY` from `supabase status -o env` for the selected stack and set it as `SUPABASE_ANON_KEY` in `verification/.env`. Set `SUPABASE_URL` to that stack's loopback API URL. Set `DEEPSEEK_API_KEY` locally to enable judging; `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL` may be left blank to use the client's defaults. Never put a production Supabase URL or service-role key in this file. Keep the DeepSeek key private: `.env` is ignored by Git, and credentials are not written to run artifacts or logs.

For OpenCode Go, set `DEEPSEEK_BASE_URL=https://opencode.ai/zen/go` and `DEEPSEEK_MODEL=deepseek-v4.1-flash`; requests use `/v1/chat/completions` with a 120-second default timeout. Optionally set `DEEPSEEK_TIMEOUT_SECONDS` to a positive finite number of seconds to override the provider default (an explicit Python `timeout` argument takes precedence). Network/timeout, 429 and 5xx retries remain bounded to two retries per completion.

## Scenario v1

Each JSON scenario has `schema_version: 1`, `scenario_id`, `description`, `activity` (`type`, `base_currency`, `multi_currency_enabled`), `participants`, and ordered `operations`. Supported operation types are `create_expense`, `linked_refund`, `fifo_repayment`, `targeted_repayment`, `create_prepayment`, `return_prepayment`, and `void_transfer`. Participants and prior operations use short refs such as `A`, `B`, and `expense_1`; UUIDs, financial versions, request IDs, and database details belong to the runner. Write amounts as decimal strings, not JSON numbers: base-currency amounts allow at most one fractional digit, while foreign-currency original amounts allow up to four.

Expense operations use `ref`, `title`, `amount`, `currency`, and `payments`, plus either `split_method: "manual"` with `splits`, or `split_method: "aa"` with `aa_participants`. Repayments use `from_participant`, `to_participant`, `amount`, and `currency`; TARGETED also requires `target_expense_refs`. Prepayment and return operations use `owner_participant`, `custodian_participant`, `amount`, and `currency`. A linked refund uses a negative amount and `original_expense_ref` to identify its positive source expense. Void uses `transfer_ref` and `reason`. See the six examples in `scenarios/smoke/`.

## Run scenarios

Run these commands from `verification/`:

```powershell
python -m shared_ledger_verifier run scenarios/smoke/basic_single_payment.json
python -m shared_ledger_verifier run-all scenarios/smoke
```

The runner reports each scenario, operation progress, execution status, and result directory. `EXECUTED` means the RPC operations completed; it is not a business-level PASS judgment.

Each run is written under `verification/runs/<run_id>/`, with the input scenario, result summary, operation trace, and final state. Runs contain generated test data and are local output; review or remove them as needed.

## Judge a completed run

The Judge reads the run's `scenario.json` and `state_final.json`, together with the complete `docs/backend/BUSINESS_LOGIC.md`. From `verification/`, run one judgment or serially judge the newest `EXECUTED` run for each of the six configured Smoke scenarios:

```powershell
python -m shared_ledger_verifier judge runs/<run_id>
python -m shared_ledger_verifier judge-all runs
```

Each judgment is saved as `judge.json` in its run directory. The CLI prints each verdict and totals for `PASS`, `FAIL`, `UNCERTAIN`, and `JUDGE_ERROR`. `API_ERROR` results also record a safe `error_kind` (`timeout`, `network`, `http`, or `invalid_response`) and optional `http_status`; the CLI prints these diagnostics without exception text or response bodies. The first three are business assessments; `JUDGE_ERROR` means the model response or request could not be used. A returned `FAIL` or `UNCERTAIN` is recorded for review and does not modify business code or data.

## Smoke scenarios

- `basic_single_payment.json`: A pays 100 CNY; B bears it.
- `multi_payer_aa.json`: A and B both pay; A, B, and C split equally.
- `targeted_partial_repayment.json`: B pays 40 CNY against the selected 100 CNY expense owed to A.
- `prepayment_before_debt.json`: B prepays A 200 CNY before a later 100 CNY B-to-A debt.
- `linked_refund_after_settlement.json`: B settles the original debt, then a linked refund is received by B and benefits A.
- `multiple_repayments.json`: B repays A's 100 CNY debt by FIFO installments of 30, 20, and 50.

The Business Judge uses DeepSeek. To run the one-shot local LLM Probe v2, run this from `verification/`:

```powershell
py -3.12 -m shared_ledger_verifier local-llm-probe
```

Set `LOCAL_LLM_BASE_URL` in the ignored `.env` file if the local server differs from `http://127.0.0.1:1234/v1`; `LOCAL_LLM_TIMEOUT_SECONDS` defaults to 180. The probe discovers the actual model ID through `/models`; `LOCAL_LLM_MODEL` may be left blank. Set `LOCAL_LLM_API_KEY` only if LM Studio requires authentication. Probe v2.1 parses headings from `docs/backend/BUSINESS_LOGIC.md` and sends only the mapped sections for `expense_aa`, `targeted_repayment`, and `prepayment_refund`, once each in that order. It uses `json_schema` Structured Output with operation-specific `oneOf` / `const` constraints and immediately validates each result with the existing Scenario Loader, without repairing JSON, executing Supabase scenarios, or invoking the DeepSeek Judge. The ignored `verification/local_llm_probe/probe_v2_1_result.json` records section titles, input size, token usage when available, elapsed time, and Loader outcomes; generated scenarios are saved alongside it. Earlier v2 probe results remain untouched.

## Generate a case (Workflow v0.3, stage 1)

From `verification/`, generate one case for a supported focus:

```powershell
py -3.12 -m shared_ledger_verifier generate-case --focus expense_aa
```

The local Qwen model receives the focus-specific sections dynamically selected from `BUSINESS_LOGIC.md` and returns a lightweight raw business case. The separate DeepSeek Scenario Compiler receives that raw case, the complete business logic document, and the Scenario v1 input contract. Its Scenario JSON is passed unchanged to the existing Loader. If the Loader rejects it, the Compiler may make one repair request using the raw case, prior output, and Loader error; there is no manual repair. This command does **not** run Supabase or invoke the business Judge.

Each invocation writes an ignored directory under `verification/local_llm_probe/generated_cases/`. It contains `raw_case.json`, `compiler_result.json` (parsed Scenario attempts and Loader diagnostics, without provider reasoning), `scenario.json` (last compiled output), and `result.json` with model names, business logic commit, timings, repair count, and Loader status. Failed requests may have fewer artifacts if the corresponding stage produced no usable output. The CLI exits successfully only when the final Scenario passes the Loader.

## Run one generated case end to end (Workflow v0.3, stage 2)

With the isolated local Supabase stack and both model endpoints configured in `verification/.env`, run one focus from `verification/`:

```powershell
py -3.12 -m shared_ledger_verifier run-generated-case --focus expense_aa
```

The command generates a fresh Qwen raw case, compiles it with DeepSeek (at most one Loader-guided repair), validates it with the existing Loader, executes it with the existing Runner against loopback Supabase, and asks the separate DeepSeek Judge to assess the saved final state. It stops before judging if compilation or execution fails. A Judge verdict of `FAIL` or `UNCERTAIN` is saved as returned; it does not trigger a rerun or change the Scenario. Each invocation has its own run ID, test identity, and business data. The existing loopback URL and credential checks apply; do not point this command at Production.

The ignored case directory under `verification/local_llm_probe/generated_cases/` contains `raw_case.json`, `compiler_result.json`, `scenario.json`, `result.json`, `operations.jsonl`, `state_final.json`, and `judge.json` as far as each stage completes. `result.json` records models, business logic commit, stage latencies, Loader/Runner results, Judge verdict, and Compiler repair count. Credentials, authorization headers, and provider reasoning are excluded. The CLI exits successfully only after an `EXECUTED` run and a parsed `PASS`, `FAIL`, or `UNCERTAIN` verdict. This command runs one case; it does not start batch generation.

## Coverage framework (focus contracts, ScenarioPlan, duplicates)

Running a case is not the same as covering a behaviour. Three additions make a
batch report what it actually verified.

### Focus contracts

`focus_contract.py` owns a registry of 16 focuses. Each entry declares the
business shape it stands for (participant range, payer count, amount patterns,
operation count, edge tags) and a contract: a predicate over a parsed Scenario
that is decidable from the scenario alone, with no database access.

The pipeline gates on two things in order. The Loader answers "is this a legal
Scenario v1 document?"; the focus contract answers "does it exercise the
behaviour its focus claims?". A document that passes the Loader but fails its
contract is reported as `FOCUS_MISMATCH`: it is still executed and judged,
because it exercises real business logic, but it is excluded from every coverage
denominator. Both gates share the single permitted Compiler repair.

`expense_aa`, `targeted_repayment` and `prepayment_refund` are the historical
E2E smoke focuses and keep their original contracts. The formal coverage focuses
are `single_payer_aa`, `multi_payer_aa`, `aa_rounding`, `manual_split`,
`fifo_repayment`, `targeted_repayment`, `multiple_repayments`,
`prepayment_before_debt`, `prepayment_after_debt`, `prepayment_return`,
`linked_refund`, `negative_expense`, `void_transfer`, and `mixed_flow`.

### ScenarioPlan

`scenario_plan.py` derives a reproducible business shape from `(focus, seed)`.
A plan fixes the participant roster, how many of them pay, the exact amounts,
the amount pattern and the operation sequence, and is handed to both the Qwen
generator and the DeepSeek Compiler as facts they must encode. The same seed
always yields the same plan and therefore the same business data; different
seeds walk the variation space (participant_count 3-5, payer_count 1-3,
`divisible` / `non_divisible` / `decimal` / `large` / `small` amounts, 1-5
operations, and edge tags such as `rounding_residual`, `partial_repayment`,
`multiple_creditors`, `remaining_prepayment`, `full_settlement`).

`plan_for` validates every plan against its focus spec before it reaches a
model, so an unsatisfiable plan fails at planning time rather than burning a
generation request.

```powershell
py -3.12 -m shared_ledger_verifier generate-case --focus multi_payer_aa --seed 3
py -3.12 -m shared_ledger_verifier run-generated-case --focus void_transfer --seed 1
```

Omit `--seed` for the legacy behaviour (no plan). A run writes `plan.json`
alongside the other artifacts and records `plan_seed` and `plan_fingerprint` in
`result.json`.

### Duplicate detection and unique-valid coverage

`duplicates.py` reduces each scenario to a structural digest that maps every
participant ref and operation ref to its position, so renaming refs or rewording
titles does not change it, while changing any amount, payer, split method or
topology does. The first case carrying a given `(focus, fingerprint)` is
canonical; later ones are `DUPLICATE_CASE`.

`coverage.py` turns this into the batch counters. `unique_valid_count` -- focus
contract satisfied, Loader valid, and not a structural repeat -- is the only
denominator any pass rate may use. A run of 30 cases that all encode one
scenario has a coverage of one, however green the pipeline looks.

### Run a coverage batch

```powershell
py -3.12 -m shared_ledger_verifier coverage-run --per-focus 3 --seed-base 1
py -3.12 -m shared_ledger_verifier coverage-run --focus multi_payer_aa --focus aa_rounding --per-focus 2
```

`coverage-run` runs every formal coverage focus (or the ones named with
`--focus`), one case per `(focus, seed)`, then prints `generated_count`,
`focus_valid_count`, `focus_mismatch_count`, `duplicate_count`,
`unique_valid_count`, `distinct_scenarios`, the Judge verdict distribution and
the pass rate over unique valid coverage, and writes the full summary under
`local_llm_probe/coverage_reports/`.

The dashboard exposes the same counters at `GET /api/coverage`, includes them in
`GET /api/dashboard` under `coverage`, marks each case with `focus_status`,
`duplicate`, `duplicate_of` and `coverage_status`, and accepts
`GET /api/cases?coverage=UNIQUE_VALID|DUPLICATE|FOCUS_MISMATCH|NOT_VALID`. The
run form accepts `{"focuses": [...], "count": N, "seed": S}` to start a
multi-focus batch; the SSE endpoint replays a batch's earlier events to a late
subscriber and returns 404 for an unknown batch.
