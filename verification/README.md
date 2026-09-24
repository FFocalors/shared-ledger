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

The Business Judge uses DeepSeek. To check whether LM Studio can generate valid Scenario JSON v1 before developing the local generator, run this from `verification/`:

```powershell
py -3.12 -m shared_ledger_verifier local-llm-probe
```

Set `LOCAL_LLM_BASE_URL` in the ignored `.env` file if the local server differs from `http://127.0.0.1:1234/v1`. The probe discovers the actual model ID through `/models`; `LOCAL_LLM_MODEL` may be left blank. Set `LOCAL_LLM_API_KEY` only if LM Studio requires authentication. The probe validates LM Studio output with the existing Scenario Loader, without running Supabase scenarios or invoking the DeepSeek Judge. Its generated files and result are kept in the ignored `verification/local_llm_probe/` directory.
