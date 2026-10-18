# P1 real local Supabase Auth smoke

This report records a real Auth run against the already-running local Supabase instance on 2026-10-10. It supplements the mock-only P1-04 evidence and does not claim that an Auth-issued expired token was tested.

The helper created two unique temporary users through the local Auth API, performed password sign-in for both, and verified each returned access token through `/auth/v1/user`. It then started one isolated Agent process bound to `127.0.0.1`, using a new temporary SQLite database, `AGENT_AGENT_ENABLED=false`, and `AGENT_PROVIDER_MODE=disabled`.

| Check | Result |
| --- | --- |
| Local Auth health | HTTP 200, GoTrue v2.195.0 |
| Signup and password sign-in, users A and B | HTTP 200 for each operation |
| Auth `/user` token verification | HTTP 200 for A and B; returned IDs matched the created users |
| Missing and invalid Agent bearer tokens | HTTP 401 for each |
| A creates, lists, and gets a session | HTTP 201, 200, and 200 |
| B lists A's sessions and gets A's session | HTTP 200 with zero items; HTTP 404 |
| Planning while Agent is disabled | HTTP 409 `agent_disabled`; session remained with zero turns |
| Confirmation of a nonexistent proposal | HTTP 404; no business write performed |
| Provider and inference state | Provider `disabled`; inference unavailable |
| Cleanup | Both Auth sessions logged out (HTTP 204); both exact test users deleted (HTTP 200); Agent process stopped and temporary directory removed |
| Credential checks | No test credential values or JWT-like value in the evidence; temporary SQLite scan found no credential values |
| Frozen application inputs | SHA-256 inventory matched before and after |

The actual sanitized 29-check result, including opaque Auth user IDs and the session ID, is in [P1-04-RealAuthSmoke-20261010-013323.json](evidence/P1-04-RealAuthSmoke-20261010-013323.json). Its SHA-256 is `1846cb701837e51ad0a71aec5882b07aa717756124748e37eca9194ab9658142`. The helper [real_auth_smoke.py](../../deploy/acceptance/real_auth_smoke.py) has SHA-256 `a2fbfdc785f4d96e3ef428e46ec2464fa0d590ad89c084b7a0811f2253dacf87`.

Before the live run, `py_compile` and two helper-only regression checks passed: an injected `failure_code` forces overall FAIL even when prior checks and cleanup are green, and a local HTTP 302 does not forward the bearer token to the redirect target. These checks exercise helper behavior; they are not real Auth evidence. The 29-check JSON above is the real Auth and Agent HTTP run.

An Auth-issued expired token was not available without changing Auth settings or waiting for a token to expire, so the evidence records `expired_token.status` as `NOT_TESTED`. The existing [`test_untrusted_or_ineligible_user_claims_are_rejected`](../../tests/test_auth_verifier.py) unit test exercises an expired `exp` claim using a test token with an untrusted signature; it does not count as a real Auth expired-token test. The earlier seed account's HTTP 500 with a NULL `confirmation_token` remains a historical upstream issue and was not repaired; this run used newly created test users. The helper's child process sends stdout and stderr to `DEVNULL`; no runtime log scan is claimed. Secrets stay in process memory, and the evidence contains only response statuses, safe error codes, UUIDs, boolean checks, and source digests.

To repeat the test, keep the local Supabase services already running and run this command from the Agent checkout. The helper reads local CLI status, requires a loopback HTTP API URL, and does not start, stop, reset, or reconfigure Supabase.

```powershell
& 'D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe' `
  'D:\project\Android\shared-ledger-agent\agent\deploy\acceptance\real_auth_smoke.py' `
  --supabase-workdir 'D:\project\Android\shared-ledger'
```

Each run creates uniquely named `example.test` users and deletes only the returned IDs through the local Auth admin API in `finally`. It uses a temporary SQLite path and ephemeral loopback port; it does not perform ledger writes or enable Agent/provider execution. The helper is [real_auth_smoke.py](../../deploy/acceptance/real_auth_smoke.py).
