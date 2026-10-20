"""Version, path, and behaviour constants for the T1 release-v3 conversion.

Nothing here may silently change a v2 artefact.  ``V2`` values below are the
frozen v2 identities and are re-asserted, never rewritten.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- frozen v2 identities (assert-only, never written) -----------------------
V2_RUN_ROOT = Path(r"D:\AI\runs\shared-ledger\t1-release-v2-20261011")
V2_CANDIDATE_ROOT = V2_RUN_ROOT / "candidate-v2"
V2_SNAPSHOT_ROOT = V2_RUN_ROOT / "baseline-snapshot"
V2_SNAPSHOT_MANIFEST_SHA256 = (
    "711adfbd40a66d9c7b0aa1f32850e72e4f13fac08b370f051d4ae3791136989c"
)
V2_PAYLOAD_SHA256 = {
    "train": "be8795a68e9d739ecb72360d66b223accc428b735eab1d65cb2f6e71b6dc7247",
    "validation": "5e4c4faa0318ad8ceec79b5ac0f9e1aef679d5ad9caa8e55b767a13e0acfd903",
    "sealed": "1501d8931324fcba36d10e6c91c0f16f24dd2347497d7dd7c5eac0527f37f9db",
}
V2_ROW_COUNTS = {"train": 135, "validation": 129, "sealed": 129}
V2_RELEASE_VERSION = "t1-release-v2"
V2_GENERATOR_VERSION = "t1-synth-2.0.0"
V2_SEMANTIC_VERSION = "1.0.0"

# --- the frozen offline protocol v1.1.0 (the conversion target) --------------
V11_PROFILE = "t1-offline-canonical"
V11_API_VERSION = "1.0.0"
V11_SEMANTIC_VERSION = "1.1.0"
V11_OPERATIONS_VERSION = "1.1.0"
V11_TRAJECTORY_VERSION = "1.1.0"
V11_EXECUTION_KEY_VERSION = "1"
V11_QUERY_EVIDENCE_SCHEMA_VERSION = "1.1.0"
V11_MANIFEST_RELATIVE = Path("dataset_contracts/t1-protocol-v1.1.0/manifest.json")
V11_SCHEMA_DIR_RELATIVE = Path("dataset_contracts/t1-protocol-v1.1.0/schemas")
V11_PACKAGE_RELATIVE = Path("evaluation/t1_protocol_v1_1")

# --- this version ------------------------------------------------------------
RELEASE_VERSION = "t1-release-v3"
GENERATOR_VERSION = "t1-synth-3.0.0"
# Each preparation writes into its own run root so no earlier receipt can be
# reused.  The 2026-10-19 attempt is kept as history and is never read back.
RUN_ROOT = Path(
    os.environ.get(
        "T1_RELEASE_V3_RUN_ROOT",
        r"D:\AI\runs\shared-ledger\t1-release-v3-20261020",
    )
)
SNAPSHOT_ROOT = RUN_ROOT / "baseline-snapshot"
CANDIDATE_ROOT = RUN_ROOT / "candidate-v3"
REVIEW_ROOT = RUN_ROOT / "review"
SNAPSHOT_FORMAT = "t1-release-v3-source-snapshot"

SPLITS = ("train", "validation", "sealed")
OPERATIONS = (
    "read.activities", "read.expenses", "read.debts",
    "expense.create", "expense.update", "expense.presentation.update",
)
# The 24 boundary rows are carried over verbatim; they are excluded from the
# positive-family floor, exactly as in v2.
EXPECTED_ROW_COUNTS = {"train": 135, "validation": 129, "sealed": 129}
# v3 adds the twelve RBR04 original-currency coverage rows and the twelve
# base-currency coverage rows on top of the v2 shapes.
EXPECTED_ROW_COUNTS_V3 = {"train": 143, "validation": 137, "sealed": 137}

# --- RBR fix switches --------------------------------------------------------
# Each switch is explicit so a reviewer can see which quality item is active.
#   RBR01  empty-result answers bind a typed, citable query result
#   RBR02  no training-only "already read and consumed" hint in model input
#   RBR03  ambiguous clarification names candidates by returned facts
#   RBR04  non-integral-cent AA tails and multi-person small amounts
RBR01_QUERY_EVIDENCE = "rbr01"
RBR02_NO_CONSUMED_HINT = "rbr02"
RBR03_NATURAL_CLARIFICATION = "rbr03"
RBR04_AA_TAIL_COVERAGE = "rbr04"
ACTIVE_RBR_ITEMS = (
    RBR01_QUERY_EVIDENCE,
    RBR02_NO_CONSUMED_HINT,
    RBR03_NATURAL_CLARIFICATION,
    RBR04_AA_TAIL_COVERAGE,
)
