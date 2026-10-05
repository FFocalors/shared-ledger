# v0.3 AI Gateway Boundary Prototype

This is a small Python-only boundary prototype. It reuses the frozen v0.1.2 model-output schema, Tool catalog, Intent catalog, Scope decisions, and pure evaluator validation helpers. It does not alter those sources and does not call a model, network, database, Android UI, or financial RPC.

## Prototype layout

- `scripts/ai_gateway_boundary_prototype/gateway.py` — session, parsing, Scope/schema checks, canonical proposal registry, confirmation capability, revalidation, no-op adapter, and structured audit.
- `scripts/ai_gateway_boundary_prototype/test_gateway.py` — focused unit and boundary tests.
- `scripts/ai_gateway_boundary_prototype/run_controls.py` — integration replay using the prior 15 non-training controls as setup/input fixtures.
- `control_replay.json`, `source_hashes.json`, `audit_example.json`, and `artifact_manifest.json` — replay outcomes and integrity record.

Run with `python -m unittest scripts.ai_gateway_boundary_prototype.test_gateway -v` and `python scripts.ai_gateway_boundary_prototype/run_controls.py` from the repository root.

## Trust boundary

The public model path accepts only raw JSON output and a `SessionHandle` already registered by this Gateway against its server-side session registry. It does not accept caller-supplied origin, confirmation, current binding, or enabled-tool claims. Strict parsing, duplicate-key rejection, the frozen model-output schema, frozen Intent/Tool/Scope checks, and the snapshot's server-owned enabled-tool set run before routing. Schema-valid model-origin reads use the fake no-op adapter. Every model-origin write `tool_call` is denied.

A model `proposal` can only be staged when it passes the same frozen schema and write-scope checks and exactly matches the FakeAuthority's separately seeded server-owned canonical plan after typed entity resolution. The Gateway freezes the canonical operation and current actor/activity/conversation/version binding in its own registry. It rejects unknown IDs, `result_id`-typed IDs, wrong entity roles, and entities from another Activity; UUID shape does not establish entity authority. Changes to model or UI display objects cannot change the stored command.

The UI display path shows the server-owned canonical command. Its confirmation callback accepts only the opaque proposal handle and returns an identity-registered, single-use `ConfirmationCapability`. The dispatch path requires the original Gateway session handle, atomically consumes the capability under a lock before any adapter invocation, re-reads current state and the canonical plan, and rechecks the full binding, operation digest, frozen Scope/allowlist, and typed entity ownership. A state/version/binding/plan change fails closed; capabilities cannot cross Gateway or session boundaries. D4 `update_expense` always remains non-executable. No TTL is invented.

The old 15 controls are treated as non-training test vectors. Their `trusted`, `current_binding`, `simulator_confirmation`, digest, and command fields are not accepted by a public API as authority declarations. The integration runner seeds its isolated FakeAuthority from fixture scenario data; malformed legacy confirmation objects are used only as hostile payloads. Stale version, actor/activity/conversation change, and post-confirmation payload/tool/intent mutation cases issue a genuine fake-UI capability first, then change the server-side snapshot or plan and verify dispatch rejection. Wrong entity type/scope and missing session bindings reject during setup/staging. Positive confirmation is generated through the prototype's internal `FakeTrustedUI` callback.

## Audit and test boundary

Audit events use sequence, event, decision, reason, source, intent/tool, operation digest, and binding digest fields. They never store raw model output, session IDs, opaque handles, confirmation capabilities, or bearer secrets. `audit_example.json` contains one synthetic successful no-op flow.

`FakeAuthority` and `FakeNoopAdapter` are deterministic local test doubles. The no-op adapter captures two accepted positive write cases but invokes zero RPCs. The prototype is designed to show that untrusted JSON/model payloads cannot mint internal capabilities. It is not a security boundary against arbitrary malicious Python code running in the same process: Python objects and memory are inspectable there. Production authentication, Android callback plumbing, cryptographic tokens, idempotency, transaction/CAS enforcement, and complete financial business validation remain unimplemented.
