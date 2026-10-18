# P2 volatile multi-result currentness R2

**Status:** implemented under root approval in the existing P2 runtime owner file; CPU fake evidence only. This is a narrow same-Turn/same-verified-Activity change. It does not change frozen v1 contracts, Store, backend, provider, Harness, API, preregistration, or live Supabase state.

## Behavior

After a complete financial result is durably appended, the runtime retains it as current only when its own durably committed typed `ToolReadResult` projection, operation, exact typed `ReadDecision`, result/evidence references, private owner/Turn binding snapshot, resolved Activity binding, scope fingerprint, context version, planning generation and financial-version map still match. Its body is independently fingerprinted from the durable typed result. The runtime's `source_fingerprint` is only a source/version/observation/result/query/scope/Turn-binding fingerprint; it is **not a raw PostgREST DTO hash** and does not prove that raw upstream JSON is recoverable. `ToolReadResult` remains the durable financial fact body.

Only a previously-current result from a distinct financial operation can remain current beside the new result, and only when the full financial-version maps agree. A same-operation reread permanently stales the older result. Any changed version, scope, binding, context, generation, missing provenance, or failed body/query/fingerprint check prevents the old result from joining a current answer. Activity listing remains point-in-time and does not join the financial currentness group.

The adapter sends only complete/current expense supplements to the provider and answer renderer. A stale prior expense supplement cannot block a current debt result. Existing membership and financial-version guards before model dispatch, after model generation, and before final commit remain in place. If the version changes, this implementation ends the current Turn without publishing a mixed-version answer. Read and model-call counters continue from their durable checkpoints.

The result snapshot validator verifies that the current model context exists and is an activity scope matching the private bound Activity reference. Expense activity scope is established through the bound expense, bound evidence and verified Activity binding; it does not read an `activity_ref` field from the v1 `ExpenseFact` contract, which has no such field. `ContractModel`, `ToolReadResult`, `BoundReference`, `ReadDecision`, and P2 provenance/supplement models are not frozen Pydantic models; `_TurnP2State` also retains some model references and a shallow tuple of bound-reference objects. The state objects are private runtime metadata, not public request input. Store bindings/results are append-only, durable Turn aggregates are reparsed from SQLite JSON, binding snapshots are compared with those fresh parses, and the committed result body is compared with a separate in-memory digest; validation does not depend on aggregate-object identity. The sidecar snapshots themselves are mutable Pydantic/dataclass objects (including a shallow tuple of references), however, so the implementation does not claim object-level immutability or tamper resistance against mutation by an in-process trusted component. These checks validate an internal binding/provenance fingerprint, not the original HTTP response bytes.

## Focused evidence

Run directory: `D:\AI\runs\shared-ledger\p2\multi-result-r2-20261012\`.

Current SHA-256: runtime source `9A17BA735A73DFDFDF4724E69ED2F527EA7CF0C40E9B435959A59290C72EE220`; new focused test `4DB630D6D2A724507F7B8BB5F82CA6EB349CA312F3287B417D2967A412221399`; requirements audit `667109720035D58018341D2044551DD56EBE212AF9E32A54626EF337EB8128EF`; protocol proposal `82EB113C787E6C639366967A5AA941FF92274B511C090E33C09A72985359C341`. This document’s hash and the pytest log/run metadata hashes are recorded in `manifest.sha256`.

Command run from `D:\project\Android\shared-ledger-agent\agent`:

```powershell
uv run --frozen --group dev --python 3.12 python -m pytest -p no:cacheprovider --basetemp 'D:\AI\runs\shared-ledger\p2\multi-result-r2-20261012\final-pytest-temp' -q tests/test_p2_multi_result_runtime.py tests/test_p2_runtime.py::test_expense_body_is_returned_to_next_model_and_answer_uses_trusted_dto
```

Result: **6 passed in 3.05s**, recorded in [`pytest.log`](D:/AI/runs/shared-ledger/p2/multi-result-r2-20261012/pytest.log). Temporary SQLite databases and pytest work files were under the same D: run directory. No LM Studio, Supabase, auth endpoint, or live database request was made.

The five new integration tests exercise:

- expenses → debts → one grounded answer with both current citations, exact payer/split detail and separate original amounts;
- same-operation reread permanently staling the older expense and excluding its supplement while keeping the latest expense and debt current;
- missing old provenance excluding the old expense and its supplement from the final answer;
- a changed financial version ending the Turn with only the prior expense body persisted and no answer message;
- claim release plus API cancellation while a backend read is blocked, followed by a late result that cannot append a read result or message.

The primary path makes three model calls and two reads; the reread path makes four model calls and three reads. This verifies counters do not reset between operations. The existing expense-body closed-loop test was run in the same command as a regression check.

## Limits

Provenance and supplements remain volatile. After restart, Auth pause, or loss of the internal per-Turn state, missing provenance is stale and the runtime fails closed; this change does not implement durable continuation or restart recovery. It does not establish live source DTO freshness, FV-0 label freshness, complete base-currency rendering, prepayment/repayment/refund reads, zero-row outcome evidence, or C/B/D acceptance. A separate same-Turn activity-list selection path remains an optional workflow proposal; the explicit old-reference/scope boundary is kept by current fresh scope resolution and new Turn bindings.

The exact current source/test/audit/proposal hashes and command output are in the run `manifest.sha256` and `pytest.log`; this document is not a substitute for the full P2 requirements audit or final release evidence.
