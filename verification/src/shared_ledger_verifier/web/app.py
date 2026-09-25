"""FastAPI Web application for Shared Ledger verification dashboard."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..focus_contract import COVERAGE_FOCUSES, SMOKE_FOCUSES
from ..supabase import load_local_env
from .service import (
    VerificationScanner,
    WorkflowOrchestrator,
    focus_catalog,
    orchestrator_instance,
    scanner_instance,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_local_env()
    yield


app = FastAPI(
    title="Shared Ledger Verification Console",
    description="Local lightweight dashboard for Shared Ledger verification workflow",
    version="0.1.0",
    lifespan=lifespan,
)

# Only local origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class RunWorkflowRequest(BaseModel):
    focus: str | None = Field(
        default=None, description="Single focus (kept for compatibility; e.g. expense_aa)"
    )
    focuses: list[str] | None = Field(
        default=None, description="One or more coverage focuses; takes precedence over focus"
    )
    count: int = Field(default=1, ge=1, le=10, description="Cases per focus, each with its own ScenarioPlan seed")
    seed: int | None = Field(default=None, ge=0, description="First ScenarioPlan seed; defaults to 1")

    def selected_focuses(self) -> list[str]:
        if self.focuses:
            return [focus for focus in self.focuses if focus]
        return [self.focus] if self.focus else []


@app.get("/api/dashboard")
def get_dashboard() -> dict[str, Any]:
    """Retrieve aggregate statistics for the dashboard."""
    return scanner_instance.get_dashboard_stats()


@app.get("/api/cases")
def list_cases(
    verdict: str = Query(default="ALL", description="Filter by verdict: ALL, PASS, FAIL, UNCERTAIN, ERROR"),
    focus: str = Query(default="ALL", description="Filter by focus: ALL or specific focus name"),
    coverage: str = Query(
        default="ALL",
        description="Filter by coverage: ALL, UNIQUE_VALID, DUPLICATE, FOCUS_MISMATCH, NOT_VALID",
    ),
    search: str = Query(default="", description="Search substring in run_id or case_id"),
) -> list[dict[str, Any]]:
    """List all scanned cases with flexible filtering."""
    cases = scanner_instance.scan_cases()
    filtered = []

    verdict_upper = verdict.strip().upper()
    focus_lower = focus.strip().lower()
    coverage_upper = coverage.strip().upper()
    search_lower = search.strip().lower()

    for c in cases:
        # Verdict filter
        if verdict_upper != "ALL":
            filter_status = c.get("filter_status", "").upper()
            if verdict_upper == "ERROR":
                if filter_status not in ("ERROR", "JUDGE_ERROR", "RUNNER_FAILED", "COMPILER_INVALID", "GENERATION_ERROR"):
                    continue
            elif filter_status != verdict_upper:
                continue

        # Focus filter
        if focus_lower != "all":
            c_focus = (c.get("focus") or "").lower()
            if c_focus != focus_lower:
                continue

        # Coverage filter
        if coverage_upper != "ALL":
            if (c.get("coverage_status") or "NOT_VALID").upper() != coverage_upper:
                continue

        # Search filter
        if search_lower:
            text = f"{c.get('id', '')} {c.get('run_id', '')} {c.get('focus', '')}".lower()
            if search_lower not in text:
                continue

        filtered.append(c)

    return filtered


@app.get("/api/cases/{case_id}")
def get_case_detail(case_id: str) -> dict[str, Any]:
    """Retrieve full artifacts and details for a specific case."""
    detail = scanner_instance.get_case_detail(case_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")
    return detail


@app.get("/api/issues")
def get_issue_queue() -> list[dict[str, Any]]:
    """Retrieve list of problematic runs (FAIL, UNCERTAIN, COMPILER_INVALID, etc.)."""
    return scanner_instance.get_issue_queue()


@app.get("/api/config/info")
def get_config_info() -> dict[str, Any]:
    """Return backend status without exposing sensitive credentials."""
    load_local_env()
    return {
        "supported_focuses": focus_catalog(),
        "smoke_focuses": list(SMOKE_FOCUSES),
        "coverage_focuses": list(COVERAGE_FOCUSES),
        "env_status": {
            "has_supabase_url": bool(os.environ.get("SUPABASE_URL")),
            "has_supabase_anon_key": bool(os.environ.get("SUPABASE_ANON_KEY")),
            "has_deepseek_api_key": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "has_local_llm_url": bool(os.environ.get("LOCAL_LLM_BASE_URL")),
            "local_generator_model": os.environ.get("LOCAL_LLM_MODEL") or "qwen/qwen3.5-9b",
            "compiler_model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4.1-flash",
            "judge_model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4.1-flash",
        },
    }


@app.get("/api/coverage")
def get_coverage() -> dict[str, Any]:
    """Unique-valid coverage counters over every generated case on disk."""
    return scanner_instance.get_coverage_report()


@app.post("/api/workflow/run")
def run_workflow(req: RunWorkflowRequest) -> dict[str, Any]:
    """Trigger a new workflow test batch in the background."""
    focuses = req.selected_focuses()
    if not focuses:
        raise HTTPException(status_code=400, detail="At least one focus is required")
    try:
        batch_id = orchestrator_instance.create_batch(focuses, req.count, req.seed)
        orchestrator_instance.run_batch_in_background(batch_id)
        return {
            "status": "started",
            "batch_id": batch_id,
            "focuses": focuses,
            "focus": focuses[0] if len(focuses) == 1 else "multi",
            "count": req.count,
            "total_count": req.count * len(focuses),
            "seed_base": req.seed if req.seed is not None else 1,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/workflow/live")
def get_workflow_live() -> dict[str, Any]:
    """Retrieve live execution status across all runners (Web UI or Claude Code / CLI)."""
    return scanner_instance.get_live_execution(orchestrator_instance)


@app.get("/api/workflow/status/{batch_id}")
def get_workflow_status(batch_id: str) -> dict[str, Any]:
    """Poll status of a background workflow batch."""
    batch = orchestrator_instance.get_batch_status(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@app.get("/api/workflow/events/{batch_id}")
async def stream_workflow_events(batch_id: str) -> StreamingResponse:
    """Server-Sent Events endpoint streaming pipeline progress in real-time.

    The orchestrator replays the batch's events so far to a late subscriber, so
    a client that attaches after the run request still sees ``batch_started``
    and every earlier case.  An unknown batch is a 404 rather than an endless
    keepalive stream.
    """
    if orchestrator_instance.get_batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    queue = orchestrator_instance.subscribe(batch_id)

    async def event_generator():
        try:
            while True:
                try:
                    # Timeout after 30 seconds to send keepalive comment
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: {event.get('event')}\ndata: {json.dumps(event.get('data', {}), ensure_ascii=False)}\n\n"
                    if event.get("event") == "batch_completed":
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            orchestrator_instance.unsubscribe(batch_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Mount static assets
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index_view() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
