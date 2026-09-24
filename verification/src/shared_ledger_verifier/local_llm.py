"""One-shot LM Studio connection and Scenario JSON v1 capability probe.

This module never executes a generated scenario or calls Supabase/Judge.
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .loader import ScenarioValidationError, load_scenario
from .models import CreateExpense, TargetedRepayment
from .runner import _business_logic_commit
from .supabase import load_local_env, verification_root


DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_TIMEOUT = 180.0
_QWEN_35_9B = re.compile(r"qwen.*3[._-]?5.*9b", re.IGNORECASE)
_MAX_RESPONSE_BYTES = 2_000_000


class LocalLLMError(RuntimeError):
    """A classified probe failure; response bodies and credentials are never exposed."""

    def __init__(self, category: str, *, http_status: int | None = None,
                 elapsed_seconds: float | None = None, usage: dict[str, int] | None = None):
        self.category = category
        self.http_status = http_status
        self.elapsed_seconds = elapsed_seconds
        self.usage = usage or {}
        super().__init__(category)


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class Completion:
    content: str
    http_status: int
    elapsed_seconds: float
    usage: dict[str, int]


Transport = Callable[[Request, float], HTTPResponse]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _transport(request: Request, timeout: float) -> HTTPResponse:
    # Do not let a local token follow proxies or redirects outside loopback.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return HTTPResponse(response.status, response.read(_MAX_RESPONSE_BYTES + 1))
    except HTTPError as error:
        return HTTPResponse(error.code, error.read(_MAX_RESPONSE_BYTES + 1))


def _base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise LocalLLMError("INVALID_CONFIG") from None
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or port is None or parsed.path != "/v1" or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise LocalLLMError("INVALID_CONFIG")
    return value


def _json_object(body: bytes) -> dict[str, Any]:
    if len(body) > _MAX_RESPONSE_BYTES:
        raise LocalLLMError("INVALID_JSON")
    try:
        parsed = json.loads(body.decode("utf-8"), parse_constant=lambda _: _reject_constant())
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise LocalLLMError("INVALID_JSON") from None
    if not isinstance(parsed, dict):
        raise LocalLLMError("SCHEMA_MISMATCH")
    return parsed


def _reject_constant() -> Any:
    raise ValueError("non-JSON constant")


class LocalLLMClient:
    """Minimal non-streaming OpenAI-compatible client for loopback LM Studio."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = "", api_key: str = "",
                 timeout: float = DEFAULT_TIMEOUT, transport: Transport | None = None):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise LocalLLMError("INVALID_CONFIG")
        self.base_url = _base_url(base_url)
        self.model = model.strip()
        self._api_key = api_key.strip()
        self.timeout = float(timeout)
        self._transport = transport or _transport

    @classmethod
    def from_env(cls, *, transport: Transport | None = None) -> "LocalLLMClient":
        load_local_env()
        timeout_raw = os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "").strip()
        try:
            timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT
        except ValueError:
            raise LocalLLMError("INVALID_CONFIG") from None
        return cls(
            base_url=os.environ.get("LOCAL_LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL,
            model=os.environ.get("LOCAL_LLM_MODEL", ""),
            api_key=os.environ.get("LOCAL_LLM_API_KEY", ""),
            timeout=timeout,
            transport=transport,
        )

    def _request(self, path: str, *, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], int, float]:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        started = time.monotonic()
        try:
            response = self._transport(request, self.timeout)
        except (TimeoutError, socket.timeout):
            raise LocalLLMError("TIMEOUT") from None
        except (URLError, OSError) as error:
            if isinstance(getattr(error, "reason", None), (TimeoutError, socket.timeout)):
                raise LocalLLMError("TIMEOUT") from None
            raise LocalLLMError("NETWORK_ERROR") from None
        elapsed = round(time.monotonic() - started, 3)
        if response.status != 200:
            body_lower = response.body.lower()
            category = ("CONTEXT_TOO_SMALL" if response.status in {400, 413, 422}
                        and b"context" in body_lower else "HTTP_ERROR")
            raise LocalLLMError(category, http_status=response.status, elapsed_seconds=elapsed)
        return _json_object(response.body), response.status, elapsed

    def models(self) -> tuple[list[str], int, float]:
        payload, status, elapsed = self._request("/models")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise LocalLLMError("SCHEMA_MISMATCH")
        ids = [row.get("id") for row in rows if isinstance(row, dict)]
        if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(rows):
            raise LocalLLMError("SCHEMA_MISMATCH")
        return ids, status, elapsed

    def select_model(self, ids: list[str]) -> str:
        matches = [value for value in ids if _QWEN_35_9B.search(value)]
        if self.model:
            if self.model not in matches:
                raise LocalLLMError("LOCAL_MODEL_NOT_AVAILABLE")
            return self.model
        if len(matches) != 1:
            raise LocalLLMError("LOCAL_MODEL_NOT_AVAILABLE")
        self.model = matches[0]
        return self.model

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int,
                 response_format: dict[str, Any] | None = None) -> Completion:
        if not self.model:
            raise LocalLLMError("LOCAL_MODEL_NOT_AVAILABLE")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        response, status, elapsed = self._request("/chat/completions", payload=payload)
        raw_usage = response.get("usage")
        usage = {key: raw_usage[key] for key in ("prompt_tokens", "completion_tokens")
                 if isinstance(raw_usage, dict) and type(raw_usage.get(key)) is int and raw_usage[key] >= 0}
        try:
            content = response["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise LocalLLMError("EMPTY_RESPONSE", http_status=status, elapsed_seconds=elapsed, usage=usage) from None
        if not isinstance(content, str) or not content.strip():
            raise LocalLLMError("EMPTY_RESPONSE", http_status=status, elapsed_seconds=elapsed, usage=usage)
        return Completion(content, status, elapsed, usage)


_SMALL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok"]},
        "value": {"type": "integer"},
    },
    "required": ["status", "value"],
    "additionalProperties": False,
}


def _response_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def _scenario_schema(kind: str) -> dict[str, Any]:
    """The requested operation subset; the existing Loader remains authoritative."""

    ref = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"}
    money = {"type": "string", "pattern": "^[0-9]+(?:\\.[0-9]{1,4})?$"}
    operation: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "enum": ["create_expense"] if kind == "simple" else ["create_expense", "targeted_repayment"]},
            "ref": ref,
            "title": {"type": "string"},
            "amount": money,
            "currency": {"type": "string", "enum": ["CNY"]},
            "payments": {"type": "object", "additionalProperties": money},
            "split_method": {"type": "string", "enum": ["aa", "manual"]},
            "splits": {"type": "object", "additionalProperties": money},
            "aa_participants": {"type": "array", "items": ref},
            "from_participant": ref,
            "to_participant": ref,
            "target_expense_refs": {"type": "array", "items": ref},
        },
        "required": ["type", "ref"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "scenario_id": ref,
            "description": {"type": "string"},
            "activity": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": ["normal"]},
                    "base_currency": {"type": "string", "enum": ["CNY"]},
                    "multi_currency_enabled": {"type": "boolean", "enum": [False]},
                },
                "required": ["type", "base_currency", "multi_currency_enabled"],
            },
            "participants": {"type": "array", "items": ref, "minItems": 3, "maxItems": 3 if kind == "simple" else 4},
            "operations": {"type": "array", "items": operation, "minItems": 1 if kind == "simple" else 2,
                           "maxItems": 1 if kind == "simple" else 2},
        },
        "required": ["schema_version", "scenario_id", "description", "activity", "participants", "operations"],
    }


def _parse_content(content: str) -> dict[str, Any]:
    return _json_object(content.encode("utf-8"))


def _validate_theme(path: Path, kind: str) -> None:
    scenario = load_scenario(path)
    if scenario.activity.type != "normal" or scenario.activity.base_currency != "CNY" or scenario.activity.multi_currency_enabled:
        raise ScenarioValidationError("generated activity does not match the requested CNY normal activity")
    if kind == "simple":
        if (len(scenario.participants) != 3 or len(scenario.operations) != 1
                or not isinstance(scenario.operations[0], CreateExpense)):
            raise ScenarioValidationError("generated simple operation shape does not match")
        expense = scenario.operations[0]
        if (expense.split_method != "aa" or len(expense.payments) not in {2, 3}
                or set(expense.aa_participants) != set(scenario.participants)):
            raise ScenarioValidationError("generated multi-payer AA shape does not match")
        return
    if (len(scenario.participants) not in {3, 4} or len(scenario.operations) != 2
            or not isinstance(scenario.operations[0], CreateExpense)
            or not isinstance(scenario.operations[1], TargetedRepayment)):
        raise ScenarioValidationError("generated combined operation shape does not match")
    expense, repayment = scenario.operations
    if (expense.currency != "CNY" or repayment.currency != "CNY"
            or expense.split_method != "manual" or expense.splits is None
            or repayment.target_expense_refs != (expense.ref,)):
        raise ScenarioValidationError("generated targeted expense reference does not match")
    debtor_due = expense.splits.get(repayment.from_participant, 0) - expense.payments.get(repayment.from_participant, 0)
    creditor_due = expense.payments.get(repayment.to_participant, 0) - expense.splits.get(repayment.to_participant, 0)
    if not 0 < repayment.amount < min(debtor_due, creditor_due):
        raise ScenarioValidationError("generated TARGETED repayment is not partial against the selected debt")


def _generation_messages(business_logic: str, kind: str) -> list[dict[str, str]]:
    common = (
        "Return only one Scenario JSON v1 object. No Markdown, explanations, UUID, financial_version, "
        "request_id, SQL, expected_result, database fields, or Judge verdict. All money values must "
        "be JSON decimal strings with at most one fractional digit for CNY. Use exactly the Scenario "
        "v1 envelope: schema_version, scenario_id, description, activity, participants, operations. "
        "Activity must be normal, base_currency CNY, multi_currency_enabled false.\n\n"
    )
    if kind == "simple":
        task = (
            "Generate one NEW simple scenario with exactly three participants A, B, C and exactly "
            "one create_expense operation. Two or three participants pay positive CNY amounts that "
            "sum exactly to the expense amount. Set split_method to aa and aa_participants to all "
            "three participants. No repayment, refund, or prepayment."
        )
    else:
        task = (
            "Generate one NEW scenario with three or four participants A, B, C (optionally D), "
            "and exactly two operations in order: create_expense, then targeted_repayment. "
            "For the expense, A alone pays 100.0 CNY, B alone bears 100.0 CNY using manual splits. "
            "For the repayment, B pays A 40.0 CNY, target_expense_refs contains only the earlier "
            "expense ref. C (and optional D) may be members without a share. The TARGETED repayment "
            "must be strictly smaller than B's 100.0 CNY debt."
        )
    return [
        {"role": "system", "content": "Generate valid Shared Ledger Scenario JSON v1 from the complete business rules. Use final message.content only."},
        {"role": "user", "content": common + task + "\n\nComplete BUSINESS_LOGIC.md:\n" + business_logic},
    ]


def run_probe(*, client: LocalLLMClient | None = None, output_dir: Path | None = None,
              business_logic_path: Path | None = None) -> dict[str, Any]:
    """Perform one request per step, save safe artifacts, and stop on first failure."""

    client = client or LocalLLMClient.from_env()
    output_dir = output_dir or verification_root() / "local_llm_probe"
    business_logic_path = business_logic_path or verification_root().parent / "docs/backend/BUSINESS_LOGIC.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": client.base_url,
        "request_timeout_seconds": client.timeout,
        "model": None,
        "server_reachable": False,
        "model_count": None,
        "model_ids": [],
        "chat_completion_ok": False,
        "structured_output_supported": False,
        "business_logic_characters": None,
        "business_logic_commit": _business_logic_commit(),
        "simple_scenario_valid": None,
        "combined_scenario_valid": None,
        "steps": {},
        "error_category": None,
    }
    current_step = "models"

    def save() -> dict[str, Any]:
        (output_dir / "probe_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result

    try:
        ids, status, elapsed = client.models()
        result.update(server_reachable=True, model_count=len(ids), model_ids=ids)
        result["steps"]["models"] = {"http_status": status, "elapsed_seconds": elapsed}
        result["model"] = client.select_model(ids)

        current_step = "chat"
        completion = client.complete(
            [{"role": "user", "content": 'Reply with exactly {"status":"ok"} and nothing else.'}],
            max_tokens=256,
        )
        parsed = _parse_content(completion.content)
        if parsed != {"status": "ok"}:
            raise LocalLLMError("SCHEMA_MISMATCH")
        result["chat_completion_ok"] = True
        result["steps"]["chat"] = _step(completion)

        current_step = "structured"
        completion = client.complete(
            [{"role": "user", "content": 'Return status ok and any integer value. JSON only.'}],
            max_tokens=768,
            response_format=_response_format("lmstudio_probe", _SMALL_SCHEMA),
        )
        parsed = _parse_content(completion.content)
        if set(parsed) != {"status", "value"} or parsed["status"] != "ok" or type(parsed["value"]) is not int:
            raise LocalLLMError("SCHEMA_MISMATCH")
        result["structured_output_supported"] = True
        result["steps"]["structured"] = _step(completion)

        try:
            business_logic = business_logic_path.read_text(encoding="utf-8")
        except OSError:
            raise LocalLLMError("BUSINESS_LOGIC_UNAVAILABLE") from None
        result["business_logic_characters"] = len(business_logic)

        for kind in ("simple", "combined"):
            current_step = kind
            completion = client.complete(
                _generation_messages(business_logic, kind),
                max_tokens=2048,
                response_format=_response_format(f"shared_ledger_{kind}_scenario_v1", _scenario_schema(kind)),
            )
            result["steps"][kind] = _step(completion)
            path = output_dir / f"generated_{kind}.json"
            # Preserve exactly the model's final content; never repair it.
            path.write_text(completion.content, encoding="utf-8")
            try:
                _validate_theme(path, kind)
            except ScenarioValidationError as error:
                result[f"{kind}_scenario_valid"] = False
                result["error_category"] = "GENERATION_INVALID"
                result["loader_error"] = str(error)[:240]
                return save()
            result[f"{kind}_scenario_valid"] = True
        return save()
    except LocalLLMError as error:
        result["error_category"] = error.category
        result["failed_step"] = current_step
        if error.http_status is not None:
            failed_step: dict[str, Any] = {"http_status": error.http_status}
            if error.elapsed_seconds is not None:
                failed_step["elapsed_seconds"] = error.elapsed_seconds
            failed_step.update(error.usage)
            result["steps"].setdefault(current_step, failed_step)
        if error.category == "CONTEXT_TOO_SMALL":
            result["context_recommendation"] = "Use at least a 32K-token context for the complete business rules and generated JSON; do not truncate the rules."
        if error.http_status is not None:
            result["http_status"] = error.http_status
        return save()


def _step(completion: Completion) -> dict[str, Any]:
    step: dict[str, Any] = {"http_status": completion.http_status,
                            "elapsed_seconds": completion.elapsed_seconds}
    step.update(completion.usage)
    return step
