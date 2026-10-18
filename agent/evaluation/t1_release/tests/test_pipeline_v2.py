from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from agent.evaluation.t1_release import pipeline
from agent.evaluation.t1_release.pipeline import (
    PreparedRelease,
    ReleasePipelineError,
    _PREPARED_RELEASE_SEAL,
    _source_manifest_payload,
    _source_digest,
    _pair_review_map,
    _root_review_header,
    _verify_saved_teacher_bindings,
    _verify_teacher_source_snapshot,
    canonical_json,
    collection_sha256,
    freeze_source_manifest,
    prepare_in_memory,
    sha256_bytes,
)


def _prepared_with_bytes(train: bytes, validation: bytes, sealed: bytes) -> PreparedRelease:
    source_body = {"format": "test-source-freeze", "agent_git_head": "test"}
    source_sha = sha256_bytes(canonical_json(source_body))
    source_bytes = canonical_json({**source_body, "source_manifest_sha256": source_sha})
    report_bytes = canonical_json({"collection_passed": True, "pair_findings": []})
    payload_hashes = {
        "train": sha256_bytes(train),
        "validation": sha256_bytes(validation),
        "sealed": sha256_bytes(sealed),
    }
    payloads_sha = sha256_bytes(canonical_json(payload_hashes))
    creation_body = {
        "format": "t1-release-v2-creation-manifest",
        "source_manifest_sha256": source_sha,
        "root_creation_receipt_sha256": "a" * 64,
        "collection_sha256": "b" * 64,
        "checker_report_sha256": sha256_bytes(report_bytes),
        "payload_sha256": payload_hashes,
        "payloads_sha256": payloads_sha,
        "row_counts": {"train": len(train.splitlines()), "validation": len(validation.splitlines()),
                        "sealed": len(sealed.splitlines())},
    }
    creation_bytes = canonical_json(creation_body)
    prepared = PreparedRelease(
        train_bytes=train,
        validation_bytes=validation,
        sealed_bytes=sealed,
        creation_manifest_bytes=creation_bytes,
        source_manifest_bytes=source_bytes,
        checker_report_bytes=report_bytes,
        root_receipt_sha256="a" * 64,
        collection_sha256="b" * 64,
        payloads_sha256=payloads_sha,
        creation_manifest_sha256=sha256_bytes(creation_bytes),
    )
    object.__setattr__(prepared, "_seal", _PREPARED_RELEASE_SEAL)
    return prepared


def _root_receipt(source_sha: str, collection_sha: str) -> dict:
    return {
        "decision": "approve_candidate_preparation",
        "review_kind": "root_agent",
        "reviewer_id": "root-test-reviewer",
        "evidence": "synthetic unit-test receipt only",
        "source_manifest_sha256": source_sha,
        "collection_sha256": collection_sha,
        "pair_dispositions": {},
    }


def _init_git_repo(path: Path, files: dict[str, bytes]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T1 test"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t1-test@example.invalid"],
                   check=True, capture_output=True)
    for relative, body in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    subprocess.run(["git", "-C", str(path), "add", "--all"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "fixture"], check=True, capture_output=True)


def test_public_source_freeze_binds_fixed_sources_environment_teacher_and_snapshot() -> None:
    manifest = freeze_source_manifest()
    assert _source_digest(manifest) == manifest["source_manifest_sha256"]
    assert set(manifest["agent_sources"]) == set(pipeline.REQUIRED_AGENT_SOURCES)
    assert manifest["snapshot"]["file_count"] == 72
    assert manifest["snapshot"]["manifest_sha256"] == pipeline.SNAPSHOT_MANIFEST_SHA256
    assert manifest["business_logic"]["matches_head"] is True
    assert manifest["environment"] == pipeline._runtime_environment()
    assert manifest["environment"]["python_executable"].casefold() == str(
        pipeline.EXPECTED_PYTHON_EXECUTABLE.resolve()
    ).casefold()
    assert manifest["environment"]["jsonschema_version"]
    assert manifest["environment"]["pydantic_version"]
    assert set(manifest["teacher_preregistration_bindings"]["saved_artifact_sha256"]) == {
        "teacher/readiness/request.json",
        "teacher/readiness/run_manifest.json",
        "teacher/probe/run_manifest.json",
        "teacher/source-snapshot/manifest.json",
        "teacher/source-snapshot/manifest.sha256",
    }
    assert manifest["teacher_preregistration_bindings"]["readiness_source_sha256"]
    assert manifest["teacher_preregistration_bindings"]["probe_source_sha256"]
    archive = manifest["teacher_preregistration_bindings"]["teacher_source_snapshot"]
    assert archive["manifest_sha256"] == pipeline._TEACHER_SOURCE_SNAPSHOT_MANIFEST_SHA256
    assert archive["file_count"] == 13
    assert archive["cohort_binding_count"] == 14


def test_saved_teacher_bindings_use_pinned_archive_after_mutable_guide_changes() -> None:
    repo = pipeline.AGENT_REPO_ROOT
    temp_parent = Path(r"D:\AI\runs\shared-ledger\t1-release-v2-20261011\pipeline-test-fixtures")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="teacher-binding-copy-", dir=temp_parent) as temp_name:
        temp_agent = Path(temp_name)
        metadata_paths = (
            "agent/evaluation/t1_teacher_readiness_v2/preregistration.json",
            "agent/evaluation/t1_teacher_readiness_v2/evidence/ROOT_REVIEW.json",
            "agent/evaluation/t1_teacher_probe/preregistration.json",
            "agent/evaluation/t1_teacher_probe/evidence/ROOT_REVIEW.json",
        )
        for relative in metadata_paths:
            target = temp_agent / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo / relative, target)
        guide = temp_agent / "agent/docs/shared-ledger-agent-development-guide-v0.4.html"
        guide.parent.mkdir(parents=True, exist_ok=True)
        guide.write_text("later mutable guide content", encoding="utf-8")

        bindings = _verify_saved_teacher_bindings(temp_agent)

    assert bindings["teacher_source_snapshot"]["manifest_sha256"] == (
        pipeline._TEACHER_SOURCE_SNAPSHOT_MANIFEST_SHA256
    )


def test_teacher_archive_rejects_changed_archived_source_bytes() -> None:
    repo = pipeline.AGENT_REPO_ROOT
    readiness = json.loads(
        (repo / "agent/evaluation/t1_teacher_readiness_v2/preregistration.json").read_text(encoding="utf-8")
    )
    probe = json.loads(
        (repo / "agent/evaluation/t1_teacher_probe/preregistration.json").read_text(encoding="utf-8")
    )
    temp_parent = Path(r"D:\AI\runs\shared-ledger\t1-release-v2-20261011\pipeline-test-fixtures")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="teacher-archive-copy-", dir=temp_parent) as temp_name:
        copy_root = Path(temp_name) / "teacher-source-snapshot"
        shutil.copytree(pipeline.TEACHER_SOURCE_SNAPSHOT_ROOT, copy_root)
        archived_guide = copy_root / "sources/agent/docs/shared-ledger-agent-development-guide-v0.4.html"
        archived_guide.write_bytes(archived_guide.read_bytes() + b"changed")
        with pytest.raises(ReleasePipelineError, match="archived Teacher source bytes"):
            _verify_teacher_source_snapshot(
                readiness_sources=readiness["source_sha256"],
                probe_sources=probe["source_sha256"],
                readiness_preregistration_sha256=sha256_bytes(
                    (repo / "agent/evaluation/t1_teacher_readiness_v2/preregistration.json").read_bytes()
                ),
                probe_preregistration_sha256=sha256_bytes(
                    (repo / "agent/evaluation/t1_teacher_probe/preregistration.json").read_bytes()
                ),
                snapshot_root=copy_root,
            )


def test_root_receipt_is_bound_to_current_source_and_collection_hashes() -> None:
    receipt = _root_receipt("a" * 64, "b" * 64)
    assert _root_review_header(receipt, "a" * 64, "b" * 64) is receipt
    with pytest.raises(ReleasePipelineError, match="different sources/collection"):
        _root_review_header(receipt, "c" * 64, "b" * 64)
    with pytest.raises(ReleasePipelineError, match="different sources/collection"):
        _root_review_header(receipt, "a" * 64, "d" * 64)


def test_near_pair_receipt_must_cover_exact_current_pairs_and_full_signatures() -> None:
    source_sha, collection_sha = "a" * 64, "b" * 64
    finding = {
        "finding_id": "near-001",
        "kind": "near_prompt_candidate",
        "left_prompt_sha256": "1" * 64,
        "right_prompt_sha256": "2" * 64,
        "left_full_state_signature_sha256": "3" * 64,
        "right_full_state_signature_sha256": "4" * 64,
    }
    disposition = {
        "decision": "distinct_initial_states", "review_kind": "root_agent",
        "reviewer_id": "root-test-reviewer", "evidence": "rechecked distinct visible facts",
        "source_manifest_sha256": source_sha, "collection_sha256": collection_sha,
        **{key: finding[key] for key in (
            "left_prompt_sha256", "right_prompt_sha256",
            "left_full_state_signature_sha256", "right_full_state_signature_sha256",
        )},
    }
    receipt = {
        "source_manifest_sha256": source_sha, "collection_sha256": collection_sha,
        "pair_dispositions": {"near-001": disposition},
    }
    accepted = _pair_review_map({"pair_findings": [finding]}, receipt)
    assert set(accepted) == {"near-001"}
    assert accepted["near-001"]["left_full_state_signature_sha256"] == "3" * 64
    with pytest.raises(ReleasePipelineError, match="exactly the current near-pair"):
        _pair_review_map({"pair_findings": [finding]}, {**receipt, "pair_dispositions": {}})
    with pytest.raises(ReleasePipelineError, match="exactly the current near-pair"):
        _pair_review_map({"pair_findings": [finding]}, {
            **receipt, "pair_dispositions": {**receipt["pair_dispositions"], "stale": disposition},
        })
    stale = {**disposition, "right_full_state_signature_sha256": "f" * 64}
    with pytest.raises(ReleasePipelineError, match="not bound to current evidence"):
        _pair_review_map({"pair_findings": [finding]}, {
            **receipt, "pair_dispositions": {"near-001": stale},
        })


def test_exact_prompt_and_state_leak_findings_cannot_be_root_dispositioned() -> None:
    receipt = {"pair_dispositions": {}}
    exact = {"finding_id": "exact-001", "kind": "exact_prompt_duplicate"}
    with pytest.raises(ReleasePipelineError, match="exact cross-split prompt duplicate"):
        _pair_review_map({"pair_findings": [exact]}, receipt)


def test_source_manifest_fixture_uses_real_self_digest_shape_on_d_drive() -> None:
    temp_parent = Path(r"D:\AI\runs\shared-ledger\t1-release-v2-20261011\pipeline-test-fixtures")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-shape-", dir=temp_parent) as temp_name:
        temp = Path(temp_name)
        agent = temp / "agent"
        main = temp / "main"
        snapshot = temp / "snapshot"
        _init_git_repo(agent, {"sentinel.py": b"VERSION = 1\n"})
        business = b"# synthetic business logic fixture\n"
        _init_git_repo(main, {"docs/backend/BUSINESS_LOGIC.md": business})
        snapshot.mkdir()
        file_map = {f"source-{index:02d}.py": {"sha256": f"{index:064x}"} for index in range(72)}
        snapshot_manifest = canonical_json({"files": file_map})
        (snapshot / "snapshot-manifest.json").write_bytes(snapshot_manifest)
        payload = _source_manifest_payload(
            agent_root=agent,
            main_root=main,
            teacher_evidence_sources=(),
            required_agent_sources=("sentinel.py",),
            snapshot_root=snapshot,
            snapshot_expected_sha256=sha256_bytes(snapshot_manifest),
            snapshot_verifier=lambda: {"files": file_map},
        )
        digest = sha256_bytes(canonical_json(payload))
        complete_manifest = {**payload, "source_manifest_sha256": digest}
        assert _source_digest(complete_manifest) == digest
        assert complete_manifest["agent_sources"] == {"sentinel.py": sha256_bytes(b"VERSION = 1\n")}
        assert complete_manifest["business_logic"]["matches_head"] is True
        assert complete_manifest["snapshot"]["file_count"] == 72


def test_source_manifest_self_digest_rejects_mutation() -> None:
    source_body = {
        "format": "t1-release-v2-source-freeze",
        "agent_git_head": "synthetic-test-head",
        "snapshot": {"file_count": 72, "manifest_sha256": "1" * 64},
    }
    manifest = {**source_body, "source_manifest_sha256": sha256_bytes(canonical_json(source_body))}
    broken = copy.deepcopy(manifest)
    broken["snapshot"]["file_count"] -= 1
    with pytest.raises(ReleasePipelineError, match="digest"):
        _source_digest(broken)


def test_canonical_json_rejects_nonfinite_numbers() -> None:
    with pytest.raises(ReleasePipelineError, match="canonical JSON"):
        canonical_json({"amount": float("nan")})


def test_v2_acceptance_keeps_v1_numeric_thresholds_and_separates_measurement_claims() -> None:
    docs = pipeline.AGENT_REPO_ROOT / "agent/docs/t1"
    v1 = json.loads((docs / "ACCEPTANCE_CRITERIA-T1-v1.json").read_text(encoding="utf-8"))
    v2 = json.loads((docs / "release-v2/ACCEPTANCE_CRITERIA-T1-v2.json").read_text(encoding="utf-8"))
    old_metrics = {item["id"]: item for item in v1["metrics"]}
    new_metrics = {item["id"]: item for item in v2["metrics"]}
    renamed = {"operation_choice_exact": "primary_operation_selection_exact"}
    for old_id, old in old_metrics.items():
        new = new_metrics[renamed.get(old_id, old_id)]
        assert (new["threshold"], new["direction"]) == (old["threshold"], old["direction"])
    assert v2["measurement_contract"]["primary_operation_selection"]["report_auxiliary_reads_separately"] is True
    result_consumption = v2["measurement_contract"]["result_consumption"]
    assert result_consumption["verify_each_asserted_final_answer_fact_and_citation_against_actual_result"] is True
    assert result_consumption["verify_answer_completeness_against_original_request_including_post_filter"] is True
    assert "including any post-filter" in new_metrics["deterministic_result_consumption_exact"]["denominator"]
    assert "Write trajectories" not in new_metrics["auxiliary_read_exact"]["denominator"]
    assert v2["measurement_contract"]["task_success_evidence"]["teacher_forced_frozen_contexts"].startswith(
        "NOT_A_CLOSED_LOOP"
    )
    assert v1["diagnostic_sample_floor"]["independent_state_families_per_enabled_operation"] == 5
    assert v2["formal_release_sample_floor"]["independent_state_families_per_enabled_operation_per_split"] == 20
    assert set(v2["formal_release_sample_floor"]["required_splits"]) == {
        "train", "validation", "sealed",
    }
    assert v2["reporting"]["teacher_data_quality_status_now"] == "NOT_ASSESSED"
    assert v2["reporting"]["student_model_quality_status_now"] == "DEFERRED_NOT_TESTED"
    assert v2["reporting"]["training_eligibility_status_now"].startswith("FALSE_")


def test_prepare_requires_schema_and_independent_gold_before_collection_gate() -> None:
    source = freeze_source_manifest()
    source_sha = source["source_manifest_sha256"]
    records = {
        split: [{"split": split, "sample_id": f"malformed-{split}"}]
        for split in ("train", "validation", "sealed")
    }
    receipt = _root_receipt(source_sha, collection_sha256(records))
    with pytest.raises(ReleasePipelineError, match="strict schema or independent gold"):
        prepare_in_memory(records, source, receipt)


def test_prepared_source_manifest_digest_is_rechecked() -> None:
    prepared = _prepared_with_bytes(b"{}\n", b"{}\n", b"sealed-content-must-not-be-logged\n")
    prepared.verify_integrity()
    object.__setattr__(
        prepared, "source_manifest_bytes",
        canonical_json({"format": "mutated", "source_manifest_sha256": "0" * 64}),
    )
    with pytest.raises(ReleasePipelineError, match="source manifest digest"):
        prepared.verify_integrity()


def test_prepared_release_bytes_are_hash_bound_and_repr_redacts_sealed_body() -> None:
    secret_marker = "SEALED-SEMANTIC-BODY-MUST-STAY-PRIVATE"
    prepared = _prepared_with_bytes(b"{}\n", b"{}\n", f"{secret_marker}\n".encode())
    prepared.verify_integrity()
    assert secret_marker not in repr(prepared)
    object.__setattr__(prepared, "sealed_bytes", b"tampered\n")
    with pytest.raises(ReleasePipelineError, match="changed after validation"):
        prepared.verify_integrity()


def test_untrusted_prepared_release_cannot_be_made_by_direct_constructor() -> None:
    prepared = _prepared_with_bytes(b"{}\n", b"{}\n", b"secret\n")
    forged = PreparedRelease(
        train_bytes=prepared.train_bytes,
        validation_bytes=prepared.validation_bytes,
        sealed_bytes=prepared.sealed_bytes,
        creation_manifest_bytes=prepared.creation_manifest_bytes,
        source_manifest_bytes=prepared.source_manifest_bytes,
        checker_report_bytes=prepared.checker_report_bytes,
        root_receipt_sha256=prepared.root_receipt_sha256,
        collection_sha256=prepared.collection_sha256,
        payloads_sha256=prepared.payloads_sha256,
        creation_manifest_sha256=prepared.creation_manifest_sha256,
    )
    with pytest.raises(ReleasePipelineError, match="gated preparation path"):
        forged.verify_integrity()


def test_immutable_payloads_are_canonical_jsonl_and_have_no_semantic_readback_api() -> None:
    row = {"sample_id": "unit-row", "split": "train", "value": "visible-only-in-test"}
    raw = canonical_json(row) + b"\n"
    prepared = _prepared_with_bytes(raw, b"{}\n", b"sealed-only\n")
    assert prepared.train_bytes == raw
    assert json.loads(prepared.train_bytes.splitlines()[0]) == row
    # The only public accessor for sealed data is the write path; no parsed-row
    # accessor is intentionally exposed on PreparedRelease.
    assert not hasattr(prepared, "sealed_rows")
    assert not hasattr(prepared, "read_sealed")

