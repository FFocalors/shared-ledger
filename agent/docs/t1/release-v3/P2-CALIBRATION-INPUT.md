# P2 baseline calibration: T1 input record

**What this is.** A factual cross-reference from the T1 preparation to P2's own
calibration record. It records what P2 accepted, with P2's stated limits, and how
T1 treats that result. It is not a T1 admission record and it changes no gate.

## The P2 record

| Field | Value |
|---|---|
| Path | `agent/docs/p2/P2_BASELINE_CALIBRATION_R1.md` |
| Status label | `ACCEPTED_LIMITED_P2_READONLY_ENGINEERING_BASELINE` |
| Date | 2026-10-19 |
| Source/config pin | `362e66ad04491be4f711c8db076f5bb0736904b5d6e9962a9f13ba82e6e8a848` (49 components, 0 mismatches against source `3fcb2fd`) |
| Suite | 745 passed + 1 xfailed, reproduced twice |
| Reproducibility precondition | `agent/tests` invoked once over the whole directory, with `P2_V3_STORE_TEST_ROOT` and `P2_STORE_TEST_ROOT` freshly created per run; reusing a directory produces spurious failures unrelated to the code |

## What P2 explicitly does not claim

* No independent review was performed. P2's own signing section says so, and states
  that using the record as an admission basis requires a root record of that review.
* It is not a model-quality result (`INSUFFICIENT_SAMPLE` remains).
* It is not a cloud deployment result; the evidence is a local, isolated stack.

## How T1 uses it

T1 treats the P2 record as an **input that exists and is documented**, not as an
admission and not as a substitute for any T1 gate:

* the T1 candidate binds the frozen offline protocol v1.1.0 typed query evidence,
  not P2's runtime; P2's `query_zero_classification` remains an alignment target
  and is not a protocol field (P2 recorded the same ruling in
  `agent/docs/p2/P2_V3_PROFILE_STATUS.md`);
* `training_eligible` stays `false`, `human_reviewed` stays `false`;
* if the P2 record is later used as a gate input, the root record of its
  independent review is still required, and that is not something this
  preparation can produce.

## Checklist position

The goal's item "P2 baseline calibration 完成" is satisfied **on P2's side and
within P2's stated limits**: the record exists, is dated, is pinned, is
reproducible under a stated precondition, and lists its known limitations. What
remains is the root record of independent review if it is to be relied on for
admission — a step that needs a reviewer other than the producers.
