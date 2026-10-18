# P2 Runtime and Harness implementation plan

Status: the limited A engineering subset is implemented and its CPU/fake test suite passed. Model-quality and live backend validation remain separate acceptance gates. C completed 17 calls but failed semantic diagnostics (`FAIL_SEMANTIC_DIAGNOSTIC`); only transport compatibility is limited-pass. Thirteen outputs were nonempty and all clarified; schema validity was 10/17 pooled across candidate caps, and at default cap 768 it was 7/9 with 9/9 nonempty responses. For the six default-cap operation fixtures (three reads and three proposals, one per operation), exact read/proposal selection was 0/3 each; grounded answers/citations were zero. The clarification kind passed 1/1, but required missing slots matched 0/1. An expense-context response contradicted available scope/read facts; false refusals are failures, while the four empty responses are unassessable. No critical financial assertions about amount, currency, debt direction, settlement, participant, citation, or write success were observed in the 13 nonempty outputs; this does not establish safety. Neither C bundle is part of the A CPU test result below.

## Scope and verification

- Agent checkout: branch `agent`, HEAD `1a80a0f29e1ea432a60b95e7437af23d51182938` at the recorded baseline. Business checkout `D:\project\Android\shared-ledger` is read-only.
- P1 plus P2 tests: `PYTHONPATH=.. .venv\Scripts\python.exe -X utf8 -m pytest tests -q`, run from `D:\project\Android\shared-ledger-agent\agent`; 248 passed in 46.60 seconds.
- Read-only frozen export check: `PYTHONPATH=.. .venv\Scripts\python.exe -X utf8 -m agent.app.export_contracts --check`; exit 0, snapshot matches manifest.
- Verification ran on the Windows host. P2 Docker/container deployment and interruption/recovery were not tested; P1 Docker evidence does not transfer to P2. The D-drive journal/model/counter paths are host paths, not Linux container paths.
- Durable command/result logs and file hashes: `D:\AI\runs\shared-ledger\p2\acceptance-20261011T040422Z-runtime-final`. The original command wrapper recorded elapsed time but no wall-clock start/end; evidence records that limitation rather than estimating a timestamp.
- The 248-test CPU command did not execute `agent/evaluation`, T1, T0, sealed data, live Supabase Auth/Data API, or live LM Studio inference. B and D are `NOT_RUN_USER_DEFERRED`. C is a separate live provider/Harness probe; it completed with a semantic diagnostic failure as described above.

## Implemented safe subset

P2 reuses the durable v1 Turn scheduler and frozen v1 `ModelContext`, `ModelReadResult`, `ToolReadResult`, and `SemanticDecision`. A successful read stores the complete typed body already supported by v1 and supplies it to the next model decision. P2-only trusted metadata is a typed runtime-owned provider envelope; it does not change the canonical contract or export.

The runtime allows bounded authenticated reads for `read.activities`, `read.expenses`, and `read.debts`. Activity-list reads use verified no-activity scope; expense/debt reads require one verified activity scope. Scope bootstrap and each backend read are server-side, use the current per-Turn verified token and RLS, and apply bounded pagination, response-size and version checks. Only a complete result within v1 capacities is appended. Incomplete, stale, over-capacity or unavailable reads fail closed; they are never represented as an empty list.

The runtime also accepts valid proposal intents only to produce a deterministic statement that this build does not create a preview, confirmation card, proposal, or write. `Gateway` remains `Unimplemented`. Invalid or incomplete proposal intents are clarified using a fixed prompt derived from typed missing slots. Model-authored clarification prose is not shown.

API event polling requires exact proof for closed P2 dependency-error events. Unproved errors are hidden and bounded read-ahead can return following status events while keeping the v1 cursor equal to the last delivered event. Source-free clarification prompts must match the deterministic missing-slot templates. Business fact events still require backend scope authorization.

## Runtime, grants, and limits

- The Auth-verified bearer is held only in a memory lease bound to exact owner and Turn, bounded by configured lease (maximum 300 seconds). It is excluded from durable Store data, prompts, logs and DTOs. Accepted auth resume may install a new lease; idempotency receipt replay does not extend or recreate one. Terminal/cancelled Turns revoke the lease.
- Auth resume/restart preserve current generation counters. A user clarification starts a new generation. Defaults cap each generation at 6 model calls, 4 backend reads and 1 repair; model concurrency is 1. Admission is fixed at one running and one queued task per user, with global queue 16. The other response, context, timeout and HTTP limits are bounded separately.
- Failed/offline dependencies save a closed, sanitized dependency event, revoke the in-memory lease and pause at the existing `AUTH_REQUIRED` checkpoint for explicit recovery. This does not claim the token expired and does not retry indefinitely.
- Each output is checked against the durable claim/checkpoint before persistence; late output after cancellation, timeout or a competing state change loses the CAS. A saved FINALIZE answer resumes directly without model regeneration.
- The optional exact-artifact token counter requires explicit artifact path/hash/size, model path, API origin, context limit and counter interpreter settings. It is disabled by default. No health/start path hashes, loads or probes a model. A provider is not ready until a real parsed inference succeeds.

## Known acceptance gaps

- v1 supports at most 16 read results, 64 typed bound references, 48 durable evidence entries, and 16 fact items per result, but has no cursor/continuation representation. The current backend consumes all pages in a single call, returns only a complete result of at most 16 facts, and otherwise tells the user to narrow the query. Cross-request/restart continuation is not implemented.
- Each successful new read marks previous P2 provenance stale. The current subset supports a latest-current-result answer, not combined multi-operation evidence in one answer. Store bodies remain append-only. After restart/auth recovery, missing private provenance makes a stored body stale; the runtime asks for new user input instead of sending that body to the model again.
- A zero-row read has no citation-bearing fact in frozen v1. The runtime completes with an explicit deterministic message that the current protocol cannot express a cited zero-result answer; it does not fabricate policy evidence.
- Canonical `ExpenseFact` carries original amount/currency only; canonical `DebtFact` carries original debt amount/currency only. Internal P2 expense supplements retain backend payment/split rows and base amounts, but the current renderer displays only each payment/split line's original amount/currency. Debt base amounts/totals remain private DTO/version inputs and are not rendered as facts. No base-currency summary or computed balance is claimed.
- Prepayment/refund operations, signed-refund semantics, and complete payment/split rendering are not implemented. No sum/netting/currency conversion is done by the Agent.
- Activity-list-to-different-activity read in the same Turn is not supported because v1 bindings are append-only and all activity-scoped refs must match one selected activity. Start a new Turn from the verified UI activity context.

## Files and protected boundaries

P2 modules are `agent/app/p2_identity.py`, `p2_harness.py`, `p2_runtime.py`, `p2_backend.py`, `p2_journal.py`, `p2_model_provider.py`, and `p2_token_budget.py`; P2 tests are the `agent/tests/test_p2_*.py` files. Minimal wiring is in `api.py`, `components.py`, and `settings.py`. File hashes are recorded in the independent D-drive source snapshot.

`agent/app/store.py`, canonical `contracts.py`, v1 exports/manifest, migrations, the old P1 Runtime/Harness, old P1 tests, and shared README/development-guide files were not edited by the P2 runtime worker. No commit or push was made. T1 frozen protocol documentation and metadata/fingerprint hashes were reviewed as required; sealed dataset contents and Teacher/evaluation execution were not accessed. Two independently reported T1 file changes are documented as external baseline drift and were not restored or modified. The final source/test snapshot is `D:\AI\runs\shared-ledger\p2\final-delivery-20261011T0427Z-runtime\source-test-snapshot.json`.

For exact environment names and a safe disabled profile, see [P2_CONFIGURATION_EXAMPLE.md](P2_CONFIGURATION_EXAMPLE.md). A live `provider_mode=p2` setup remains gated on B Auth/RLS acceptance; no real Supabase credentials or live setup were used for the A verification.
