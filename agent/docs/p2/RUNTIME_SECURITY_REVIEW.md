# P2 Runtime Security Review

## Review boundary

This is a CPU/fake-only review snapshot, not final P1/P2 acceptance. Reviewed the P2 entry wiring and runtime/API seam in `app/settings.py`, `app/components.py`, `app/main.py`, `app/api.py`, `app/p2_runtime.py`, `app/p2_backend.py`, and `app/p2_model_provider.py`; the independent lifecycle/auth/budget tests are in `tests/test_p2_runtime_security.py`. Snapshot revisions were main `3f938ee6114b763e6cd3dbd10792a78c691eb526` and agent `1a80a0f29e1ea432a60b95e7437af23d51182938`.

The observed wiring keeps P2 on the local provider/backend/runtime path. The Gateway implementation is unavailable, P2 proposals are deterministic acknowledgements, and no business-write path was exercised. The component lifecycle starts local resources and recovers interrupted Turns; it does not itself establish successful Auth, RLS, or live provider access. The model token-budget checker is optional configuration and fails closed when required but unavailable.

Per-request Auth grants are memory-only and scoped to owner plus Turn. Sensitive runtime steps revalidate the request bearer; a successful accepted auth-resume can replace the grant, while replay of an existing receipt does not extend or recreate it. Durable model/read counters remain with the generation across auth-resume. Cancellation racing a late provider response leaves the terminal cancellation in place and persists no late message. Terminal grant cleanup is asynchronous relative to the durable terminal commit; bounded finalizer cleanup is expected and was tested with a bounded wait.

## Verification

Command: `uv run --offline python -m pytest -q tests/test_p2_backend.py tests/test_p2_result_binding.py tests/test_p2_runtime_security.py`

Result: **46 passed in 3.65s**. The tests use temporary SQLite/journal state and fake Auth, provider, control, backend, and local transport. No live Supabase/Auth, LM Studio generation, production database, or Docker stack was used.

Evidence is preserved at `D:\AI\runs\shared-ledger\p2\backend-runtime-security-20261011T0355Z\` (`pytest.log`, `run-info.txt`, and `manifest.sha256`). Manifest SHA-256: `7c01d9ea71ef4468ba8a3569f9f165ae2d4a08a26e21c5a32eda996e6bdcd7b2`. The manifest binds the test and reviewed source hashes to the recorded run.

## Remaining acceptance boundary

Provider preregistration/model-output checks remain pending. Real B/D validation is deferred by the user, so no live identity, data, or service request was made. This snapshot does not establish live Auth/RLS behavior, production readiness, or completion of the full P1/P2 acceptance suite. Findings about API scope-error mapping, missing-journal response handling, and receipt-replay grant binding were already assigned to the runtime/API owner and are outside this snapshot's finality claim.
