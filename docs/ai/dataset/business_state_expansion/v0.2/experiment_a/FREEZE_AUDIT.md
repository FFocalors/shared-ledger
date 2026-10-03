# Training v0.2 Experiment A Freeze Audit

Frozen at `2026-10-01T12:35:01+08:00` (Asia/Shanghai). External experiment version: `0.2 Experiment A`; Dataset Schema version stays `0.1` as required by the frozen schema.

The current user request explicitly accepted the independent final review and authorized `approved`/`frozen` governance. The record attributes the independent audit to Codex and the freeze acceptance to the maintainer; it does not claim a human reviewer identity.

- 16/16 Scenarios: `SILVER`, `business_validated=true`, lifecycle `approved`.
- 16/16 Samples: `SILVER`, `ground_truth_locked=true`, `surface_form_reviewed=true`, lifecycle `approved`, policy `active`.
- All 16 Samples remain `split=unassigned`. `training_eligible=true` means governance-ready; export remains blocked until split assignment. No export or training occurred.
- Output distribution: 7 clarification, 5 proposal, 3 tool_call, 1 answer. Six reviewed contrast warnings are retained.
- Expected facts: 102/102 visible sources, 0 missing. Frozen v0.1 source hashes: 30/30 unchanged.
- Exact non-governance deep equality: all 16 Scenarios and all 16 Samples match their pre-freeze business content. The policy's principles are unchanged; only freeze metadata was appended.

Pre- and post-governance hashes and the equality proof are in `freeze_report.json`. Final manifest and artifact hashes are in `freeze_hashes.json`. Builder/finalizer overwrite guards were added; rerunning either against this frozen directory must fail without changing files.

Guard recovery: an initial smoke test exposed a missing builder-main guard invocation. Regenerated records matched the recorded pre-governance hashes exactly, and the authorized freeze recovery restored governance with the original timestamp/provenance. Final builder/finalizer negative tests both refused writes (nonzero exit); all 10 checked manifest/core artifact hashes remained unchanged. See `freeze_report.json`.
