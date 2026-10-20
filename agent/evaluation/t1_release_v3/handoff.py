"""Assemble the two handoff packages for the release-v3 preparation.

1. ``independent-near-pair-review`` -- the complete 5,429-pair analysis plus the
   exact procedure by which an independent reviewer re-issues it in the
   ``root_agent`` role.  The analysis was produced by this session, so it is
   labelled ``assistant_technical_review`` and the collection gate does not pass
   on it.  Nothing in this package presents it as an independent adjudication.

2. ``human-receipt`` -- the 34-row train-only packet and the pending receipt,
   ready for a human to review and sign.  Nothing in this package can sign it.

Both packages state plainly that ``human_reviewed`` and ``training_eligible``
are still false.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.handoff
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from . import hashing, packet, profile

REVIEW_HANDOFF = "handoff"
NEAR_DIR = "independent-near-pair-review"
HUMAN_DIR = "human-receipt"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _sanitised_dispositions(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop free-text evidence that could name sealed rows; keep the category.

    A reviewer re-derives the category from the recomputed state and prompt
    hashes already bound in each disposition, so the descriptive text is not
    needed and would only spread sealed-adjacent identifiers.
    """
    clean: dict[str, Any] = {}
    for key, item in raw.items():
        clean[key] = {
            "decision": item["decision"],
            "review_kind": item["review_kind"],
            "reviewer_id": item["reviewer_id"],
            "category": item["category"],
            "left_full_state_signature_sha256": item["left_full_state_signature_sha256"],
            "right_full_state_signature_sha256": item["right_full_state_signature_sha256"],
            "left_prompt_sha256": item["left_prompt_sha256"],
            "right_prompt_sha256": item["right_prompt_sha256"],
        }
    return clean


def build_near_pair_handoff() -> dict[str, Any]:
    review = json.loads(
        (profile.REVIEW_ROOT / "near-pair-review-v3.json").read_text(encoding="utf-8")
    )
    raw = json.loads(
        (profile.REVIEW_ROOT / "near-pair-dispositions-v3.json").read_text(encoding="utf-8")
    )
    target = profile.REVIEW_ROOT / REVIEW_HANDOFF / NEAR_DIR
    target.mkdir(parents=True, exist_ok=True)

    clean = _sanitised_dispositions(raw)
    dispositions_path = target / "near-pair-dispositions-v3.json"
    _write(dispositions_path,
           json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _copy(profile.REVIEW_ROOT / "near-pair-review-v3.json",
          target / "near-pair-review-v3.json")

    status = {
        "package": "independent-near-pair-review",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "findings_total": review["findings_total"],
        "categories": review["category_counts"],
        "original_review_kind": "assistant_technical_review",
        "original_reviewer_id": "/assistant:t1-release-v3",
        "accepted_by_gate": "root_agent",
        "collection_gate_currently_passed": False,
        "gate_reason": "the analysis is a same-session technical review, not a root_agent adjudication",
        "dispositions_sha256": hashing.sha256(clean),
        "dispositions_file": dispositions_path.name,
        "human_reviewed": False,
        "training_eligible": False,
    }
    _write(target / "STATUS.json",
           json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write(target / "README.md", _near_pair_readme(status))
    _write(target / "reissue-dispositions.py", _REISSUE_SCRIPT)
    return status


def build_human_receipt_handoff() -> dict[str, Any]:
    source = profile.REVIEW_ROOT / "human-review-v3"
    target = profile.REVIEW_ROOT / REVIEW_HANDOFF / HUMAN_DIR
    target.mkdir(parents=True, exist_ok=True)
    for name in ("pending-human-review-receipt.json", "human-review-manifest.json",
                 "selection-hashes.json", "train-review-v3.md", "train-review-v3.html"):
        _copy(source / name, target / name)

    manifest = json.loads((source / "human-review-manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (source / "pending-human-review-receipt.json").read_text(encoding="utf-8")
    )
    status = {
        "package": "human-receipt",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "packet_rows": manifest["row_count"],
        "packet_sha256": manifest["packet_sha256"],
        "selection_sha256": manifest["selection_sha256"],
        "receipt_schema": packet.RECEIPT_SCHEMA,
        "receipt_status": receipt["status"],
        "human_reviewed": False,
        "training_eligible": False,
        "training_blockers": receipt["training_blockers"],
        "coverage": manifest["coverage"],
    }
    _write(target / "STATUS.json",
           json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write(target / "README.md", _human_readme(status))
    _write(target / "sign-receipt.py", _SIGN_SCRIPT)
    return status


def _near_pair_readme(status: dict[str, Any]) -> str:
    return f"""# Handoff: independent near-pair adjudication

**What this is.** Every cross-split near-pair finding of the release-v3
candidate ({status['findings_total']} pairs), already classified by the
dimension that actually distinguishes each pair, with both members' full-state
and normalized-prompt hashes bound in the disposition.

**What this is not.** The analysis was produced by the `assistant` session that
generated the rows, so it is recorded as `assistant_technical_review` with
reviewer `{status['original_reviewer_id']}`. It is **not** a `root_agent`
adjudication, and the collection gate does not pass on it. This package must not
be described as independent review, and the producing session must not re-run
the re-issue step itself.

**Categories observed.** {json.dumps(status['categories'], ensure_ascii=False)}

**What an independent reviewer does.**

1. Open `near-pair-dispositions-v3.json`. Each entry binds
   `left/right_full_state_signature_sha256` and `left/right_prompt_sha256` and
   carries a `category`. Recompute the category from the rebuilt rows (the build
   prints the same category counts), spot-check a sample, and confirm or correct
   them.
2. Re-issue the confirmed set in the root role. That is a deliberate source
   change, not a flag: edit
   `agent/evaluation/t1_release_v3/near_pairs.py` and set `REVIEW_KIND`,
   `REVIEWER_ID` and `PROVENANCE` to the reviewer's own identity, then rebuild
   into a fresh run root:

   ```
   set T1_RELEASE_V3_RUN_ROOT=D:\\AI\\runs\\shared-ledger\\t1-release-v3-<reviewer-date>
   agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.build_candidate
   ```

   The rebuild regenerates sealed rows in memory (sealed bodies are never
   written here and are not in this package), re-runs the schema, gold, replay,
   split and near-pair gates, and reports the collection outcome.
3. Do not reuse this run root or its receipt. A new preparation needs its own
   freeze and its own run root.

**Why the producing session cannot do step 2 for you.** Attempting to relabel
its own analysis as `root_agent` is self-approval; the harness blocked exactly
that during this preparation and the block stands.

**If `reissue-dispositions.py` is present**, it is a *dry-run* helper that
replays the recorded categories over the readable splits and prints how the gate
would see them. It cannot produce an accepted adjudication by itself.

Status: `human_reviewed=false`, `training_eligible=false`.
"""


def _human_readme(status: dict[str, Any]) -> str:
    return f"""# Handoff: genuine human review receipt

**What this is.** The 34-row train-only packet for release-v3
(`train-review-v3.md` / `.html`), its selection and packet hashes, and the
pending receipt template. Packet SHA-256 `{status['packet_sha256']}`;
selection SHA-256 `{status['selection_sha256']}`.

**What a human must do.**

1. Read the packet. It is required to contain every RBR fix
   (`rbr01-query-evidence` x3, `rbr03-natural-clarification`,
   `rbr04-aa-tail`), one row per boundary case, and a balanced sample of the
   operations. Coverage counts are in `STATUS.json`.
2. Check the business text, the amounts and the scope of each row against the
   stated user request. The RBR01 rows should show a complete query result
   (`page_complete`, no truncation) and cite `query_1`; the RBR03 rows should
   name candidates by returned facts and never by an internal reference; the
   RBR04 rows should show the two allocation columns with their own shares.
3. Sign `pending-human-review-receipt.json` by setting, on the same object:
   `status="approved"`, `decision="approved"`, `human_reviewed=true`,
   `reviewer_kind="human"`, a non-empty `reviewer_id`, and a non-empty
   `evidence` (a ticket, a meeting note, anything that identifies the review).
   Leave `packet_sha256`, `selection_sha256` and `selections` untouched — they
   bind the receipt to this packet and to every row hash.
4. Verify with `sign-receipt.py`, which re-applies the gate's checks.

**What signing does not grant.** `packet.validate_external_receipt` returns
`training_eligible: false` even for a correctly signed receipt. Admission still
requires the independent near-pair adjudication, the T1/root record of P2's
limited baseline acceptance, and explicit T2 authorization.

**What this work will not do.** It will not sign on your behalf, will not fill
in a reviewer identity, and will not treat an agent review as a human receipt.

Status: `human_reviewed=false`, `training_eligible=false`,
blockers `{json.dumps(status['training_blockers'], ensure_ascii=False)}`.
"""


_REISSUE_SCRIPT = '''"""Dry-run: replay the recorded near-pair categories over the readable splits.

This helper does NOT produce an accepted adjudication. The collection gate
accepts only a root_agent decision, and the producing session may not issue one
for its own data. Use it to see the category distribution and to sanity-check
that the recorded bindings still match the rows.

    agent/.venv/Scripts/python.exe reissue-dispositions.py --run-root <root>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# This script lives outside the repository, so the repository root is explicit.
REPO_ROOT = Path(os.environ.get("T1_AGENT_REPO", r"D:\\project\\Android\\shared-ledger-agent"))
sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release import checker  # noqa: E402
from agent.evaluation.t1_release_v3 import near_pairs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True,
                        help="the release-v3 run root containing candidate-v3/")
    args = parser.parse_args()
    rows = near_pairs.load_rows(Path(args.run_root) / "candidate-v3")
    findings = checker.check_collection(rows)["pair_findings"]
    result = near_pairs.adjudicate(rows, findings)
    print("readable-split findings:", len(findings))
    print("categories:", result["counts"])
    print("recorded reviewer:", near_pairs.REVIEW_KIND, near_pairs.REVIEWER_ID)
    print("NOTE: this is a technical review, not a root_agent adjudication.")
    print("The full three-split gate requires an independent rebuild, not this helper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


_SIGN_SCRIPT = '''"""Apply the receipt gate's checks to a signed receipt.

    agent/.venv/Scripts/python.exe sign-receipt.py --receipt pending-human-review-receipt.json

It prints the gate's verdict and never edits the receipt or any packet file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# This script lives outside the repository, so the repository root is explicit.
REPO_ROOT = Path(os.environ.get("T1_AGENT_REPO", r"D:\\project\\Android\\shared-ledger-agent"))
sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import packet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", default="pending-human-review-receipt.json")
    parser.add_argument("--manifest", default="human-review-manifest.json")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    receipt = json.loads((here / args.receipt).read_text(encoding="utf-8"))
    manifest = json.loads((here / args.manifest).read_text(encoding="utf-8"))
    result = packet.validate_external_receipt(manifest, receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["human_reviewed"]:
        print("Receipt is not a signed human review yet.")
    else:
        print("Receipt is a signed human review. training_eligible is still false:")
        print("the remaining blockers are listed above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main(argv: list[str] | None = None) -> int:
    near = build_near_pair_handoff()
    human = build_human_receipt_handoff()
    print(f"near-pair package: {near['findings_total']} findings, "
          f"categories {near['categories']}, original review {near['original_review_kind']}")
    print(f"human-receipt package: {human['packet_rows']} rows, packet "
          f"{human['packet_sha256'][:16]}, receipt {human['receipt_status']}")
    print(f"wrote {profile.REVIEW_ROOT / REVIEW_HANDOFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
