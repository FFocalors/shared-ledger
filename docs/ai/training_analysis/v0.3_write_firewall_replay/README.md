# v0.3 Model-Origin Write Firewall Replay

This directory contains the preregistered offline replay, isolated conformance controls, and result artifacts for the v0.3 write-origin boundary experiment. It uses 24 saved validation outputs each from v1 cp33, A cp36, and C cp33 (72 total). The harness uses only saved model outputs and frozen serialized runtime `enabled_tools`; Expected/GT never enters common or arm decisions.

Arm 0 records a hypothetical model-origin write capability after common public checks; Arm 1 additionally denies every model-origin write. Both arms use the same strict JSON parser, frozen model-output schema, intent/tool Scope/catalog mapping, visible runtime tool allowlist, and no-op destination. A separate simulator-only trusted-UI/executor-origin control path checks that exact trusted confirmation and current actor/activity/conversation/entity/payload/version binding can reach the no-op recorder in either arm. Forged or mismatched confirmation and D4 remain rejected. No TTL is invented.

The conformance controls are under [`controls_non_training`](controls_non_training/control_vectors.json), outside every dataset/training directory, and marked `non_training` / `no_export`. They are not Samples. No model is imported, no inference or training runs, and the harness contains no network, RPC, or database client. Every action is recorded as a decision; the executor invocation count must be zero.

Run the small offline checks and replay from the repository root:

```powershell
python -m unittest scripts.ai_write_firewall_replay.test_replay -v
python scripts/ai_write_firewall_replay/replay.py
```

The immutable saved evaluator fields are reported separately as raw model quality; a denied or common-rejected output is never relabeled correct. The 72-row common-rejection count and the Arm0-vs-Arm1 incremental interception count are separate. If common public checks reject every observed write in both arms, the observed incremental count is zero even if conformance controls validate the origin gate mechanism.

See [`preregistration.json`](preregistration.json) for the decision rules and [`replay_outputs/final_report.md`](replay_outputs/final_report.md) and JSON/manifest files for results, source hashes, and integrity checks. No production Gateway is claimed or implemented by this analysis.
