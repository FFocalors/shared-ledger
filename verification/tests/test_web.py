"""Tests for web dashboard service and FastAPI endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from shared_ledger_verifier.focus_contract import ALL_FOCUSES, COVERAGE_FOCUSES
from shared_ledger_verifier.web.app import app
from shared_ledger_verifier.web.service import VerificationScanner, WorkflowOrchestrator


client = TestClient(app)


def test_index_view() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Shared Ledger" in response.text
    assert "text/html" in response.headers.get("content-type", "")


def test_config_info_does_not_leak_secrets() -> None:
    response = client.get("/api/config/info")
    assert response.status_code == 200
    data = response.json()
    assert "supported_focuses" in data
    focuses = {entry["id"]: entry for entry in data["supported_focuses"]}
    assert len(focuses) == len(ALL_FOCUSES)
    assert set(data["smoke_focuses"]) == {"expense_aa", "targeted_repayment", "prepayment_refund"}
    assert set(data["coverage_focuses"]) == set(COVERAGE_FOCUSES)
    # The picker needs the plan dimensions, not just a name.
    for entry in focuses.values():
        assert entry["tier"] in {"smoke", "coverage"}
        assert entry["goal"]
        assert entry["participants"] and entry["payers"]
        assert entry["amount_patterns"] and entry["operation_counts"]
    assert focuses["multi_payer_aa"]["payers"] == [2, 3]
    assert "env_status" in data

    # Crucial safety check: ensure no actual secrets are in JSON
    for key, val in os.environ.items():
        if ("KEY" in key or "SECRET" in key) and len(val) >= 12:
            assert val not in response.text


def test_scanner_and_dashboard_stats() -> None:
    scanner = VerificationScanner()
    cases = scanner.scan_cases()
    assert isinstance(cases, list)

    # We know there are already runs or generated cases in the repository
    if cases:
        sample = cases[0]
        assert "id" in sample
        assert "source_type" in sample
        assert "focus" in sample
        assert "latencies" in sample
        assert "has_artifacts" in sample

    stats = scanner.get_dashboard_stats()
    assert "total_cases" in stats
    assert "verdicts" in stats
    assert "PASS" in stats["verdicts"]
    assert "FAIL" in stats["verdicts"]
    assert "loader_stats" in stats
    assert "runner_stats" in stats
    assert "average_latencies" in stats
    assert "focus_stats" in stats


def test_api_dashboard_endpoint() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "total_cases" in data
    assert "verdicts" in data


def test_api_cases_list_and_filters() -> None:
    # 1. Default list
    response = client.get("/api/cases")
    assert response.status_code == 200
    cases = response.json()
    assert isinstance(cases, list)

    # 2. Filter by verdict
    resp_pass = client.get("/api/cases?verdict=PASS")
    assert resp_pass.status_code == 200
    for c in resp_pass.json():
        assert c.get("filter_status") == "PASS"

    resp_fail = client.get("/api/cases?verdict=FAIL")
    assert resp_fail.status_code == 200
    for c in resp_fail.json():
        assert c.get("filter_status") == "FAIL"

    # 3. Filter by focus
    resp_focus = client.get("/api/cases?focus=expense_aa")
    assert resp_focus.status_code == 200
    for c in resp_focus.json():
        assert c.get("focus") == "expense_aa"


def test_api_case_detail() -> None:
    # Get first case from list
    list_resp = client.get("/api/cases")
    cases = list_resp.json()
    if cases:
        first_id = cases[0]["id"]
        detail_resp = client.get(f"/api/cases/{first_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert "artifacts" in detail
        arts = detail["artifacts"]
        assert "scenario" in arts

    # Non-existent case
    not_found_resp = client.get("/api/cases/non_existent_case_xyz")
    assert not_found_resp.status_code == 404


def test_api_issues_queue() -> None:
    response = client.get("/api/issues")
    assert response.status_code == 200
    issues = response.json()
    assert isinstance(issues, list)
    allowed = {
        "FAIL", "UNCERTAIN", "COMPILER_INVALID", "RUNNER_FAILED", "JUDGE_ERROR",
        "ERROR", "GENERATION_ERROR", "FOCUS_MISMATCH", "DUPLICATE_CASE",
    }
    for issue in issues:
        assert "issue_type" in issue
        assert issue["issue_type"] in allowed


def test_api_coverage_reports_unique_valid_counts() -> None:
    response = client.get("/api/coverage")
    assert response.status_code == 200
    data = response.json()
    for key in (
        "generated_count", "focus_valid_count", "focus_mismatch_count",
        "duplicate_count", "unique_valid_count", "distinct_scenarios",
        "compiler_repair_count", "loader_valid_count", "runner_executed_count",
        "judge_verdicts", "pass_rate", "focus_breakdown",
    ):
        assert key in data, key
    assert data["unique_valid_count"] <= data["generated_count"]
    assert data["focus_valid_count"] + data["focus_mismatch_count"] <= data["generated_count"]
    assert "cases" not in data


def test_api_cases_exposes_coverage_status_and_filters() -> None:
    cases = client.get("/api/cases").json()
    for case in cases:
        assert case["coverage_status"] in {
            "UNIQUE_VALID", "DUPLICATE", "FOCUS_MISMATCH", "NOT_VALID",
        }
        assert isinstance(case["duplicate"], bool)
        assert isinstance(case["unique_valid"], bool)
    unique = client.get("/api/cases?coverage=UNIQUE_VALID").json()
    assert all(case["coverage_status"] == "UNIQUE_VALID" for case in unique)
    assert len(unique) <= len(cases)


def test_api_cases_marks_a_repeat_as_a_duplicate() -> None:
    cases = [
        case for case in client.get("/api/cases").json()
        if case["source_type"] == "generated" and case["scenario_fingerprint"]
    ]
    by_fingerprint: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for case in cases:
        by_fingerprint.setdefault((case["focus"], case["scenario_fingerprint"]), []).append(case)
    for group in by_fingerprint.values():
        if len(group) < 2:
            continue
        canonical = next(case for case in group if not case["duplicate"])
        assert canonical["duplicate_of"] is None
        # unique_valid also requires the focus contract to be satisfied and the
        # Runner to have been attempted; pre-contract cases stay UNKNOWN.
        assert canonical["unique_valid"] == (
            canonical["focus_status"] == "FOCUS_VALID"
            and canonical["loader_result"] == "VALID"
            and canonical["runner_result"] is not None
        )
        for case in group:
            if case is canonical:
                continue
            assert case["duplicate"] is True
            assert case["duplicate_of"] == canonical["id"]
            assert case["unique_valid"] is False
        return
    pytest.skip("no duplicate scenario pair on disk yet")


def test_create_batch_plans_one_seed_per_case() -> None:
    orchestrator = WorkflowOrchestrator(VerificationScanner())
    batch_id = orchestrator.create_batch(["multi_payer_aa", "fifo_repayment"], count=2, seed=10)
    batch = orchestrator.get_batch(batch_id)
    assert batch is not None
    assert batch["focuses"] == ["multi_payer_aa", "fifo_repayment"]
    assert batch["total_count"] == 4
    assert [(task["focus"], task["seed"]) for task in batch["tasks"]] == [
        ("multi_payer_aa", 10), ("multi_payer_aa", 11),
        ("fifo_repayment", 12), ("fifo_repayment", 13),
    ]
    with pytest.raises(ValueError):
        orchestrator.create_batch(["not_a_focus"], count=1)
    with pytest.raises(ValueError):
        orchestrator.create_batch(["expense_aa"], count=0)
    with pytest.raises(ValueError):
        orchestrator.create_batch([], count=1)


def test_sse_replays_earlier_events_to_a_late_subscriber() -> None:
    orchestrator = WorkflowOrchestrator(VerificationScanner())
    batch_id = orchestrator.create_batch(["expense_aa"], count=1)
    # These fire before any browser has attached its EventSource.
    orchestrator._broadcast_event(batch_id, "batch_started", {"total_count": 1})
    orchestrator._broadcast_event(batch_id, "case_started", {"case_index": 1})
    queue = orchestrator.subscribe(batch_id)
    replayed = [queue.get_nowait()["event"] for _ in range(queue.qsize())]
    assert replayed == ["batch_started", "case_started"]
    orchestrator.unsubscribe(batch_id, queue)


def test_sse_unknown_batch_is_not_found() -> None:
    assert client.get("/api/workflow/events/batch_does_not_exist").status_code == 404
    assert client.get("/api/workflow/status/batch_does_not_exist").status_code == 404


def test_api_workflow_run_validation() -> None:
    # 1. Invalid focus
    bad_focus = client.post("/api/workflow/run", json={"focus": "invalid_focus", "count": 1})
    assert bad_focus.status_code == 400

    # 2. Invalid count
    bad_count = client.post("/api/workflow/run", json={"focus": "expense_aa", "count": 100})
    assert bad_count.status_code == 422  # pydantic validation error

    # 2b. No focus at all
    assert client.post("/api/workflow/run", json={"count": 1}).status_code == 400

    # 3. Valid call with mocked background runner
    with patch("shared_ledger_verifier.web.service.WorkflowOrchestrator.run_batch_in_background") as mock_run:
        good = client.post("/api/workflow/run", json={"focus": "expense_aa", "count": 2})
        assert good.status_code == 200
        data = good.json()
        assert data["status"] == "started"
        assert "batch_id" in data
        assert data["count"] == 2
        assert data["total_count"] == 2
        mock_run.assert_called_once()

    # 4. Multi-focus batch with an explicit seed base
    with patch("shared_ledger_verifier.web.service.WorkflowOrchestrator.run_batch_in_background"):
        multi = client.post("/api/workflow/run", json={
            "focuses": ["multi_payer_aa", "void_transfer"], "count": 2, "seed": 7,
        })
        assert multi.status_code == 200
        body = multi.json()
        assert body["focuses"] == ["multi_payer_aa", "void_transfer"]
        assert body["total_count"] == 4
        assert body["seed_base"] == 7


def test_api_workflow_live() -> None:
    response = client.get("/api/workflow/live")
    assert response.status_code == 200
    data = response.json()
    assert "has_active_run" in data
    assert "server_time" in data
    assert "latest_completed" in data

