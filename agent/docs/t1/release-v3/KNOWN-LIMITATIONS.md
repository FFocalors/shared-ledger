# T1 release-v3 — known limitations

Frozen training version: `D:\AI\runs\shared-ledger\t1-release-v3-20261020\candidate-v3`
(417 rows: train 143, validation 137, sealed 137 — sealed not written).
This page records what the freeze does **not** establish. It is the authoritative
limitation list for that artifact.

## 1. The 48 blockers were a false positive and will not be repaired

The independent audit reported 48 blocking issues, all `invalid_boundary_gold` with
`BaselineError: untrusted preloaded module blocks pinned baseline import: agent.app`.
That is the v2 runtime's guard rejecting a **preloaded live-repo module**, i.e. an
import-order artefact of the auditing process. A clean subprocess (no live `agent.app`,
no preloaded v1.1 package, imports matching `build_candidate.py`) reports **0**
`invalid_boundary_gold` blockers and **boundary gold passes**. The 48 blockers are
withdrawn; no data or gate code was changed to "fix" them.
Evidence: `review/verification/clean-gate-report.md`, `clean-gate-report.json`.

## 2. A reporting defect was found, and it invalidates an earlier claim

`check_collection` reports blockers under `blocking_issues`, not `blockers`. The earlier
preparation record read `gate.get("blockers")`, which never exists, so it printed
`blockers: 0` unconditionally. That statement is withdrawn. The field name was corrected
in commit `8302bb5`; the frozen candidate bytes are unaffected.

## 3. The source freeze is stale, and was incomplete when written

* `source-manifest.json` (`4c8b1a7f…`, 26 files) no longer matches the tree:
  `build_candidate.py` and `freeze.py` changed in `8302bb5`. The candidate files are bound
  directly by their own SHA-256 above, so the frozen bytes are unaffected; the *tooling*
  is newer than the freeze.
* That manifest also omitted four modules that materially determine the artifact —
  `base_allocation.py`, `near_pairs.py`, `packet.py`, `handoff.py`. Fixed in `8302bb5` for
  future preparations; this frozen artifact's manifest still omits them.

## 4. Sealed is not part of the artifact

Sealed (137 rows) is generated and validated in memory only. It is not written, not bound
by a file hash here, and no sealed semantic readback or sealed model evaluation occurred.
Writing it requires a one-shot receipt in a future cycle.

## 5. A clean-process gate run is partial

The verification loaded only the two splits written to disk (280 rows). The six remaining
`insufficient_independent_families` blockers in that run are sealed-family placeholders
(`actual: 0`) produced by the partial load, not data defects. The full three-split gate
needs one in-memory build run.

## 6. Near-pair review: source constants and persisted artifacts disagree

`near_pairs.py` now carries the independent reviewer's `root_agent` identity and
provenance. The run root's persisted `near-pair-review-v3.json` and
`near-pair-dispositions-v3.json` still hold the producer's
`assistant_technical_review` set (09:23). Applying the reviewer's dispositions in memory
resolved all readable near pairs (1,779 → 0); the persisted artifacts were not
regenerated. Regenerating them is the reviewer's rebuild, not the producer's.

## 7. Admission flags are not asserted

`training_eligible` is **not** asserted true. `human_reviewed=false`, the packet receipt
is `pending`, no T2 authorization is recorded, and P2's limited baseline acceptance has
not been independently reviewed. `collection_passed=false`. This freeze designates the
training artifact and binds its bytes; it is not an admission decision.

## 8. Scope of the dataset

Synthetic, offline, simulated replay only. Not a live backend, not model-quality, not
Student evaluation, not the 393-row v2 candidate: this artifact is 417 rows because 24
coverage rows were added (12 original-currency AA tails, 12 base-currency AA tails) at the
owner's instruction.

## 9. AA semantics are recorded, not re-derived here

`original_currency_column` allocates at a 0.0001 quantum; `base_currency_column` at a 0.1
quantum. The base column's persisted shape is first-N participants, not the creation-time
last-participant intermediate. These are recorded in the candidate report
(`aa_quantum_ruling`) and verified by the case list; they are backend facts transcribed
from source, not an independent re-derivation by this freeze.
