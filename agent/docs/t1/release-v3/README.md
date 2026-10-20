# T1 release-v3: explicit conversion to the frozen offline v1.1 profile

**Frozen training version (2026-10-20, owner instruction).** The 417-row candidate in
`D:\AI\runs\shared-ledger\t1-release-v3-20261020\candidate-v3` is designated as the training
artifact and bound by its own file hashes in
`review/TRAINING-FREEZE-v3.json` (train 143 rows / `8cd3451d…`, validation 137 rows /
`6ed20231…`; sealed 137 rows generated but not written). This designation is not an
admission: `training_eligible` is not asserted. The authoritative limitation list is
[KNOWN-LIMITATIONS.md](KNOWN-LIMITATIONS.md).

**Status (2026-10-19): the release-v3 candidate is built, validated and gated as far as it
can be without root adjudication; it is not an admitted dataset.** 417 rows (143 train /
137 validation / 137 sealed) carry all four RBR fixes, including base-currency AA tail
coverage in both allocation columns. `training_eligible` is still `false` and
`human_reviewed` is still `false`: the near-pair findings, the human receipt, T2
authorization and the T1 re-authorization of P2's limited baseline acceptance are external
gates.

The frozen v2 candidate and every v2 receipt are byte-identical to before: all three v2
payload hashes still match, and the v2 release suite still passes unchanged.

## Why a conversion at all

The dataset applicability policy
(`dataset_contracts/t1-protocol-v1.1.0/applicability-policy.json`) files
`legacy-t1-release-v2` as a **conversion_candidate**: not directly trainable, requiring
explicit conversion, a new source freeze, a new split, and replay plus human review. The
393-row candidate was generated under vendor v1 semantics, which is why three of its answers
had no citable source for an empty query result, why 33 of 34 reviewed contexts carried a
training-only "already read and consumed" hint, why clarification asked for an internal
reference, and why the packet's equal shares were all whole cents.

## The four RBR items

| Item | What changed | Rows |
|---|---|---|
| **RBR01** empty result has no citable source | Each no-match answer is the frozen trusted renderer's output and cites `query_1` through the frozen v1.1 typed query result | 3 |
| **RBR02** manual "already read and consumed" hint | Every model-visible input is byte-equal to the original user request | 414 (of 417; the three `actor_not_authorized` rows have no read step) |
| **RBR03** bare internal `expense_ref` in clarification | Candidates are named by returned facts and the follow-up selects on them | 56 |
| **RBR04** AA minor-unit tail coverage | Twelve original-currency cases **plus twelve base-currency cases**, each with a checked allocation and exact conservation in its own column | 24 |

### RBR01: how the empty result is bound

The frozen offline protocol v1.1.0 is the only **ratified** definition of typed query
evidence; the P2 v3 profile is an unratified candidate and is not a baseline. The two carry
the same semantics for the part that matters, so this work binds to the frozen port and
records the P2 runtime's `query_zero_classification` as an alignment target only -- adopting
it into the protocol would be a new field needing its own freeze.

Each converted no-match row binds all four axes RBR01 demands, using only fields of the
frozen v1.1 port; none is authored by the generator:

| RBR01 axis | Bound by |
|---|---|
| completeness, including pagination/truncation | `page.complete`, `page.expected_total`, `page.pages_seen`, `page.has_more`, `page.truncated`, `page.range_contiguous`, `page.stable_total_verified`, `page.source_version_fenced`, `page.unique_items_verified`, plus the private page receipts and their cursor chain |
| filters actually applied | `operation`, `criteria`, `normalized_criteria`, `backend_criteria`, `post_filter`, `returned_count`, `matched_count` |
| scope | `criteria.activity_ref`, the private `scope_activity_id`, and the page scope fingerprint |
| result/schema version | `schema_version`, `context_version`, `source_version`, `source`, `query_digest`, `body_digest`, profile tuple |

An empty list still proves nothing: the envelope's `rbr01_query_evidence` definition makes
`matched_count` a `const: 0`, forces `page_complete`, `range_contiguous`,
`stable_total_verified`, `source_version_fenced` and `unique_items_verified` to `true`,
`has_more`/`truncated` to `false`, and the source to `synthetic_simulation`. No row can claim
"no match" while reporting partial or unverified coverage.

**Two of the three rows are complete backend zeros; one is a post-filter zero.** The
expenses row read five real rows and then emptied them with a title filter that appeared
nowhere in the query. Under v1.1 the filter is a typed post-filter stage, so the converted
row reports `returned_count: 5`, `matched_count: 0` and `zero_class: post_filter_zero`, while
the activity and debt rows report `returned_count: 0` and `backend_zero`. The two cases
cannot be confused, which is what RBR01 asked for.

The tool observation's `request` is left exactly as the frozen simulator consumed it. The
typed post-filter lives on the query observation, not on the backend request, and the frozen
v1 simulator rejects the v1.1-only expense field -- a conversion that rewrote the backend
request would break deterministic replay.

### RBR03: clarify by returned facts

```
请求标题=“星栈车票费”；候选(ref|currency|participant_refs|financial_locked)=expense_1|CNY|…   ← before
有 2 笔同名费用：“星栈车票费”（日期 2026-10-17，金额 123.00 CNY，参与人 participant_2）；…     ← after
expense_ref=expense_1。                                  ← before
改日期 2026-10-17、金额 123.00 CNY 的那一笔。            ← after
```

56 rows, two to fifteen candidates each; every one is checked to be uniquely selectable by
date and amount, and to expose no internal reference. The proposal, its `expense_ref`, the
amounts and the operation state are unchanged. The v2 gold parser hard-requires
`expense_ref=` in the follow-up, so these rows carry their own gold check
(`rbr03.validate_natural_clarification`) instead.

### RBR04: coverage in both allocation columns

The default create amount is `25 * participant_count`, so **every** default equal-split
family is whole-cent by construction; the flagged packet rows are 25.00/1, 250.00/10 and
50.00/2. The review called this a coverage gap rather than an allocation defect, so the fix
adds cases and changes no existing row and no allocation rule.

**The two columns are not an either/or** (verified against the backend source, not inferred):

| | `splits.amount` | `splits.base_amount` |
|---|---|---|
| currency | original | activity base |
| quantum | **0.0001** (`p_original_amount * 10000`) | **0.1** (`base_amount * 10`) |
| rule | `trunc(total/n)`; first `|remainder|` in `participant_order, id` move by one unit | same rule |
| source | `private.replace_expense_children` (AA branch) | `private.redistribute_aa_split_base_amounts` |

The base rule is the one that is persisted. Creation writes the base tail to the **last**
participant, but every create, update, delete, restore and the repair path then call the fair
redistribution, which overwrites the row set with the **first-N** shape. The training data
stores the first-N result; the converter rejects a row set that is the superseded last-person
shape, and the audit records the first-N shares. `payments.base_amount` keeps the
last-participant delta, because the fair-allocation migration redistributes splits only.

The generator keeps its `0.0001` original-currency allocation; the base column is added
alongside it, not used in place of it.

**Original-currency coverage (12 cases).** Each reuses an existing in-split state family, so
family counts and state signatures are untouched:

| Case | Amount | Participants | First / last share |
|---|---|---|---|
| `aa-tail` | 150.01 | 6 | 25.0017 / 25.0016 |
| `aa-tail` | 200.01 | 8 | 25.0013 / 25.0012 |
| `aa-tail` | 300.01 | 12 | 25.0009 / 25.0008 |
| `small-multi` | 0.05 | 6 | 0.0084 / 0.0083 |

**Base-currency coverage (12 cases).** These target `expense_1` of a `read.expenses` row, so
both columns are factual ledger state rather than a proposal. They add four independent
`read.expenses` families per split, which is why that operation reports 24 rather than 20:

| Case | Original / participants | Original column | Base column | Base total |
|---|---|---|---|---|
| `base-100-3` | 100.00 / 3 | 33.3334 / 33.3333 / 33.3333 | **33.4 / 33.3 / 33.3** | 100.0 |
| `base-10-6` | 10.00 / 6 | 1.6667 x4 / 1.6666 x2 | **1.7 x4 / 1.6 x2** | 10.0 |
| `orig-tail-base-even` | 150.01 / 6 | 25.0017 x4 / 25.0016 x2 | **25.0 x6** (even) | 150.0 |
| `fx-both-tail` | 100.00 EUR / 3, fx 7.10 | 33.3334 / 33.3333 / 33.3333 | **236.7 / 236.7 / 236.6** | 710.0 |

The first two are B01's own examples. The third is the case where the original column tails
and the base column does not; the fourth is a foreign-currency expense where both columns
tail and are verified separately. Every case is checked for exact conservation in both
columns at its own quantum.

## What was produced

Run root: `D:\AI\runs\shared-ledger\t1-release-v3-20261020\` (the 2026-10-19 attempt is
retained as history and is never read back; each preparation gets its own run root so no
earlier receipt can be reused).

| Artifact | Note |
|---|---|
| `baseline-snapshot/` | 91 pinned files: the 72-file v1 baseline (re-verified against the frozen v2 snapshot manifest) plus the 19 files of the frozen offline v1.1.0 package and its exported schemas, each proved against the v1.1 export manifest before it is copied. Manifest self-hash `12f4d6b5b81a7dda49f9efcbb2182b7f03cb09ebaf988327ed45b291d82ca6d5`. |
| `review/source-manifest.json` | The fresh source freeze: 27 files, git heads, the snapshot and v1.1 manifest bindings, and its own self-hash. |
| `candidate-v3/train.jsonl`, `validation.jsonl` | 143 and 137 rows. Sealed is generated and validated but **not written**. |
| `review/candidate-report.json` | Row counts, payload hashes, which RBR item applied to how many rows, the AA quantum ruling, the twelve base-column cases, the validation and replay results, the collection gate, and the pending external gates. |
| `review/near-pair-review-v3.json`, `near-pair-dispositions-v3.json` | The near-pair analysis over **all three splits**, every pair classified by its distinguishing dimension. |
| `review/human-review-v3/` | The new 34-row train-only packet, its selection hashes, and the **pending** receipt. |
| `review/handoff/independent-near-pair-review/` | Handoff package 1: the sanitised 5,429-pair analysis, its status, the role caveat, and a dry-run helper. Explicitly labelled `assistant_technical_review`, not a `root_agent` adjudication. |
| `review/handoff/human-receipt/` | Handoff package 2: the packet, its hashes, the pending receipt and a signing checker, ready for a human signature. |
| `review/handoff/HANDOFF-INDEX.md` | The three open decisions, each with its owner and the one command that closes it. |
| `conversion/*` | The three slice artefacts (RBR01, RBR03, RBR04). |

Repository side, all new files:

| Path | Role |
|---|---|
| `agent/evaluation/t1_release_v3/profile.py` | Version/path/switch constants; the frozen v2 identities are assert-only. |
| `agent/evaluation/t1_release_v3/snapshot.py` | Builds and re-verifies the 91-file snapshot. |
| `agent/evaluation/t1_release_v3/schema.py` | Derives the release-v3 envelope from the frozen v2 envelope by an explicit, reviewable transform and embeds the frozen v1.1 schemas. |
| `agent/evaluation/t1_release_v3/runtime.py` | Pinned module loader and the release-v3 validator. |
| `agent/evaluation/t1_release_v3/v11_evidence.py` | Issues the typed query evidence through the frozen v1.1 ports. Nothing is hand-authored. |
| `agent/evaluation/t1_release_v3/convert.py` | The row conversion, for no-match reads and for carry-over rows. |
| `agent/evaluation/t1_release_v3/rbr03.py`, `rbr04.py` | The RBR03 gold check, the RBR04 original-currency catalogue, the AA quantum ruling, and the base-column case catalogue. |
| `agent/evaluation/t1_release_v3/base_allocation.py` | Both AA allocation rules at their own quanta, plus the last-person detector. |
| `agent/evaluation/t1_release_v3/near_pairs.py` | The near-pair analysis. Its reviewer label is `assistant_technical_review`, deliberately not `root_agent`. |
| `agent/evaluation/t1_release_v3/hashing.py` | Canonical JSON and SHA-256, byte-compatible with the v2 tooling. |
| `agent/evaluation/t1_release_v3/bridge.py`, `generate_v2_rows.py` | Run the frozen v2 generator in an isolated process. |
| `agent/evaluation/t1_release_v3/freeze.py` | The fresh source freeze. |
| `agent/evaluation/t1_release_v3/build_candidate.py` | Builds, validates, replays, gates and writes the candidate. |
| `agent/evaluation/t1_release_v3/packet.py` | The new train-only packet and the human-receipt gate. |
| `agent/evaluation/t1_release_v3/handoff.py` | Assembles the two handoff packages; the near-pair copy is sanitised of free text so it carries no sealed identifiers. |
| `agent/evaluation/t1_release_v3/slice_rbr01.py`, `slice_rbr03.py`, `slice_rbr04.py` | The three slices. |
| `agent/dataset_contracts/t1-release-v3/dataset-envelope.schema.json` | The generated envelope schema. |

Run the whole thing with:

```
agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.build_candidate
agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.packet
agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.handoff
```

## Verification performed

* The v2 generator still reproduces the frozen rows byte-for-byte. After **both** generator
  changes the whole readable candidate was regenerated and compared row by row: 127 train and
  121 validation builder rows plus 8 + 8 boundary rows hash identically to the frozen
  `train.jsonl` and `validation.jsonl` -- exactly the frozen 135 / 129 split counts, zero
  mismatches. `builder.py` is the only v2 source file touched, and all three frozen v2
  payloads still match.
* All 417 candidate rows validate against the release-v3 envelope, whose model context and
  decision ports are the **frozen v1.1** schemas, not the vendor v1 ones.
* Every one of the 414 tool observations in the written splits still re-derives
  byte-for-byte from its own fixture through the frozen simulator.
* Each no-match row's evidence is re-proved by the frozen v1.1 harness: `bind_trusted_query`
  issues it, `validate_context_bindings` re-derives currentness, page continuity, scope and
  digest agreement, and `render_query_answer` produces the answer text. The converter rejects
  any run where the renderer does not return a grounded, query-citing answer.
* Each RBR04 original-currency case is checked for exact conservation and a real tail from its
  own proposal. Each base-currency case is checked against the exact two-column share list it
  declares, including the original-tails/base-even case and the foreign-currency case where
  both columns tail, and the row set is rejected if it is the superseded last-person shape.
* The collection gate reports zero blocking issues and every operation at or above its
  twenty-family floor (eighteen at exactly 20; `read.expenses` at 24 because of the four base
  families per split), plus 5,429 near-pair findings, all classified, that need root
  adjudication.
* `agent/.venv/Scripts/python.exe -m pytest agent/evaluation/t1_release_v3/tests -q` -- 40 passed.
* `agent/.venv/Scripts/python.exe -m pytest agent/evaluation/t1_release/tests -q` -- 122 passed,
  unchanged.
* The packet's selection is deterministic (rebuilding it twice yields the same packet hash)
  and the receipt gate refuses a pending receipt that claims a review, an "approved" receipt
  without a named human and evidence, and even a properly signed receipt as a route to
  `training_eligible`.

## What remains, and what this work cannot do

1. **Root adjudication of this version's near-pair findings** (5,429 of them). The analysis
   exists and covers all three splits, but it is labelled `assistant_technical_review`
   because it was produced by the session that generated the rows. The collection gate accepts
   only a `root_agent` adjudication, so it does not pass. Handoff package
   `review/handoff/independent-near-pair-review/` contains the sanitised dispositions, the
   role caveat and the exact re-issue procedure, so an independent reviewer can confirm and
   re-issue rather than redo.
2. **A genuine human receipt for the new packet.** Handoff package
   `review/handoff/human-receipt/` contains the packet, its hashes, the pending receipt and
   `sign-receipt.py`. The signature does not exist. `packet.validate_external_receipt` accepts
   only a receipt naming a human reviewer with evidence, and even then reports
   `training_eligible: false`.
3. **P2 baseline calibration and an explicit T2 authorization.** P2 has recorded
   `ACCEPTED_LIMITED_P2_READONLY_ENGINEERING_BASELINE` (2026-10-19) for its read-only
   engineering baseline, and states plainly that no independent review was performed and that
   it is not a model-quality or cloud result. That record, its pin, its reproducibility
   precondition and its limits are transcribed in
   [P2 calibration input](P2-CALIBRATION-INPUT.md); using it as an admission input still
   needs the root record of that independent review. The T2 authorization is the user's
   decision.
4. **Writing sealed**, which happens last under its own one-shot receipt once the gates above
   close.

Items 1--3 are outside what this work can produce: one needs an independent reviewer signature,
one needs a human signature, and one is the user's authorization. This work does not and cannot
make `training_eligible` true on its own.

## What this does not claim

This is an offline, synthetic conversion. It is not T1 formal data admission, not a
model-quality or Student evaluation result, not live backend acceptance, and not a human
review. `human_reviewed` stays `false`, `human_review_pending` stays `true`, real Agent CAP
coverage stays `0/17`, and `training_eligible` stays `false`. The frozen v2 candidate, its
packet, its receipts and the frozen protocol v1.1.0 are untouched, and no sealed content was
read.
