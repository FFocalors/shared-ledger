# Shared Ledger verification smoke workflow

This small workflow runs hand-written business scenarios against the repository's isolated local Supabase project and saves the operation trace and final business state. It complements the database and Android test suites; it does not replace them or decide whether a result is semantically correct.

The current version has no LLM integration, reference model, general-purpose test DSL, or production database support. Scenarios describe business actions through the published RPCs.

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

Get the local `ANON_KEY` from `supabase status -o env` for the selected stack and set it as `SUPABASE_ANON_KEY` in `verification/.env`. Set `SUPABASE_URL` to that stack's loopback API URL. Never put a production URL or service-role key in this file.

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

## Smoke scenarios

- `basic_single_payment.json`: A pays 100 CNY; B bears it.
- `multi_payer_aa.json`: A and B both pay; A, B, and C split equally.
- `targeted_partial_repayment.json`: B pays 40 CNY against the selected 100 CNY expense owed to A.
- `prepayment_before_debt.json`: B prepays A 200 CNY before a later 100 CNY B-to-A debt.
- `linked_refund_after_settlement.json`: B settles the original debt, then a linked refund is received by B and benefits A.
- `multiple_repayments.json`: B repays A's 100 CNY debt by FIFO installments of 30, 20, and 50.

There is no DeepSeek or local-LLM code in this phase. The only proposed next step is a separate DeepSeek business judge that evaluates saved runs against `docs/backend/BUSINESS_LOGIC.md`.
