"""Tests for web dashboard service and FastAPI endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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
    assert len(data["supported_focuses"]) == 3
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
    for issue in issues:
        assert "issue_type" in issue
        assert issue["issue_type"] in ("FAIL", "UNCERTAIN", "COMPILER_INVALID", "RUNNER_FAILED", "JUDGE_ERROR", "ERROR", "GENERATION_ERROR")


def test_api_workflow_run_validation() -> None:
    # 1. Invalid focus
    bad_focus = client.post("/api/workflow/run", json={"focus": "invalid_focus", "count": 1})
    assert bad_focus.status_code == 400

    # 2. Invalid count
    bad_count = client.post("/api/workflow/run", json={"focus": "expense_aa", "count": 100})
    assert bad_count.status_code == 422  # pydantic validation error

    # 3. Valid call with mocked background runner
    with patch("shared_ledger_verifier.web.service.WorkflowOrchestrator.run_batch_in_background") as mock_run:
        good = client.post("/api/workflow/run", json={"focus": "expense_aa", "count": 2})
        assert good.status_code == 200
        data = good.json()
        assert data["status"] == "started"
        assert "batch_id" in data
        assert data["count"] == 2
        mock_run.assert_called_once()
