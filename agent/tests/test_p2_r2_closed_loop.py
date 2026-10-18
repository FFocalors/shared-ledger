from __future__ import annotations

"""CPU-only R2 exercise through the real P2 provider adapter and runtime.

The injected transport and token counter are deterministic test doubles. This
test does not open an LM Studio socket and is not live-model evidence.
"""

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import contracts as c
from app.components import AppComponents
from app.p2_backend import (
    P2BackendAdapter,
    P2BackendConfig,
    TransportResponse,
)
from app.p2_journal import P2ErrorProofJournal
from app.p2_identity import P2GrantError
from app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    _TransportResult,
)
from app.p2_runtime import P2Runtime
from app.p2_token_budget import P2TokenBudgetMeasurement
from app.ports import AgentControlSnapshot
from app.settings import Settings
from app.store import SQLiteAgentStore


OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")
ACTIVITY = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNIT = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
MORGAN = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
SOL = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
TOKEN = "synthetic-r2-token-never-log"
ENDPOINT = "http://127.0.0.1:1234/v1/chat/completions"
API_HOST = "http://127.0.0.1:1234"
ARTIFACT_HASH = "a" * 64
PROJECT_URL = "https://r2-fixture.invalid"
PUBLISHABLE_KEY = "sb_publishable_r2_cpu_fixture"


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_returned_body_hash(returned_hash: str | None, persisted_body: Any) -> str:
    expected = _sha256_json(persisted_body)
    if returned_hash != expected:
        raise AssertionError("provider request body does not match the persisted read result")
    return expected


def _export_cpu_evidence(
    export_dir: str | None,
    requests: list[Any],
    measurements: list[P2TokenBudgetMeasurement],
    calls: list[dict[str, Any]],
    fake_http: "_InProcessReadOnlyTransport",
    ledger: "_R2GenerationLedger",
    public_client: "_BoundedPublicClient",
) -> None:
    if not export_dir:
        return
    target = Path(export_dir)
    target.mkdir(parents=True, exist_ok=False)
    prompt_dir = target / "dynamic-provider-requests"
    prompt_dir.mkdir()
    request_stages: dict[tuple[str, str], Any] = {}
    for request in requests:
        user_message = next(item.content for item in request.messages if item.role == "user")
        prefix, separator, envelope_text = user_message.partition("\n")
        if not separator or not prefix.endswith("(JSON data):"):
            raise AssertionError("unexpected provider user-message envelope")
        envelope = json.loads(envelope_text)
        context = envelope["context"]
        input_text = context["input_text"].casefold()
        tag = "expense" if "expense" in input_text else "debt" if "debt" in input_text else None
        if tag is None:
            raise AssertionError("provider request cannot be assigned to a fixture Turn")
        stage = "post-read" if context["read_results"] else "first-stage"
        key = (tag, stage)
        if key in request_stages:
            raise AssertionError("duplicate provider request stage in CPU fixture")
        request_stages[key] = request
    if set(request_stages) != {
        ("expense", "first-stage"), ("expense", "post-read"),
        ("debt", "first-stage"), ("debt", "post-read"),
    }:
        raise AssertionError("expected first-stage and post-read requests for both fixtures")
    for tag, stage in sorted(request_stages):
        request = request_stages[(tag, stage)]
        payload = {
            "model_key": request.model_key,
            "api_host": request.api_host,
            "messages": [{"role": item.role, "content": item.content} for item in request.messages],
            "response_format_payload_json": (
                request.response_format.payload_json if request.response_format is not None else None
            ),
            "max_output_tokens": request.max_output_tokens,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        if TOKEN.encode("utf-8") in encoded:
            raise AssertionError("synthetic bearer leaked into provider request export")
        filename_stage = "dynamic-request" if stage == "post-read" else "first-stage-request"
        (prompt_dir / f"{tag}-{filename_stage}.json").write_bytes(encoded)
    summary = {
        "classification": "cpu_controlled_transport_only_not_live_model_evidence",
        "lm_generations": ledger.total,
        "lm_generation_ledger": {
            "direct_provider": ledger.direct,
            "closed_loop": ledger.closed_loop,
            "by_turn": ledger.by_turn,
            "attempts": ledger.attempts,
            "absolute_limit": ledger.total_limit,
            "direct_limit": ledger.direct_limit,
            "closed_loop_limit": ledger.closed_loop_limit,
            "per_turn_limit": ledger.per_turn_limit,
        },
        "runtime_public_http_requests": public_client.request_count,
        "runtime_public_request_shapes": public_client.request_shapes,
        "provider_token_budget_measurements": [_canonical(item) for item in measurements],
        "model_calls": calls,
        "fake_http_calls": fake_http.calls,
        "fake_source_response_body_hashes": fake_http.source_body_hashes,
        "fake_read_routes": fake_http.read_routes,
        "bearer_values_recorded": False,
        "network_sockets_opened_for_backend": False,
    }
    (target / "cpu-closed-loop-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8",
    )


class _Auth:
    configured = True

    def verify_bearer(self, token: str):
        if token != TOKEN:
            from app.auth import Unauthenticated
            raise Unauthenticated("synthetic principal rejected")
        from app.ports import Principal
        return Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))


class _R2GenerationLedger:
    """Separate LM-generation accounting for this bounded closed-loop runner."""

    def __init__(self) -> None:
        self.total_limit = 24
        self.direct_limit = 9
        self.closed_loop_limit = 12
        self.per_turn_limit = 6
        self.direct = 0
        self.closed_loop = 0
        self.by_turn: dict[str, int] = {}
        self.attempts: list[dict[str, Any]] = []

    def record_direct(self) -> None:
        if self.direct >= self.direct_limit or self.direct + self.closed_loop >= self.total_limit:
            raise AssertionError("R2 LM generation ledger cap reached before provider call")
        self.direct += 1
        self.attempts.append({"kind": "direct_provider", "ordinal": self.direct})

    def record_closed_loop(self, turn_tag: str) -> None:
        turn_count = self.by_turn.get(turn_tag, 0)
        if (
            turn_count >= self.per_turn_limit
            or self.closed_loop >= self.closed_loop_limit
            or self.direct + self.closed_loop >= self.total_limit
        ):
            raise AssertionError("R2 LM generation ledger cap reached before provider call")
        turn_count += 1
        self.by_turn[turn_tag] = turn_count
        self.closed_loop += 1
        self.attempts.append({
            "kind": "closed_loop", "turn_tag": turn_tag, "turn_ordinal": turn_count,
            "closed_loop_ordinal": self.closed_loop,
        })

    @property
    def total(self) -> int:
        return self.direct + self.closed_loop


class _LedgerProvider:
    def __init__(self, provider: Any, ledger: _R2GenerationLedger) -> None:
        self._provider = provider
        self._ledger = ledger

    async def generate(self, prompt: Any) -> str:
        text = prompt.context.input_text.casefold()
        turn_tag = "expense" if "expense" in text else "debt" if "debt" in text else "unknown"
        self._ledger.record_closed_loop(turn_tag)
        return await self._provider.generate(prompt)


class _BoundedPublicClient:
    """Count and stop public API requests before crossing the HTTP client."""

    def __init__(self, client: TestClient, maximum: int = 12) -> None:
        self._client = client
        self.maximum = maximum
        self.request_count = 0
        self.request_shapes: list[dict[str, str]] = []

    def __enter__(self) -> "_BoundedPublicClient":
        self._client.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._client.__exit__(*args)

    def request(self, method: str, url: str, **kwargs: Any):
        if self.request_count >= self.maximum:
            raise AssertionError("R2 public HTTP request cap reached before client dispatch")
        self.request_count += 1
        path_parts = url.split("?", 1)[0].split("/")
        if len(path_parts) >= 3 and path_parts[-1] == "turns":
            safe_path = "/v1/sessions/{session_id}/turns"
        elif len(path_parts) >= 4 and path_parts[-1] == "events":
            safe_path = "/v1/turns/{turn_id}/events"
        else:
            safe_path = url.split("?", 1)[0]
        self.request_shapes.append({"method": method.upper(), "path": safe_path})
        return self._client.request(method, url, **kwargs)


class _Control:
    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=True, disable_revision=0, source="r2-cpu-test")


class _InProcessReadOnlyTransport:
    """HTTP-shaped allowlisted fake; never resolves the .invalid host."""

    def __init__(self) -> None:
        now = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        expense_id = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
        self.rows: dict[str, list[dict[str, Any]]] = {
            "activities": [{
                "id": str(ACTIVITY), "name": "R2 synthetic activity", "type": "normal",
                "base_currency": "USD", "multi_currency_enabled": True,
                "is_deleted": False, "archived_at": None, "financial_version": 7,
            }],
            "activity_members": [{"activity_id": str(ACTIVITY), "user_id": str(OWNER)}],
            "ledger_units": [{
                "id": str(UNIT), "activity_id": str(ACTIVITY), "name": "Main",
                "type": "normal", "is_deleted": False, "participant_scope_configured": False,
            }],
            "participants": [
                {"id": str(MORGAN), "activity_id": str(ACTIVITY), "name": "Morgan",
                 "participant_order": 1, "is_deleted": False},
                {"id": str(SOL), "activity_id": str(ACTIVITY), "name": "Sol",
                 "participant_order": 2, "is_deleted": False},
            ],
            "sub_activity_participants": [],
            "expenses": [{
                "id": str(expense_id), "ledger_unit_id": str(UNIT), "title": "Harbor ferry",
                "original_amount": "37.60", "original_currency": "GBP", "fx_rate": "1.28",
                "base_amount": "48.13", "occurred_at": now.isoformat(),
                "original_expense_id": None, "version": 2,
                "is_deleted": False, "financial_locked": False,
            }],
            "payments": [
                {"id": "12121212-1212-4212-8212-121212121212", "expense_id": str(expense_id),
                 "participant_id": str(MORGAN), "amount": "30.00", "base_amount": "38.40"},
                {"id": "13131313-1313-4313-8313-131313131313", "expense_id": str(expense_id),
                 "participant_id": str(SOL), "amount": "7.60", "base_amount": "9.73"},
            ],
            "splits": [
                {"id": "14141414-1414-4414-8414-141414141414", "expense_id": str(expense_id),
                 "participant_id": str(MORGAN), "amount": "5.60", "base_amount": "7.17"},
                {"id": "15151515-1515-4515-8515-151515151515", "expense_id": str(expense_id),
                 "participant_id": str(SOL), "amount": "32.00", "base_amount": "40.96"},
            ],
            "rpc/list_settlement_options": [
                {"debtor_participant_id": str(MORGAN), "creditor_participant_id": str(SOL),
                 "currency": "EUR", "original_amount": "18.40", "base_amount": "20.15",
                 "base_total": "20.15", "financial_version": 7},
                {"debtor_participant_id": str(SOL), "creditor_participant_id": str(MORGAN),
                 "currency": "JPY", "original_amount": "1200.00", "base_amount": "8.20",
                 "base_total": "8.20", "financial_version": 7},
            ],
        }
        self.calls: list[dict[str, Any]] = []
        self.source_body_hashes: list[str] = []
        self.read_routes: list[str] = []
        self._lock = threading.Lock()

    @staticmethod
    def _matches(row: dict[str, Any], key: str, expression: str) -> bool:
        if expression.startswith("eq."):
            actual = str(row.get(key, ""))
            expected = expression[3:]
            if expected in ("true", "false"):
                return actual.casefold() == expected
            return actual == expected
        if expression.startswith("in.(") and expression.endswith(")"):
            return str(row.get(key, "")) in expression[4:-1].split(",")
        return True

    def get(
        self, url: str, headers: dict[str, str], *, timeout: float,
        max_response_bytes: int, control: Any,
    ) -> TransportResponse:
        import urllib.parse

        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "r2-fixture.invalid":
            raise AssertionError("fake transport refuses all non-fixture endpoints")
        route = parsed.path.removeprefix("/rest/v1/")
        if route not in self.rows:
            raise AssertionError(f"fake transport refuses unmapped route: {route}")
        if headers.get("Authorization") != f"Bearer {TOKEN}":
            raise AssertionError("fake transport saw an unexpected principal credential")
        if headers.get("apikey") != PUBLISHABLE_KEY or headers.get("Prefer") != "count=exact":
            raise AssertionError("fake transport received unexpected API headers")
        if control.aborted or timeout <= 0:
            raise AssertionError("fixture request unexpectedly aborted or unbounded")
        params = urllib.parse.parse_qs(parsed.query)
        filters = {key: value[-1] for key, value in params.items()
                   if key not in {"select", "order", "limit", "offset", "p_activity_id"}}
        source_rows = self.rows[route]
        if route == "rpc/list_settlement_options":
            assert params.get("p_activity_id") == [str(ACTIVITY)]
        matching = [
            row for row in source_rows
            if all(self._matches(row, key, expression) for key, expression in filters.items())
        ]
        offset = int(params.get("offset", ["0"])[0])
        limit = int(params.get("limit", ["64"])[0])
        page = matching[offset:offset + limit]
        if len(matching) == 0:
            content_range = "*/0"
        else:
            content_range = f"{offset}-{offset + len(page) - 1}/{len(matching)}"
        body = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > max_response_bytes:
            raise AssertionError("fixture exceeded adapter's response bound")
        with self._lock:
            self.calls.append({
                "route": route, "method": "GET", "has_synthetic_bearer": True,
                "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "request_header_names": sorted(name.lower() for name in headers),
                "response_sha256": hashlib.sha256(body).hexdigest(), "row_count": len(page),
            })
            self.source_body_hashes.append(hashlib.sha256(body).hexdigest())
            if route in ("expenses", "payments", "splits", "rpc/list_settlement_options"):
                self.read_routes.append(route)
        return TransportResponse(status=206, body=body, content_range=content_range)


class _FakeTokenBudgetChecker:
    """A byte-length estimate for CPU flow tests, not an SDK token counter."""

    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.measurements: list[P2TokenBudgetMeasurement] = []

    def measure(self, request: Any) -> P2TokenBudgetMeasurement:
        self.requests.append(request)
        prompt_tokens = sum((len(item.content.encode("utf-8")) + 3) // 4 for item in request.messages)
        schema_tokens = (
            (len(request.response_format.payload_json.encode("utf-8")) + 3) // 4
            if request.response_format is not None else 0
        )
        measurement = P2TokenBudgetMeasurement(
            model_key=request.model_key, api_host=API_HOST,
            artifact_path="CPU_FAKE_ONLY/model.gguf", artifact_sha256=ARTIFACT_HASH,
            actual_context_tokens=8192, prompt_tokens=prompt_tokens,
            response_format_tokens=schema_tokens, safety_margin_tokens=512,
            budgeted_input_tokens=prompt_tokens + schema_tokens + 512,
            max_input_tokens=6144, requested_output_tokens=request.max_output_tokens,
            max_output_tokens=768, method="cpu-test-byte-estimate-not-sdk",
        )
        self.measurements.append(measurement)
        return measurement


class _ControlledTransport:
    """Deterministic model transport used only to test request/body plumbing."""

    def __init__(
        self, *, block_first: bool = True, fail_on_call: int | None = None,
        omit_raw_expense_split: bool = False,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self._block_first = block_first
        self._fail_on_call = fail_on_call
        self._omit_raw_expense_split = omit_raw_expense_split
        self._attempt_count = 0
        self._active = 0
        self.max_active = 0

    def __call__(self, endpoint: str, body: bytes, headers: dict[str, str], timeout: float, cap: int):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self._attempt_count += 1
            attempt_number = self._attempt_count
            should_block = self._block_first
            self._block_first = False
        try:
            assert endpoint == ENDPOINT
            assert "Authorization" not in headers
            request_hash = hashlib.sha256(body).hexdigest()
            if self._fail_on_call == attempt_number:
                self.attempts.append({
                    "attempt": attempt_number, "request_sha256": request_hash,
                    "failure": "synthetic_offline_before_completion",
                })
                raise ConnectionError("synthetic transport offline")
            payload = json.loads(body.decode("utf-8"))
            user_text = payload["messages"][1]["content"]
            prefix, separator, envelope_json = user_text.partition("\n")
            assert separator and prefix.endswith("(JSON data):")
            envelope = json.loads(envelope_json)
            context = envelope["context"]
            input_text = context["input_text"].casefold()
            turn_tag = "expense" if "expense" in input_text else "debt"
            read_results = context["read_results"]
            if not read_results:
                scope_ref = context["verified_scope"]["activity_ref"]
                operation = "read.expenses" if turn_tag == "expense" else "read.debts"
                decision = {
                    "kind": "read", "operation": operation,
                    "criteria": {
                        "kind": "expenses" if turn_tag == "expense" else "debts",
                        "activity_ref": scope_ref,
                    },
                }
                stage = "model_selected_read"
                result_body_hash = None
            else:
                result = read_results[-1]
                assert result["operation"] == ("read.expenses" if turn_tag == "expense" else "read.debts")
                items = result["body"]["items"]
                assert items
                citations = [item["evidence_ref"] for item in items]
                if turn_tag == "expense":
                    fact = items[0]
                    supplements = envelope["expense_supplements"]
                    assert len(supplements) == 1
                    supplement = supplements[0]
                    assert supplement["evidence_ref"] == fact["evidence_ref"]
                    payer_lines = [
                        f"{line['display_name']} {line['amount']} {line['currency']}"
                        for line in supplement["payments"]
                    ]
                    split_lines = [
                        f"{line['display_name']} {line['amount']} {line['currency']}"
                        for line in supplement["splits"]
                    ]
                    raw_text = (
                        f"{fact['title']}: {fact['original_amount']} {fact['original_currency']}. "
                        f"Payers: {'; '.join(payer_lines)}. Splits: {'; '.join(split_lines)}."
                    )
                    if self._omit_raw_expense_split:
                        raw_text = raw_text.replace("Morgan 5.60 GBP", "Morgan omitted")
                    expected_fragments = [
                        "Harbor ferry", "37.60 GBP", "Morgan 30.00 GBP", "Sol 7.60 GBP",
                        "Morgan 5.60 GBP", "Sol 32.00 GBP",
                    ]
                else:
                    labels = {item["ref"]: item["display_name"]
                              for item in envelope["reference_labels"]}
                    raw_text = "; ".join(
                        f"{labels[item['debtor_ref']]} owes {labels[item['creditor_ref']]} "
                        f"{item['amount']} {item['currency']}"
                        for item in items
                    )
                    expected_fragments = [
                        "Morgan owes Sol 18.40 EUR", "Sol owes Morgan 1200.00 JPY",
                    ]
                raw_financial_text_complete = all(fragment in raw_text for fragment in expected_fragments)
                raw_financial_text_has_base_currency = "USD" in raw_text
                decision = {
                    "kind": "answer", "basis": "grounded",
                    "text": raw_text,
                    "citations": citations,
                }
                stage = "model_saw_returned_body"
                result_body_hash = _sha256_json(result["body"])
            if stage == "model_selected_read":
                raw_financial_text_complete = None
                raw_financial_text_has_base_currency = None
                raw_text = json.dumps(decision, ensure_ascii=False)
            raw_completion = json.dumps(decision, ensure_ascii=False, separators=(",", ":"))
            self.calls.append({
                "turn_tag": turn_tag, "stage": stage,
                "request_sha256": request_hash,
                "returned_model_body_sha256": result_body_hash,
                "raw_completion": raw_completion,
                "raw_completion_sha256": hashlib.sha256(raw_completion.encode("utf-8")).hexdigest(),
                "raw_financial_text": decision.get("text"),
                "raw_financial_text_complete": raw_financial_text_complete,
                "raw_financial_text_has_base_currency": raw_financial_text_has_base_currency,
                "decision": decision,
                "next_step": "backend_read" if stage == "model_selected_read" else "rendered_answer",
            })
            if should_block:
                self.entered.set()
                if not self.release.wait(5):
                    raise TimeoutError("CPU controlled-transport test release timed out")
            response = {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": raw_completion},
                }],
            }
            response_bytes = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            assert len(response_bytes) <= cap
            return _TransportResult(status=200, body=response_bytes)
        finally:
            with self._lock:
                self._active -= 1


def _build_client(
    database_path: Any, *, fail_on_provider_call: int | None = None,
    omit_raw_expense_split: bool = False,
):
    store = SQLiteAgentStore(database_path, admission_enabled=True)
    auth = _Auth()
    fake_http = _InProcessReadOnlyTransport()
    backend = P2BackendAdapter(
        P2BackendConfig(
            project_url=PROJECT_URL, publishable_key=PUBLISHABLE_KEY,
            timeout_seconds=1.0, max_response_bytes=8_192, page_size=16,
            max_pages=8, max_rows_per_query=128, max_requests_per_read=48,
            max_total_response_bytes=65_536, max_total_seconds=2.0, max_facts=16,
        ),
        transport=fake_http,
    )
    transport = _ControlledTransport(
        block_first=fail_on_provider_call is None, fail_on_call=fail_on_provider_call,
        omit_raw_expense_split=omit_raw_expense_split,
    )
    token_counter = _FakeTokenBudgetChecker()
    generation_ledger = _R2GenerationLedger()
    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(
            model_key="synthetic-cpu-model", enabled=True, endpoint_url=ENDPOINT,
            max_output_tokens=768,
        ),
        transport=transport,
        token_budget_checker=token_counter,
    )
    runtime = P2Runtime(
        store, _LedgerProvider(provider, generation_ledger), backend, auth, _Control(),
        P2ErrorProofJournal(database_path.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=3, max_model_calls=6, max_read_calls=4, max_repair_calls=1,
    )
    components = AppComponents(
        store=store, provider=provider, backend=backend, runtime=runtime,
        gateway=object(), auth_verifier=auth, scope_authorizer=None, agent_control=_Control(),
    )
    settings = Settings(
        storage_path=database_path, provider_mode="mock", agent_enabled=True,
        disable_revision=0, api_requests_per_minute=500,
    )
    from app.main import create_app
    client = _BoundedPublicClient(TestClient(create_app(settings, components_factory=lambda _: components)))
    return client, components, backend, fake_http, provider, transport, token_counter, generation_ledger


def _request(client: TestClient, method: str, path: str, **kwargs: Any):
    response = client.request(method, path, headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs)
    assert response.status_code < 400, response.text
    return response


def _create_session(client: TestClient) -> uuid.UUID:
    response = _request(client, "POST", "/v1/sessions", json={
        "api_version": "1.0.0", "client_request_id": str(uuid.uuid4()), "title": "R2 CPU fixture",
    })
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["session"]["session_id"])


def _submit(client: TestClient, session_id: uuid.UUID, text: str) -> uuid.UUID:
    response = _request(client, "POST", f"/v1/sessions/{session_id}/turns", json={
        "client_request_id": str(uuid.uuid4()), "text": text,
        "ui_context": {
            "page_type": "activity_overview", "activity_id": str(ACTIVITY),
            "captured_at": datetime.now(timezone.utc).isoformat(), "client_version": "r2-cpu-test",
        },
    })
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["turn_id"])


def _wait_terminal(components: AppComponents, turn_id: uuid.UUID) -> Any:
    deadline = time.monotonic() + 7
    last = None
    while time.monotonic() < deadline:
        last = components.store.get_turn(OWNER, turn_id)
        if last.record.turn.state in (c.TurnState.COMPLETED, c.TurnState.FAILED, c.TurnState.CANCELLED):
            return last
        time.sleep(0.01)
    raise AssertionError(f"R2 CPU Turn did not finish: {turn_id}")


def _wait_state(components: AppComponents, turn_id: uuid.UUID, state: c.TurnState) -> Any:
    deadline = time.monotonic() + 7
    last = None
    while time.monotonic() < deadline:
        last = components.store.get_turn(OWNER, turn_id)
        if last.record.turn.state == state:
            return last
        time.sleep(0.01)
    raise AssertionError(f"Turn did not reach {state}: {turn_id}; last={last.record.turn.state if last else None}")


def test_r2_two_turn_closed_loop_is_dynamic_bounded_and_fake_only(tmp_path) -> None:
    client, components, backend, fake_http, provider, transport, token_counter, ledger = _build_client(
        tmp_path / "r2-closed-loop.sqlite3",
    )
    with client:
        session_expense = _create_session(client)
        session_debt = _create_session(client)
        expense_turn = _submit(
            client, session_expense,
            "For this activity, read the expense records and report each payer and split separately in its original currency.",
        )
        assert transport.entered.wait(3), "first controlled transport call did not reach the blocking point"

        debt_turn = _submit(
            client, session_debt,
            "For this activity, read the recorded debt directions and amounts in their recorded currencies; keep each separate.",
        )
        queued = components.store.get_turn(OWNER, debt_turn)
        assert queued.record.turn.state == c.TurnState.QUEUED
        transport.release.set()

        expense = _wait_terminal(components, expense_turn)
        debt = _wait_terminal(components, debt_turn)
        assert expense.record.turn.state == c.TurnState.COMPLETED
        assert debt.record.turn.state == c.TurnState.COMPLETED
        assert (expense.checkpoint.model_calls, expense.checkpoint.read_calls, expense.checkpoint.repair_calls) == (2, 1, 0)
        assert (debt.checkpoint.model_calls, debt.checkpoint.read_calls, debt.checkpoint.repair_calls) == (2, 1, 0)

        assert isinstance(backend, P2BackendAdapter)
        assert [item["route"] for item in fake_http.calls if item["route"] in {
            "expenses", "payments", "splits", "rpc/list_settlement_options",
        }] == ["expenses", "payments", "splits", "rpc/list_settlement_options"]
        assert len(fake_http.source_body_hashes) == len(fake_http.calls)
        assert all(item["has_synthetic_bearer"] and item["method"] == "GET"
                   for item in fake_http.calls)
        assert all(item["request_header_names"] == ["accept", "apikey", "authorization", "prefer"]
                   for item in fake_http.calls)
        assert all(item["response_sha256"] for item in fake_http.calls)
        assert len(transport.calls) == 4
        assert ledger.total == 4 and ledger.closed_loop == 4 and ledger.direct == 0
        assert ledger.by_turn == {"expense": 2, "debt": 2}
        assert len(token_counter.requests) == 4
        assert transport.max_active == 1
        # These are byte-estimate checks to exercise provider admission plumbing;
        # only the later frozen SDK counter can establish a real token fit.
        assert all(item.budgeted_input_tokens <= item.max_input_tokens
                   for item in token_counter.measurements)
        assert all(item.requested_output_tokens == 768 for item in token_counter.measurements)
        assert all(item.actual_context_tokens == 8192 for item in token_counter.measurements)

        expense_calls = [item for item in transport.calls if item["turn_tag"] == "expense"]
        debt_calls = [item for item in transport.calls if item["turn_tag"] == "debt"]
        assert [item["stage"] for item in expense_calls] == ["model_selected_read", "model_saw_returned_body"]
        assert [item["stage"] for item in debt_calls] == ["model_selected_read", "model_saw_returned_body"]
        assert all(item["request_sha256"] and item["raw_completion_sha256"] for item in transport.calls)
        assert expense_calls[1]["returned_model_body_sha256"]
        assert debt_calls[1]["returned_model_body_sha256"]
        assert expense_calls[1]["decision"]["citations"] == [
            fact.evidence_ref.value for fact in expense.checkpoint.model_context.read_results[0].body.items
        ]
        assert expense_calls[1]["raw_financial_text_complete"] is True
        assert expense_calls[1]["raw_financial_text_has_base_currency"] is False
        assert debt_calls[1]["raw_financial_text_complete"] is True
        assert debt_calls[1]["raw_financial_text_has_base_currency"] is False
        assert debt_calls[1]["decision"]["citations"] == [
            fact.evidence_ref.value for fact in debt.checkpoint.model_context.read_results[0].body.items
        ]

        expense_events = _request(
            client, "GET", f"/v1/turns/{expense_turn}/events?after_seq=0&limit=100",
        ).json()["events"]
        debt_events = _request(
            client, "GET", f"/v1/turns/{debt_turn}/events?after_seq=0&limit=100",
        ).json()["events"]
        expense_text = next(item["payload"]["text"] for item in expense_events if item["type"] == "message")
        debt_text = next(item["payload"]["text"] for item in debt_events if item["type"] == "message")
        for tag, rendered_text in (("expense", expense_text), ("debt", debt_text)):
            final_call = next(
                item for item in transport.calls
                if item["turn_tag"] == tag and item["stage"] == "model_saw_returned_body"
            )
            final_call["rendered_answer_text"] = rendered_text
            final_call["rendered_answer_sha256"] = hashlib.sha256(rendered_text.encode("utf-8")).hexdigest()
            final_call["renderer_rewrite_applied"] = rendered_text != final_call["raw_financial_text"]
            assert final_call["renderer_rewrite_applied"] is True
        assert "消费记录：Harbor ferry — 37.60 GBP" in expense_text
        assert "付款 Morgan：30.00 GBP" in expense_text
        assert "付款 Sol：7.60 GBP" in expense_text
        assert "分摊 Morgan：5.60 GBP" in expense_text
        assert "分摊 Sol：32.00 GBP" in expense_text
        assert "USD" not in expense_text
        assert "债务记录：Morgan → Sol，18.40 EUR" in debt_text
        assert "债务记录：Sol → Morgan，1200.00 JPY" in debt_text
        assert "settled" not in debt_text.casefold()
        assert not any(item["decision"]["kind"] == "propose" for item in transport.calls)
        for aggregate, final_call in ((expense, expense_calls[1]), (debt, debt_calls[1])):
            persisted_body = aggregate.checkpoint.model_context.read_results[0].body.model_dump(mode="json")
            _verify_returned_body_hash(final_call["returned_model_body_sha256"], persisted_body)

        # Public traffic is counted by the wrapper before dispatch. Local store
        # reads used for terminal assertions do not count as HTTP requests.
        public_http_requests = client.request_count
        assert public_http_requests == 6 and public_http_requests <= client.maximum
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (len(components.runtime._turn_grants) or components.runtime._p2_states):
            time.sleep(0.01)
        assert len(components.runtime._turn_grants) == 0
        assert components.runtime._p2_states == {}
        _export_cpu_evidence(
            os.environ.get("P2_R2_CPU_EVIDENCE_DIR"),
            token_counter.requests, token_counter.measurements, transport.calls, fake_http,
            ledger, client,
        )


def test_r2_generation_ledger_keeps_direct_and_closed_loop_caps_separate() -> None:
    ledger = _R2GenerationLedger()
    for _ in range(9):
        ledger.record_direct()
    for turn_tag in ("expense", "debt"):
        for _ in range(6):
            ledger.record_closed_loop(turn_tag)
    assert ledger.direct == 9
    assert ledger.closed_loop == 12
    assert ledger.total == 21 < ledger.total_limit == 24
    with pytest.raises(AssertionError, match="ledger cap"):
        ledger.record_direct()
    with pytest.raises(AssertionError, match="ledger cap"):
        ledger.record_closed_loop("expense")
    assert ledger.total == 21


def test_r2_generation_ledger_overflow_stops_before_provider_dispatch() -> None:
    class _ProviderSpy:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt: Any) -> str:
            self.calls += 1
            return "unexpected"

    class _Context:
        input_text = "expense closed-loop cap fixture"

    class _Prompt:
        context = _Context()

    ledger = _R2GenerationLedger()
    for _ in range(ledger.per_turn_limit):
        ledger.record_closed_loop("expense")
    provider = _ProviderSpy()
    guarded = _LedgerProvider(provider, ledger)

    with pytest.raises(AssertionError, match="ledger cap"):
        asyncio.run(guarded.generate(_Prompt()))

    assert ledger.by_turn == {"expense": ledger.per_turn_limit}
    assert ledger.closed_loop == ledger.per_turn_limit
    assert ledger.total == ledger.per_turn_limit
    assert provider.calls == 0


def test_r2_provider_failure_stops_without_read_and_cleans_memory_state(tmp_path) -> None:
    client, components, backend, fake_http, provider, transport, token_counter, ledger = _build_client(
        tmp_path / "r2-provider-offline.sqlite3", fail_on_provider_call=1,
    )
    with client:
        session_id = _create_session(client)
        turn_id = _submit(
            client, session_id,
            "For this activity, read the expense records and report each payer and split separately in its original currency.",
        )
        turn = _wait_state(components, turn_id, c.TurnState.WAIT_INPUT)
        assert turn.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
        assert turn.checkpoint.model_calls == 1
        assert turn.checkpoint.read_calls == 0
        assert turn.checkpoint.repair_calls == 0
        assert ledger.total == 1 and ledger.closed_loop == 1
        assert len(transport.attempts) == 1
        assert transport.attempts[0]["attempt"] == 1
        assert len(transport.attempts[0]["request_sha256"]) == 64
        assert transport.attempts[0]["failure"] == "synthetic_offline_before_completion"
        assert not transport.calls
        assert fake_http.read_routes == []
        assert len(token_counter.requests) == 1  # counter ran before the synthetic transport failure
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (
            components.runtime._p2_states or len(components.runtime._turn_grants)
        ):
            time.sleep(0.01)
        assert components.runtime._p2_states == {}
        with pytest.raises(P2GrantError):
            components.runtime._turn_grants.get(OWNER, turn_id)
        assert len(transport.attempts) == 1


def test_r2_renderer_completeness_does_not_mask_raw_model_omission(tmp_path) -> None:
    client, components, backend, fake_http, provider, transport, token_counter, ledger = _build_client(
        tmp_path / "r2-raw-omission.sqlite3", omit_raw_expense_split=True,
    )
    transport.release.set()
    with client:
        session_id = _create_session(client)
        turn_id = _submit(
            client, session_id,
            "For this activity, read the expense records and report each payer and split separately in its original currency.",
        )
        turn = _wait_terminal(components, turn_id)
        assert turn.record.turn.state == c.TurnState.COMPLETED
        assert (turn.checkpoint.model_calls, turn.checkpoint.read_calls) == (2, 1)
        raw_answer = next(item for item in transport.calls if item["stage"] == "model_saw_returned_body")
        assert raw_answer["raw_financial_text_complete"] is False
        assert "Morgan omitted" in raw_answer["raw_financial_text"]
        assert "Morgan 5.60 GBP" not in raw_answer["raw_financial_text"]

        events = _request(
            client, "GET", f"/v1/turns/{turn_id}/events?after_seq=0&limit=100",
        ).json()["events"]
        rendered = next(item["payload"]["text"] for item in events if item["type"] == "message")
        assert "分摊 Morgan：5.60 GBP" in rendered
        assert "分摊 Sol：32.00 GBP" in rendered
        assert rendered != raw_answer["raw_financial_text"]
        assert ledger.total == 2 and ledger.by_turn == {"expense": 2}

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (len(components.runtime._turn_grants) or components.runtime._p2_states):
            time.sleep(0.01)
        assert len(components.runtime._turn_grants) == 0
        assert components.runtime._p2_states == {}


def test_r2_dynamic_body_gate_rejects_mismatch() -> None:
    persisted_body = {"kind": "expenses", "items": [{"original_amount": "37.60"}]}
    matching_hash = _sha256_json(persisted_body)
    assert _verify_returned_body_hash(matching_hash, persisted_body) == matching_hash
    with pytest.raises(AssertionError, match="does not match"):
        _verify_returned_body_hash(hashlib.sha256(b"different body").hexdigest(), persisted_body)


def test_r2_public_http_limit_stops_before_client_dispatch() -> None:
    class _RequestSpy:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, method: str, url: str, **kwargs: Any) -> int:
            self.calls += 1
            return self.calls

    spy = _RequestSpy()
    client = _BoundedPublicClient(spy, maximum=1)  # type: ignore[arg-type]
    assert client.request("GET", "/v1/sessions") == 1
    with pytest.raises(AssertionError, match="cap reached before client dispatch"):
        client.request("GET", "/v1/sessions")
    assert spy.calls == 1 and client.request_count == 1

