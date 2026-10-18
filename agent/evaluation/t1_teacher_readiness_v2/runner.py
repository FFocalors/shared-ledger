"""Isolated one-request synthetic Teacher text-readiness v2 probe.

Successful visible completion is never passed through the bounded error-message
sanitizer. Raw provider bodies and hidden reasoning stay in memory only.
"""
from __future__ import annotations

import hashlib
import json
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
USER_AGENT = "shared-ledger-t1-teacher-readiness-v2/0.1.0"
MAX_REQUESTS = 1
TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_TOKENS = 2048
MAX_RESPONSE_BYTES = 256_000
PROMPT_PATH = HERE / "prompt-v2.json"
PREREG_PATH = HERE / "preregistration.json"
PREREG_SHA_PATH = HERE / "preregistration.sha256"
CONFIG_PATH = Path(r"D:\project\Android\shared-ledger\scripts\ai_teacher_generator\.env")
DEFAULT_OUTPUT = Path(r"D:\AI\runs\shared-ledger\t1-teacher-readiness-v2-20261011")

TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bearer_token_pattern", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    ("openai_style_token_pattern", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token_pattern", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
)
FORBIDDEN_WRITE_CLAIMS = ("已创建", "创建成功", "已保存", "已记账", "已写入", "操作成功", "已执行")
EXPECTED_CASE_IDS = (
    "activity-meadow-prepay",
    "expense-tea-84-two-payers",
    "expense-locked-memo",
)


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


def detected_token_patterns(text: str) -> list[str]:
    """Return pattern names only; never return or capture a token value."""
    return [name for name, pattern in TOKEN_PATTERNS if pattern.search(text)]


def iter_string_values(value: Any):
    """Yield decoded strings for sensitivity checks without retaining them."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from iter_string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_string_values(item)


def decoded_sensitive_types(value: Any, secret: str) -> list[str]:
    found: set[str] = set()
    for item in iter_string_values(value):
        if secret and secret in item:
            found.add("exact_credential_echo")
        found.update(detected_token_patterns(item))
    return sorted(found)


def scrub_sensitive(text: str, secret: str) -> tuple[str, list[str]]:
    """Sanitize error text only; successful completion is not sent through this."""
    detections: list[str] = []
    if secret and secret in text:
        detections.append("exact_credential_echo")
        text = text.replace(secret, "[REDACTED_CREDENTIAL]")
    for name, pattern in TOKEN_PATTERNS:
        if pattern.search(text):
            detections.append(name)
            text = pattern.sub("[REDACTED_TOKEN_PATTERN]", text)
    return text, detections


def bounded_error_message(text: str, secret: str) -> tuple[str, list[str]]:
    sanitized, detections = scrub_sensitive(text, secret)
    return sanitized[:400], detections


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
        raise ReadinessError("Configured route/provider/model differs from the frozen target; no request was sent.")
    return endpoint


def load_prompt() -> dict[str, Any]:
    value = strict_json_loads(PROMPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("messages"), list) or len(value["messages"]) != 2:
        raise ReadinessError("Prompt structure is invalid; no request was sent.")
    if not isinstance(value.get("expected_cases"), list) or len(value["expected_cases"]) != 3:
        raise ReadinessError("Prompt case schema is invalid; no request was sent.")
    return value


def source_files() -> dict[str, Path]:
    return {
        "runner": HERE / "runner.py",
        "prompt": PROMPT_PATH,
        "fake_http_tests": HERE / "tests" / "test_runner.py",
        "legacy_provider_config_reader_read_only": PROVIDER_DIR / "live_provider.py",
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
        raise ReadinessError("Readiness v2 preregistration already exists; refusing to overwrite it.")
    config = load_env(config_path)
    endpoint_for(config)
    prompt = load_prompt()
    prereg = {
        "preregistration_version": "t1-teacher-readiness-preregistration-v2",
        "status": "FROZEN_BEFORE_EXTERNAL_REQUEST",
        "created_utc": created_utc,
        "local_date": "2026-10-11",
        "local_timezone": "Asia/Shanghai",
        "purpose": "one bounded visible-text readiness check over three new synthetic states",
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
            "session_id": str(uuid.uuid4()),
            "session_id_stable_for_single_request": True,
            "response_request_id": "record only a bounded safe allowlisted ID",
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
            "strict_json_duplicate_keys_rejected": True,
            "no_tools_or_business_writes": True,
            "no_tool_results_or_completed_write_claims": True,
            "no_hidden_reasoning_requested_or_persisted": True,
        },
        "interpretation": {
            "success_scope": "three synthetic candidate texts and strict schema only",
            "human_semantic_review_required": True,
            "teacher_quality_pass": False,
            "teacher_data_quality": "NOT_ASSESSED",
            "student_model_quality": "DEFERRED",
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
        raise ReadinessError("Frozen readiness v2 preregistration is missing; no request was sent.")
    digest = sha256_bytes(PREREG_PATH.read_bytes())
    expected_digest = PREREG_SHA_PATH.read_text(encoding="ascii").split()[0]
    if digest != expected_digest:
        raise ReadinessError("Frozen readiness v2 preregistration hash mismatch; no request was sent.")
    prereg = strict_json_loads(PREREG_PATH.read_text(encoding="utf-8"))
    if prereg.get("status") != "FROZEN_BEFORE_EXTERNAL_REQUEST":
        raise ReadinessError("Readiness v2 preregistration status invalid; no request was sent.")
    if prereg.get("source_sha256") != source_hashes() or prereg.get("prompt_sha256") != sha256_bytes(PROMPT_PATH.read_bytes()):
        raise ReadinessError("Readiness v2 source/prompt hash mismatch; no request was sent.")
    if prereg.get("configuration") != safe_config(config):
        raise ReadinessError("Non-secret configuration projection mismatch; no request was sent.")
    expected_limits = {
        "max_total_posts": 1,
        "timeout_seconds": 60.0,
        "max_output_tokens": 2048,
        "max_response_bytes": 256000,
        "automatic_retry": False,
        "fallback": False,
    }
    if prereg.get("request_limits") != expected_limits:
        raise ReadinessError("Readiness v2 request limits differ from preregistration; no request was sent.")
    identity = prereg.get("route_and_identity", {})
    if identity.get("endpoint") != EXPECTED_ENDPOINT or identity.get("configured_model") != EXPECTED_MODEL:
        raise ReadinessError("Readiness v2 target differs from preregistration; no request was sent.")
    if not isinstance(identity.get("session_id"), str) or not identity.get("session_id_stable_for_single_request"):
        raise ReadinessError("Readiness v2 session identity is invalid; no request was sent.")
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


def post_once(
    config: ProviderConfig,
    prompt: dict[str, Any],
    *,
    session_id: str,
    budget: RequestBudget,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], bytes | None]:
    """Return bounded transport metadata and transient bytes; caller must not persist raw bytes."""
    budget.reserve()
    request = urllib.request.Request(
        endpoint_for(config),
        data=json.dumps(build_payload(config, prompt), ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-opencode-session": session_id,
        },
        method="POST",
    )
    open_request = opener or urllib.request.urlopen
    started = time.monotonic()
    try:
        with open_request(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            return ({"http_status": int(response.status), "duration_seconds": round(time.monotonic() - started, 3), "response_body_bytes": len(body)}, body)
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_RESPONSE_BYTES + 1)
        return ({"http_status": int(exc.code), "duration_seconds": round(time.monotonic() - started, 3), "response_body_bytes": len(body)}, body)
    except OSError:
        # Do not serialize exception text: it can contain request/credential details.
        return ({"http_status": None, "duration_seconds": round(time.monotonic() - started, 3), "response_body_bytes": 0, "error_category": "TRANSPORT_FAILURE"}, None)


def safe_envelope_metadata(envelope: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "server_request_id": None,
        "provider_returned_model_label": None,
        "provider_returned_model_matches_expected": False,
        "finish_reason": None,
        "usage": {},
        "reasoning_content_field_present": False,
        "tool_calls_field_present": False,
    }
    request_id = envelope.get("id")
    if isinstance(request_id, str) and len(request_id) <= 160 and re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        result["server_request_id"] = request_id
    model = envelope.get("model")
    if model == EXPECTED_MODEL:
        result["provider_returned_model_label"] = EXPECTED_MODEL
        result["provider_returned_model_matches_expected"] = True
    elif isinstance(model, str):
        result["provider_returned_model_label"] = "other_or_unrecognized"
    choices = envelope.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    finish = choice.get("finish_reason")
    if isinstance(finish, str) and finish in {"stop", "length", "content_filter", "tool_calls", "function_call"}:
        result["finish_reason"] = finish
    usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    result["usage"] = {
        key: usage[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")
        if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool) and usage[key] >= 0
    }
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    result["reasoning_content_field_present"] = "reasoning_content" in message
    result["tool_calls_field_present"] = "tool_calls" in choice or "tool_calls" in message
    return result


def validate_candidate(parsed: Any, expected_cases: list[dict[str, Any]]) -> dict[str, bool]:
    result = {
        "schema_valid": False,
        "task_conclusions_match": False,
        "visible_text_valid": False,
        "no_completed_write_claim": False,
        "manual_semantic_review_required": True,
    }
    if not isinstance(parsed, dict) or set(parsed) != {"cases"} or not isinstance(parsed.get("cases"), list) or len(parsed["cases"]) != 3:
        return result
    expected_by_id = {case["case_id"]: case["task_conclusion"] for case in expected_cases}
    seen: set[str] = set()
    schema_valid = True
    conclusions_valid = True
    text_valid = True
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
        if case.get("task_conclusion") != expected_by_id[case_id]:
            conclusions_valid = False
        if not text.strip() or len(text) > 80 or "工具" in text or "function call" in text.lower():
            text_valid = False
        if any(phrase in text for phrase in FORBIDDEN_WRITE_CLAIMS):
            no_write_claim = False
    ordered = [case.get("case_id") for case in parsed["cases"] if isinstance(case, dict)] == [case["case_id"] for case in expected_cases]
    schema_valid = schema_valid and seen == set(expected_by_id) and ordered
    result.update({
        "schema_valid": schema_valid,
        "task_conclusions_match": schema_valid and conclusions_valid,
        "visible_text_valid": schema_valid and text_valid,
        "no_completed_write_claim": schema_valid and no_write_claim,
    })
    return result


def base_result(transport: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "http_status": transport.get("http_status"),
        "duration_seconds": transport.get("duration_seconds"),
        "response_body_bytes": transport.get("response_body_bytes"),
        "response_body_saved": False,
        "reasoning_content_value_saved": False,
        "candidate_texts_are_not_training_data": True,
    }


def process_success_response(transport: dict[str, Any], body: bytes, *, secret: str, expected_cases: list[dict[str, Any]]) -> dict[str, Any]:
    result = base_result(transport, "INCOMPLETE")
    if len(body) > MAX_RESPONSE_BYTES:
        result.update({"status": "RESPONSE_BYTE_LIMIT_EXCEEDED", "error_category": "RESPONSE_BYTE_LIMIT_EXCEEDED"})
        return result
    try:
        raw_text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        result.update({"status": "INVALID_PROVIDER_UTF8", "error_category": "INVALID_PROVIDER_UTF8"})
        return result
    if secret and secret in raw_text:
        result.update({
            "status": "QUARANTINED_EXACT_SECRET_ECHO",
            "sensitive_response_detected": True,
            "detection_types": ["exact_credential_echo"],
            "error_category": "SENSITIVE_RESPONSE_QUARANTINED",
        })
        return result
    token_detections = detected_token_patterns(raw_text)
    if token_detections:
        result.update({
            "status": "QUARANTINED_TOKEN_PATTERN",
            "sensitive_response_detected": True,
            "detection_types": token_detections,
            "error_category": "SENSITIVE_RESPONSE_QUARANTINED",
        })
        return result
    try:
        envelope = strict_json_loads(raw_text)
    except (ValueError, json.JSONDecodeError):
        result.update({"status": "INVALID_PROVIDER_JSON", "error_category": "INVALID_PROVIDER_JSON"})
        return result
    if not isinstance(envelope, dict):
        result.update({"status": "INVALID_PROVIDER_ENVELOPE", "error_category": "INVALID_PROVIDER_ENVELOPE"})
        return result
    decoded_detections = decoded_sensitive_types(envelope, secret)
    if decoded_detections:
        exact_echo = "exact_credential_echo" in decoded_detections
        result.update({
            "status": "QUARANTINED_EXACT_SECRET_ECHO" if exact_echo else "QUARANTINED_TOKEN_PATTERN",
            "sensitive_response_detected": True,
            "detection_types": decoded_detections,
            "error_category": "SENSITIVE_RESPONSE_QUARANTINED",
        })
        return result
    metadata = safe_envelope_metadata(envelope)
    result.update(metadata)
    if not metadata["server_request_id"] or not metadata["provider_returned_model_matches_expected"]:
        result.update({"status": "PROVIDER_IDENTITY_METADATA_INCOMPLETE", "error_category": "PROVIDER_IDENTITY_METADATA_INCOMPLETE"})
        return result
    if not all(key in metadata["usage"] for key in ("prompt_tokens", "completion_tokens", "total_tokens")) or metadata["finish_reason"] is None:
        result.update({"status": "PROVIDER_USAGE_OR_FINISH_METADATA_INCOMPLETE", "error_category": "PROVIDER_USAGE_OR_FINISH_METADATA_INCOMPLETE"})
        return result
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        result.update({"status": "MISSING_COMPLETION_CHOICE", "error_category": "MISSING_COMPLETION_CHOICE"})
        return result
    choice = choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    visible = message.get("content")
    if not isinstance(visible, str):
        result.update({"status": "MISSING_VISIBLE_COMPLETION", "error_category": "MISSING_VISIBLE_COMPLETION"})
        return result
    result["visible_content_character_count"] = len(visible)
    try:
        parsed = strict_json_loads(visible)
    except (ValueError, json.JSONDecodeError):
        result.update({"status": "INVALID_COMPLETION_JSON", "error_category": "INVALID_COMPLETION_JSON", "completion_strict_json_valid": False})
        return result
    result["completion_strict_json_valid"] = True
    validation = validate_candidate(parsed, expected_cases)
    result["validation"] = validation
    if metadata["tool_calls_field_present"]:
        validation["schema_valid"] = False
    if metadata["finish_reason"] != "stop" or not all(validation[key] is True for key in (
        "schema_valid", "task_conclusions_match", "visible_text_valid", "no_completed_write_claim"
    )):
        result.update({"status": "CANDIDATE_CONTRACT_FAILED", "error_category": "CANDIDATE_CONTRACT_FAILED"})
        return result
    result["status"] = "TEXT_CANDIDATE_SCHEMA_READY"
    result["candidate"] = parsed
    result["candidate_text_sha256"] = {
        case["case_id"]: sha256_bytes(case["visible_text"].encode("utf-8"))
        for case in parsed["cases"]
    }
    return result


def process_http_failure(transport: dict[str, Any], body: bytes | None, *, secret: str) -> dict[str, Any]:
    result = base_result(transport, "HTTP_OR_TRANSPORT_FAILURE")
    if transport.get("error_category"):
        result["error_category"] = transport["error_category"]
        return result
    if body is None:
        result["error_category"] = "HTTP_ERROR_WITHOUT_BODY"
        return result
    text = body[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
    safe, detections = bounded_error_message(text, secret)
    decoded_detections: list[str] = []
    try:
        decoded_detections = decoded_sensitive_types(strict_json_loads(text), secret)
    except (ValueError, json.JSONDecodeError):
        pass
    if any(name not in detections for name in decoded_detections):
        result.update({
            "status": "QUARANTINED_SENSITIVE_HTTP_ERROR",
            "error_category": "SENSITIVE_HTTP_ERROR_QUARANTINED",
            "sensitive_error_pattern_detected": sorted(set(detections + decoded_detections)),
            "error_message": "[SENSITIVE_ERROR_OMITTED]",
        })
        return result
    result["error_category"] = "HTTP_ERROR"
    result["error_message"] = safe
    result["error_message_truncated_to_400"] = len(safe) == 400
    if detections:
        result["sensitive_error_pattern_detected"] = detections
    return result


def run(config_path: Path, output: Path) -> dict[str, Any]:
    config = load_env(config_path)
    endpoint_for(config)
    prereg, prereg_hash = verify_preregistration(config)
    if output.exists():
        raise ReadinessError("Evidence output path already exists; refusing to overwrite it.")
    output.mkdir(parents=True, exist_ok=False)
    prompt = load_prompt()
    identity = prereg["route_and_identity"]
    payload = build_payload(config, prompt)
    write_json(output / "request.json", {
        "endpoint": EXPECTED_ENDPOINT,
        "payload": payload,
        "request_identity": {"x_opencode_session": identity["session_id"], "user_agent": USER_AGENT},
    })
    started_utc = utc_now()
    budget = RequestBudget()
    transport, body = post_once(config, prompt, session_id=identity["session_id"], budget=budget)
    if transport.get("http_status") == 200 and body is not None:
        result = process_success_response(transport, body, secret=config.api_key, expected_cases=prompt["expected_cases"])
    else:
        result = process_http_failure(transport, body, secret=config.api_key)
    ready = result.get("status") == "TEXT_CANDIDATE_SCHEMA_READY"
    manifest = {
        "probe": "t1-teacher-visible-text-readiness-v2",
        "started_utc": started_utc,
        "completed_utc": utc_now(),
        "preregistration_sha256": prereg_hash,
        "source_sha256": prereg["source_sha256"],
        "prompt_sha256": prereg["prompt_sha256"],
        "config": safe_config(config),
        "request_identity": {
            "x_opencode_session": identity["session_id"],
            "stable_for_request": True,
            "server_request_id": result.get("server_request_id"),
        },
        "limits": {
            "max_requests": 1,
            "requests_sent": budget.used,
            "timeout_seconds": TIMEOUT_SECONDS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "retries": 0,
            "fallbacks": 0,
        },
        "status": "TEXT_CANDIDATE_SCHEMA_READY" if ready else result.get("status", "INCOMPLETE"),
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


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--freeze-preregistration":
        try:
            digest = create_preregistration(CONFIG_PATH, created_utc=utc_now(), d_output=str(DEFAULT_OUTPUT))
        except (LiveProviderError, ReadinessError, OSError, ValueError) as exc:
            print(json.dumps({"status": "PREREGISTRATION_NOT_CREATED", "error": str(exc)[:300]}, ensure_ascii=False))
            return 2
        print(json.dumps({"status": "FROZEN_BEFORE_EXTERNAL_REQUEST", "preregistration_sha256": digest}, sort_keys=True))
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "--send-one":
        try:
            manifest = run(CONFIG_PATH, DEFAULT_OUTPUT)
        except (LiveProviderError, ReadinessError, OSError, ValueError) as exc:
            print(json.dumps({"status": "NOT_AVAILABLE_OR_NOT_RUN", "requests_sent": 0, "error": str(exc)[:300]}, ensure_ascii=False, sort_keys=True))
            return 2
        result = manifest["result"]
        summary = {
            "status": manifest["status"],
            "requests_sent": manifest["limits"]["requests_sent"],
            "http_status": result.get("http_status"),
            "duration_seconds": result.get("duration_seconds"),
            "finish_reason": result.get("finish_reason"),
            "usage": result.get("usage", {}),
            "candidate": result.get("candidate") if manifest["status"] == "TEXT_CANDIDATE_SCHEMA_READY" else None,
            "validation": result.get("validation"),
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if manifest["status"] == "TEXT_CANDIDATE_SCHEMA_READY" else 1
    print("No request sent. Use --freeze-preregistration first, and --send-one only after independent source review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
