"""One-request, synthetic Teacher visible-text readiness probe; no raw response persistence."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROVIDER_DIR = REPO / "scripts" / "ai_teacher_generator"
if str(PROVIDER_DIR) not in sys.path:
    sys.path.insert(0, str(PROVIDER_DIR))

from live_provider import LiveProviderError, ProviderConfig, load_env  # noqa: E402

EXPECTED_ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
EXPECTED_MODEL = "deepseek-v4.1-flash"
USER_AGENT = "shared-ledger-t1-teacher-readiness/0.1.0"
MAX_REQUESTS = 1
TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_TOKENS = 2048
MAX_RESPONSE_BYTES = 256_000
PROMPT_PATH = HERE / "prompt-v1.json"
PREREG_PATH = HERE / "preregistration.json"
PREREG_SHA_PATH = HERE / "preregistration.sha256"


class ReadinessError(RuntimeError):
    pass


class RequestBudget:
    def __init__(self, limit: int = MAX_REQUESTS):
        self.limit = limit
        self.used = 0

    def reserve(self) -> int:
        if self.used >= self.limit:
            raise ReadinessError("One-request budget exhausted; no request was sent.")
        self.used += 1
        return self.used


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def strict_json_loads(raw: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError("Non-standard JSON value.")

    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def endpoint_for(config: ProviderConfig) -> str:
    base = config.base_url.rstrip("/")
    lowered = base.lower()
    if lowered.endswith("/chat/completions"):
        endpoint = base
    elif lowered.endswith("/zen/go"):
        endpoint = base + "/v1/chat/completions"
    elif lowered.endswith("/v1"):
        endpoint = base + "/chat/completions"
    else:
        endpoint = base + "/v1/chat/completions"
    if endpoint != EXPECTED_ENDPOINT or config.provider.lower() != "opencode" or config.model != EXPECTED_MODEL:
        raise ReadinessError("Configured route/provider/model differs from the preregistered target; no request was sent.")
    return endpoint


def load_prompt() -> dict[str, Any]:
    value = strict_json_loads(PROMPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("messages"), list) or len(value["messages"]) != 2:
        raise ReadinessError("Prompt structure is invalid; no request was sent.")
    for message in value["messages"]:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user"} or not isinstance(message.get("content"), str):
            raise ReadinessError("Prompt message is invalid; no request was sent.")
    expected = value.get("expected_cases")
    if not isinstance(expected, list) or len(expected) != 3:
        raise ReadinessError("Prompt case schema is invalid; no request was sent.")
    return value


def source_files() -> dict[str, Path]:
    return {
        "runner": HERE / "runner.py",
        "prompt": PROMPT_PATH,
        "fake_http_tests": HERE / "tests" / "test_runner.py",
        "legacy_provider_config_reader_read_only": PROVIDER_DIR / "live_provider.py",
        "teacher_status_t1_v1_read_only": REPO / "agent" / "docs" / "t1" / "TEACHER_STATUS-T1-v1.md",
        "business_acceptance_t1_read_only": REPO / "agent" / "docs" / "t1" / "BUSINESS_ACCEPTANCE.md",
        "t1_freeze_read_only": REPO / "agent" / "docs" / "t1" / "FREEZE-T1.md",
    }


def source_hashes() -> dict[str, str]:
    return {name: sha256_bytes(path.read_bytes()) for name, path in source_files().items()}


def safe_config(config: ProviderConfig) -> dict[str, Any]:
    projection = {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "temperature": config.temperature,
        "api_key_present": bool(config.api_key),
    }
    return {
        "provider": config.provider,
        "model": config.model,
        "route": EXPECTED_ENDPOINT,
        "temperature": config.temperature,
        "api_key_present": bool(config.api_key),
        "credential_value_recorded_or_hashed": False,
        "nonsecret_projection_sha256": sha256_json(projection),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_preregistration(config_path: Path, *, created_utc: str, d_output: str) -> str:
    if PREREG_PATH.exists() or PREREG_SHA_PATH.exists():
        raise ReadinessError("Readiness preregistration already exists; refusing to overwrite it.")
    config = load_env(config_path)
    endpoint_for(config)
    prompt = load_prompt()
    prereg = {
        "preregistration_version": "t1-teacher-readiness-preregistration-v1",
        "status": "FROZEN_BEFORE_EXTERNAL_REQUEST",
        "created_utc": created_utc,
        "local_date": "2026-10-11",
        "local_timezone": "Asia/Shanghai",
        "purpose": "one bounded visible-text readiness check using three new synthetic business states",
        "configuration": safe_config(config),
        "credential_source": {
            "path": "D:/project/Android/shared-ledger/scripts/ai_teacher_generator/.env",
            "read_only": True,
            "loaded_into_memory_only": True,
            "secret_value_recorded_or_hashed": False,
        },
        "route_and_identity": {
            "endpoint": EXPECTED_ENDPOINT,
            "configured_model": EXPECTED_MODEL,
            "user_agent": USER_AGENT,
            "session_header": "x-opencode-session",
            "session_id": "one randomly generated UUID, stable for this single request",
            "response_request_id": "record the allowlisted envelope id when returned",
        },
        "request_limits": {
            "max_total_posts": MAX_REQUESTS,
            "timeout_seconds": TIMEOUT_SECONDS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "automatic_retry": False,
            "fallback": False,
        },
        "output_contract": {
            "top_level_exact_keys": ["cases"],
            "case_count": 3,
            "case_exact_keys": ["case_id", "task_conclusion", "visible_text"],
            "case_ids_and_conclusions": prompt["expected_cases"],
            "visible_text_character_limit": 80,
            "visible_text_must_be_nonempty": True,
            "no_tools_or_business_writes": True,
            "no_tool_results_or_completed_write_claims": True,
            "no_hidden_reasoning_requested_or_persisted": True,
        },
        "interpretation": {
            "success_scope": "three synthetic candidate texts and strict schema only",
            "human_semantic_review_required": True,
            "teacher_quality_pass": False,
            "student_quality": "DEFERRED",
            "training_eligible": False,
            "train_validation_sealed_data_read": False,
            "student_or_gpu_used": False,
            "business_database_used": False,
        },
        "prompt_sha256": sha256_bytes(PROMPT_PATH.read_bytes()),
        "source_sha256": source_hashes(),
        "evidence_output_directory": d_output,
    }
    write_json(PREREG_PATH, prereg)
    digest = sha256_bytes(PREREG_PATH.read_bytes())
    PREREG_SHA_PATH.write_text(f"{digest}  {PREREG_PATH.name}\n", encoding="ascii")
    return digest


def verify_preregistration(config: ProviderConfig) -> tuple[dict[str, Any], str]:
    if not PREREG_PATH.is_file() or not PREREG_SHA_PATH.is_file():
        raise ReadinessError("Frozen readiness preregistration is missing; no request was sent.")
    digest = sha256_bytes(PREREG_PATH.read_bytes())
    expected_digest = PREREG_SHA_PATH.read_text(encoding="ascii").split()[0]
    if digest != expected_digest:
        raise ReadinessError("Frozen readiness preregistration hash mismatch; no request was sent.")
    prereg = strict_json_loads(PREREG_PATH.read_text(encoding="utf-8"))
    if prereg.get("status") != "FROZEN_BEFORE_EXTERNAL_REQUEST":
        raise ReadinessError("Readiness preregistration status invalid; no request was sent.")
    if prereg.get("source_sha256") != source_hashes() or prereg.get("prompt_sha256") != sha256_bytes(PROMPT_PATH.read_bytes()):
        raise ReadinessError("Readiness source/prompt hash mismatch; no request was sent.")
    if prereg.get("configuration") != safe_config(config):
        raise ReadinessError("Non-secret configuration projection mismatch; no request was sent.")
    limits = prereg.get("request_limits", {})
    if limits != {"max_total_posts": 1, "timeout_seconds": 60.0, "max_output_tokens": 2048, "max_response_bytes": 256000, "automatic_retry": False, "fallback": False}:
        raise ReadinessError("Readiness request limits differ from preregistration; no request was sent.")
    return prereg, digest


def build_payload(config: ProviderConfig, prompt: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": config.model,
        "messages": prompt["messages"],
        "temperature": config.temperature,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "response_format": {"type": "json_object"},
    }


def redact_error(message: str, secret: str) -> str:
    result = message.replace(secret, "[REDACTED]") if secret else message
    result = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", result)
    result = re.sub(r'(?i)("(?:api[_-]?key|token|authorization)"\s*:\s*")[^"\\]*(")', r"\1[REDACTED]\2", result)
    return result[:400]


def _small_error_message(body: bytes, secret: str) -> str:
    try:
        value = strict_json_loads(body[:4096].decode("utf-8", errors="replace"))
        error = value.get("error") if isinstance(value, dict) else None
        message = error.get("message") if isinstance(error, dict) else error if isinstance(error, str) else None
    except (ValueError, json.JSONDecodeError):
        message = None
    return redact_error(message if isinstance(message, str) and message else "HTTP error body omitted.", secret)


def post_once(
    config: ProviderConfig,
    prompt: dict[str, Any],
    *,
    session_id: str,
    budget: RequestBudget,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    endpoint = endpoint_for(config)
    payload = build_payload(config, prompt)
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-opencode-session": session_id,
        },
        method="POST",
    )
    call_number = budget.reserve()
    started = time.monotonic()
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(response.status)
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {
            "call_number": call_number,
            "http_status": int(exc.code),
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": _small_error_message(exc.read(4096), config.api_key),
            "response_body_saved": False,
        }
    except (TimeoutError, urllib.error.URLError):
        return {
            "call_number": call_number,
            "http_status": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": "Provider request failed before an HTTP response.",
            "response_body_saved": False,
        }
    result: dict[str, Any] = {
        "call_number": call_number,
        "http_status": status,
        "duration_seconds": round(time.monotonic() - started, 3),
        "response_body_bytes": len(body),
        "response_body_saved": False,
    }
    if len(body) > MAX_RESPONSE_BYTES:
        result["error"] = "Response exceeded the preregistered byte limit."
        return result
    try:
        envelope = strict_json_loads(body.decode("utf-8", errors="replace"))
    except (ValueError, json.JSONDecodeError):
        result["error"] = "Response envelope was not strict JSON."
        return result
    if not isinstance(envelope, dict):
        result["error"] = "Response envelope was not an object."
        return result
    # Keep allowlisted metadata only. Never access or serialize reasoning_content values.
    result["provider_returned_model_label"] = envelope.get("model") if isinstance(envelope.get("model"), str) else None
    result["server_request_id"] = envelope.get("id") if isinstance(envelope.get("id"), str) else None
    choices = envelope.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    result["finish_reason"] = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
    usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    result["usage"] = {
        key: usage[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")
        if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool) and usage[key] >= 0
    }
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    result["reasoning_content_field_present"] = "reasoning_content" in message
    result["tool_calls_field_present"] = "tool_calls" in choice or "tool_calls" in message
    visible_content = message.get("content")
    if not isinstance(visible_content, str):
        result["visible_content"] = None
        result["error"] = "Completion has no visible text content."
        return result
    safe_content = redact_error(visible_content, config.api_key)
    result["credential_redaction_applied_to_visible_content"] = safe_content != visible_content
    result["visible_content"] = safe_content
    result["visible_content_sha256"] = sha256_bytes(safe_content.encode("utf-8"))
    return result


FORBIDDEN_WRITE_CLAIMS = ("已创建", "创建成功", "已保存", "已记账", "已写入", "操作成功", "已执行")


def validate_candidate(parsed: Any, expected_cases: list[dict[str, Any]]) -> dict[str, Any]:
    result = {"schema_valid": False, "task_conclusions_match": False, "visible_text_valid": False, "no_completed_write_claim": False, "manual_semantic_review_required": True}
    if not isinstance(parsed, dict) or set(parsed) != {"cases"} or not isinstance(parsed["cases"], list) or len(parsed["cases"]) != 3:
        return result
    expected_by_id = {case["case_id"]: case["task_conclusion"] for case in expected_cases}
    seen: set[str] = set()
    schema_valid = True
    conclusion_match = True
    visible_valid = True
    no_write_claim = True
    for case in parsed["cases"]:
        if not isinstance(case, dict) or set(case) != {"case_id", "task_conclusion", "visible_text"}:
            schema_valid = False
            continue
        case_id = case.get("case_id")
        text = case.get("visible_text")
        if not isinstance(case_id, str) or case_id not in expected_by_id or case_id in seen or not isinstance(text, str):
            schema_valid = False
            continue
        seen.add(case_id)
        if case["task_conclusion"] != expected_by_id[case_id]:
            conclusion_match = False
        if not text.strip() or len(text) > 80 or "工具" in text or "function call" in text.lower():
            visible_valid = False
        if any(phrase in text for phrase in FORBIDDEN_WRITE_CLAIMS):
            no_write_claim = False
    schema_valid = schema_valid and seen == set(expected_by_id)
    schema_valid = schema_valid and [case.get("case_id") for case in parsed["cases"] if isinstance(case, dict)] == [case["case_id"] for case in expected_cases]
    result.update({
        "schema_valid": schema_valid,
        "task_conclusions_match": conclusion_match and schema_valid,
        "visible_text_valid": visible_valid and schema_valid,
        "no_completed_write_claim": no_write_claim and schema_valid,
    })
    return result


def consume_visible_content(result: dict[str, Any], expected_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Consume only validated short candidate text; discard arbitrary visible payloads."""
    visible_content = result.pop("visible_content", None)
    if not isinstance(visible_content, str):
        result["visible_content_character_count"] = None
        result["visible_content_strict_json_valid"] = False
        result["validation"] = {
            "schema_valid": False,
            "task_conclusions_match": False,
            "visible_text_valid": False,
            "no_completed_write_claim": False,
            "manual_semantic_review_required": True,
        }
        return result
    result["visible_content_character_count"] = len(visible_content)
    try:
        parsed = strict_json_loads(visible_content)
    except (ValueError, json.JSONDecodeError):
        result["visible_content_strict_json_valid"] = False
        result["validation"] = {
            "schema_valid": False,
            "task_conclusions_match": False,
            "visible_text_valid": False,
            "no_completed_write_claim": False,
            "manual_semantic_review_required": True,
        }
        result["error"] = "Visible completion was not strict JSON; text omitted."
        return result
    result["visible_content_strict_json_valid"] = True
    validation = validate_candidate(parsed, expected_cases)
    result["validation"] = validation
    candidate_is_safe = all(validation.get(key) is True for key in (
        "schema_valid", "task_conclusions_match", "visible_text_valid", "no_completed_write_claim"
    ))
    if not candidate_is_safe:
        result["candidate_quarantined"] = True
        result["error"] = "Visible JSON did not satisfy the frozen three-case candidate contract; text omitted."
        return result
    result["candidate"] = parsed
    result["candidate_text_sha256"] = {
        case["case_id"]: sha256_bytes(case["visible_text"].encode("utf-8"))
        for case in parsed["cases"]
    }
    return result


def safe_config_record(config: ProviderConfig) -> dict[str, Any]:
    return safe_config(config)


def run(config_path: Path, output: Path) -> dict[str, Any]:
    config = load_env(config_path)
    endpoint_for(config)
    prereg, prereg_hash = verify_preregistration(config)
    if output.exists():
        raise ReadinessError("Evidence output path already exists; refusing to overwrite it.")
    output.mkdir(parents=True, exist_ok=False)
    prompt = load_prompt()
    session_id = str(uuid.uuid4())
    budget = RequestBudget()
    started_utc = utc_now()
    payload = build_payload(config, prompt)
    write_json(output / "request.json", {
        "endpoint": EXPECTED_ENDPOINT,
        "payload": payload,
        "request_identity": {"x_opencode_session": session_id, "user_agent": USER_AGENT},
    })
    result = post_once(config, prompt, session_id=session_id, budget=budget)
    result = consume_visible_content(result, prompt["expected_cases"])
    good_usage = all(k in result.get("usage", {}) for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
    validation = result.get("validation", {})
    ready = (
        result.get("http_status") == 200
        and result.get("finish_reason") == "stop"
        and good_usage
        and bool(result.get("server_request_id"))
        and bool(result.get("provider_returned_model_label"))
        and validation.get("schema_valid") is True
        and validation.get("task_conclusions_match") is True
        and validation.get("visible_text_valid") is True
        and validation.get("no_completed_write_claim") is True
        and result.get("tool_calls_field_present") is False
        and result.get("credential_redaction_applied_to_visible_content") is False
    )
    manifest = {
        "probe": "t1-teacher-visible-text-readiness-v1",
        "started_utc": started_utc,
        "completed_utc": utc_now(),
        "preregistration_sha256": prereg_hash,
        "source_sha256": prereg["source_sha256"],
        "prompt_sha256": prereg["prompt_sha256"],
        "config": safe_config_record(config),
        "request_identity": {"x_opencode_session": session_id, "stable_for_request": True, "server_request_id": result.get("server_request_id")},
        "limits": {"max_requests": 1, "requests_sent": budget.used, "timeout_seconds": TIMEOUT_SECONDS, "max_output_tokens": MAX_OUTPUT_TOKENS, "max_response_bytes": MAX_RESPONSE_BYTES, "retries": 0, "fallbacks": 0},
        "status": "TEXT_CANDIDATE_SCHEMA_READY" if ready else "TEXT_READINESS_FAILED_OR_INCOMPLETE",
        "teacher_data_quality": "NOT_ASSESSED",
        "student_model_quality": "DEFERRED",
        "human_semantic_review_pending": True,
        "training_eligible": False,
        "raw_response_saved": False,
        "reasoning_content_value_saved": False,
        "candidate_texts_are_not_training_data": True,
        "result": result,
    }
    write_json(output / "run_manifest.json", manifest)
    return manifest


def cli_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    result = manifest["result"]
    return {
        "status": manifest["status"],
        "requests_sent": manifest["limits"]["requests_sent"],
        "http_status": result.get("http_status"),
        "duration_seconds": result.get("duration_seconds"),
        "provider_returned_model_label": result.get("provider_returned_model_label"),
        "finish_reason": result.get("finish_reason"),
        "usage": result.get("usage", {}),
        "server_request_id": result.get("server_request_id"),
        "reasoning_content_field_present": result.get("reasoning_content_field_present"),
        "validation": result.get("validation"),
        "visible_candidate": result.get("candidate") if manifest["status"] == "TEXT_CANDIDATE_SCHEMA_READY" else None,
        "candidate_quarantined": result.get("candidate_quarantined", bool(result.get("candidate") and manifest["status"] != "TEXT_CANDIDATE_SCHEMA_READY")),
        "error": result.get("error"),
    }


def main() -> int:
    config_path = Path(r"D:\project\Android\shared-ledger\scripts\ai_teacher_generator\.env")
    output = Path(r"D:\AI\runs\shared-ledger\t1-teacher-readiness-20261011")
    try:
        manifest = run(config_path, output)
    except (LiveProviderError, ReadinessError, OSError, ValueError) as exc:
        print(json.dumps({"status": "NOT_AVAILABLE_OR_NOT_RUN", "requests_sent": 0, "error": str(exc)[:300]}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(cli_summary(manifest), ensure_ascii=False, sort_keys=True))
    return 0 if manifest["status"] == "TEXT_CANDIDATE_SCHEMA_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
