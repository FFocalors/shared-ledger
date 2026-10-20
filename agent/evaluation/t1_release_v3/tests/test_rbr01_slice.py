"""Tests for the release-v3 conversion package.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m pytest agent/evaluation/t1_release_v3/tests -q
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import (  # noqa: E402
    convert, profile, runtime, schema, snapshot, v11_evidence,
)


@pytest.fixture(scope="module")
def converted():
    from agent.evaluation.t1_release_v3 import slice_rbr01

    snapshot.verify_snapshot()
    report_path = profile.RUN_ROOT / "conversion" / slice_rbr01.REPORT_NAME
    if not report_path.is_file():
        slice_rbr01.main([])
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_frozen_v2_artifacts_are_untouched():
    """The conversion must not have moved the v2 candidate or its receipts."""
    for split, expected in profile.V2_PAYLOAD_SHA256.items():
        path = profile.V2_CANDIDATE_ROOT / f"{split}.jsonl"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        assert len(path.read_text(encoding="utf-8").splitlines()) == profile.V2_ROW_COUNTS[split]


def test_snapshot_binds_the_frozen_v1_1_protocol():
    manifest = snapshot.verify_snapshot()
    assert manifest["file_count"] == 91
    assert manifest["protocol_v1_1"]["versions"]["semantic"] == profile.V11_SEMANTIC_VERSION
    v11_manifest = snapshot.v11_manifest()
    for name, expected in v11_manifest["schema_hashes"].items():
        path = snapshot.AGENT_DIR / profile.V11_SCHEMA_DIR_RELATIVE / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_v3_envelope_embeds_the_frozen_v1_1_schemas():
    envelope = schema.load_v3_envelope_schema()
    defs = envelope["$defs"]
    assert "v11_model_context" in defs and "v11_semantic_decision" in defs
    # The embedded context is the frozen v1.1 context, not the vendor v1 one.
    assert "query_observations" in defs["v11_model_context"]["properties"]
    # Model steps must use the v1.1 context and the v1.1 decision union.
    assert envelope["$defs"]["model_step"]["properties"]["context"]["$ref"] == "#/$defs/v11_model_context"
    assert envelope["$defs"]["model_step"]["properties"]["target"]["$ref"] == "#/$defs/v11_semantic_decision"
    assert envelope["properties"]["release_version"]["const"] == profile.RELEASE_VERSION
    assert envelope["properties"]["versions"]["properties"]["semantic"]["const"] == "1.1.0"


def test_rbr01_evidence_schema_forbids_an_unproven_zero():
    """No row may claim 'no match' without complete, untruncated coverage."""
    evidence = schema.RBR01_EVIDENCE_SCHEMA
    assert evidence["properties"]["matched_count"]["const"] == 0
    assert evidence["properties"]["page_complete"]["const"] is True
    assert evidence["properties"]["has_more"]["const"] is False
    assert evidence["properties"]["truncated"]["const"] is False
    assert evidence["properties"]["range_contiguous"]["const"] is True
    assert evidence["properties"]["stable_total_verified"]["const"] is True
    assert evidence["properties"]["source_version_fenced"]["const"] is True
    assert evidence["properties"]["unique_items_verified"]["const"] is True
    assert evidence["properties"]["source"]["const"] == "synthetic_simulation"
    assert evidence["additionalProperties"] is False


def test_the_three_no_match_rows_are_converted_and_validated(converted):
    assert converted["row_count"] == 3
    assert converted["v2_regeneration_reproduced_frozen_rows"] is True
    by_operation = {row["operation"]: row for row in converted["rows"]}
    assert set(by_operation) == {"read.activities", "read.expenses", "read.debts"}

    for row in converted["rows"]:
        assert row["citations"] == [v11_evidence.QUERY_REF]
        assert row["hint_removed"] is True
        assert row["zero_class"] in {"backend_zero", "post_filter_zero"}

    # Row 21 and 24 are true backend zeros; row 22 returned five real rows and
    # was emptied by a post-filter, and the two must stay distinguishable.
    assert by_operation["read.activities"]["zero_class"] == "backend_zero"
    assert by_operation["read.debts"]["zero_class"] == "backend_zero"
    assert by_operation["read.expenses"]["zero_class"] == "post_filter_zero"
    assert by_operation["read.expenses"]["returned_count"] == 5


def test_converted_rows_carry_the_v1_1_tuple_and_validate(converted):
    validator = runtime.make_v3_validator()
    rows_path = profile.RUN_ROOT / "conversion" / converted["rows_file"]
    raw = rows_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == converted["rows_file_sha256"]
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        assert row["release_version"] == profile.RELEASE_VERSION
        assert row["protocol_profile"] == profile.V11_PROFILE
        assert row["versions"]["semantic"] == profile.V11_SEMANTIC_VERSION
        errors = list(validator.iter_errors(row))
        assert errors == [], errors[:1]
        # The typed query evidence is on the tool observation and in the context.
        assert row["trace"][1]["query"]["query_ref"] == v11_evidence.QUERY_REF
        assert row["trace"][2]["context"]["query_observations"][0]["query_ref"] == v11_evidence.QUERY_REF
        # RBR02: the model input is the untouched original request.
        assert row["trace"][2]["context"]["input_text"] == row["trace"][0]["context"]["input_text"]
        for hint in convert.TRAINING_ONLY_HINTS:
            assert hint not in row["trace"][2]["context"]["input_text"]


def test_strip_training_only_hints_is_exact():
    assert convert.strip_training_only_hints("原始请求") == "原始请求"
    for hint in convert.TRAINING_ONLY_HINTS:
        assert convert.strip_training_only_hints("原始请求" + hint) == "原始请求"
    # An unrelated trailing sentence is never treated as a hint.
    assert convert.strip_training_only_hints("原始请求 请按结果作答。") == "原始请求 请按结果作答。"
