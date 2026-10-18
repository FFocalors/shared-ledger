"""Two-request maximum synthetic Teacher availability probe; never touches ledger data."""
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
from dataclasses import dataclass
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
USER_AGENT = "shared-ledger-t1-teacher-probe/0.1.0"
MAX_REQUESTS = 2
MAX_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_TOKENS = 256
MAX_RESPONSE_BYTES = 256_000
SANITY_PROMPT = HERE / "prompts" / "contract-sanity-v1.json"
LANGUAGE_PROMPT = HERE / "prompts" / "language-pilot-v1.json"
PREREGISTRATION = HERE / "preregistration.json"
PREREGISTRATION_SHA = HERE / "preregistration.sha256"


class ProbeError(RuntimeError):
    """A safe, bounded probe failure message."""


@dataclass
class RequestBudget:
    max_requests: int = MAX_REQUESTS
    used: int = 0

    def reserve(self) -> int:
        if self.used >= self.max_requests:
            raise ProbeError("Request budget exhausted; no request was sent.")
        self.used += 1
        return self.used


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def strict_json_loads(raw: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key.")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError("Non-standard JSON number.")

    return json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=reject_constant)


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
    if endpoint != EXPECTED_ENDPOINT:
        raise ProbeError("Configured route differs from the preregistered OpenCode Go route; no request was sent.")
    if config.provider.lower() != "opencode" or config.model != EXPECTED_MODEL:
        raise ProbeError("Configured provider/model differs from the preregistered probe; no request was sent.")
    return endpoint


def load_prompt(path: Path) -> dict[str, Any]:
    prompt = strict_json_loads(path.read_text(encoding="utf-8"))
    messages = prompt.get("messages") if isinstance(prompt, dict) else None
    if not isinstance(messages, list) or not messages:
        raise ProbeError("Prompt file is invalid; no request was sent.")
    if any(not isinstance(message, dict) or message.get("role") not in {"system", "user"} or not isinstance(message.get("content"), str) for message in messages):
        raise ProbeError("Prompt message is invalid; no request was sent.")
    return prompt


def build_payload(config: ProviderConfig, prompt: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": config.model,
        "messages": prompt["messages"],
        "temperature": config.temperature,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "response_format": {"type": "json_object"},
    }


def _redact_text(text: str, secret: str) -> str:
    redacted = text.replace(secret, "[REDACTED]") if secret else text
    redacted = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r'(?i)("(?:api[_-]?key|token|authorization)"\s*:\s*")[^"\\]*(")', r"\1[REDACTED]\2", redacted)
    return redacted


def _bounded_message(body: bytes, secret: str) -> str:
    raw = body[:4096].decode("utf-8", errors="replace")
    try:
        parsed = strict_json_loads(raw)
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(err, dict):
            message = err.get("message")
        elif isinstance(err, str):
            message = err
        else:
            message = None
    except (ValueError, json.JSONDecodeError):
        message = None
    if not isinstance(message, str) or not message.strip():
        message = "Provider returned an HTTP error; body omitted."
    message = _redact_text(message, secret)
    return message[:500]


def post_once(
    config: ProviderConfig,
    prompt: dict[str, Any],
    *,
    timeout: float,
    session_id: str,
    budget: RequestBudget,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if not (0 < timeout <= MAX_TIMEOUT_SECONDS):
        raise ProbeError("Timeout exceeds the preregistered request bound; no request was sent.")
    if MAX_OUTPUT_TOKENS > 1024:
        raise ProbeError("Output token ceiling exceeds the preregistered bound; no request was sent.")
    endpoint = endpoint_for(config)
    payload = build_payload(config, prompt)
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=encoded,
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
        with opener(request, timeout=timeout) as response:
            status = int(response.status)
            raw_bytes = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        duration = round(time.monotonic() - started, 3)
        body = exc.read(4096)
        return {
            "call_number": call_number,
            "http_status": int(exc.code),
            "duration_seconds": duration,
            "error": _bounded_message(body, config.api_key),
            "raw_response": None,
        }
    except (TimeoutError, urllib.error.URLError):
        return {
            "call_number": call_number,
            "http_status": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": "Provider request failed before an HTTP response.",
            "raw_response": None,
        }
    duration = round(time.monotonic() - started, 3)
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        return {
            "call_number": call_number,
            "http_status": status,
            "duration_seconds": duration,
            "error": "Response exceeded the preregistered byte limit; content omitted.",
            "raw_response": None,
        }
    raw = raw_bytes.decode("utf-8", errors="replace")
    return {
        "call_number": call_number,
        "http_status": status,
        "duration_seconds": duration,
        "raw_response": _redact_text(raw, config.api_key),
        "error": None,
    }


def _usage_summary(envelope: dict[str, Any]) -> dict[str, Any]:
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    result: dict[str, Any] = {}
    for source, target in (("prompt_tokens", "prompt_tokens"), ("completion_tokens", "completion_tokens"), ("total_tokens", "total_tokens")):
        value = usage.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[target] = value
    cost = usage.get("cost", envelope.get("cost"))
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
        result["provider_cost"] = cost
    return result


def inspect_envelope(raw_response: str) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = strict_json_loads(raw_response)
    if not isinstance(envelope, dict):
        raise ProbeError("Provider response envelope was not a JSON object.")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProbeError("Provider response had no completion choice.")
    choice = choices[0]
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ProbeError("Provider completion content was not text.")
    parsed = strict_json_loads(content)
    if not isinstance(parsed, dict):
        raise ProbeError("Completion content was not a JSON object.")
    model = envelope.get("model") if isinstance(envelope.get("model"), str) else None
    request_id = envelope.get("id") if isinstance(envelope.get("id"), str) else None
    finish_reason = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
    metadata = {
        "provider_returned_model_label": model,
        "server_request_id": request_id,
        "finish_reason": finish_reason,
        "usage": _usage_summary(envelope),
        "content_object": parsed,
    }
    return parsed, metadata


def validate_sanity(parsed: dict[str, Any], expected: dict[str, Any]) -> bool:
    return parsed == expected and set(parsed) == set(expected)


def validate_language(parsed: dict[str, Any], expected: list[dict[str, Any]]) -> dict[str, Any]:
    if set(parsed) != {"cases"} or not isinstance(parsed["cases"], list) or len(parsed["cases"]) != len(expected):
        return {"schema_valid": False, "case_count": len(parsed.get("cases", [])) if isinstance(parsed.get("cases"), list) else None, "dispositions_match": False, "manual_semantic_review_required": True}
    expected_by_id = {case["case_id"]: case for case in expected}
    seen: set[str] = set()
    schema_valid = True
    dispositions_match = True
    for case in parsed["cases"]:
        if not isinstance(case, dict) or set(case) != {"case_id", "disposition", "reply"}:
            schema_valid = False
            continue
        case_id = case.get("case_id")
        if case_id not in expected_by_id or case_id in seen or not isinstance(case.get("reply"), str):
            schema_valid = False
            continue
        seen.add(case_id)
        if case["disposition"] != expected_by_id[case_id]["disposition"]:
            dispositions_match = False
        if len(case["reply"]) > 80:
            schema_valid = False
    return {
        "schema_valid": schema_valid and seen == set(expected_by_id),
        "case_count": len(parsed["cases"]),
        "dispositions_match": dispositions_match and seen == set(expected_by_id),
        "manual_semantic_review_required": True,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _process_call(
    config: ProviderConfig,
    prompt_path: Path,
    name: str,
    *,
    timeout: float,
    session_id: str,
    budget: RequestBudget,
    output: Path,
) -> dict[str, Any]:
    prompt = load_prompt(prompt_path)
    payload = build_payload(config, prompt)
    # Request artifacts are intentionally header-free and contain no credential.
    write_json(output / f"{name}.request.json", {"endpoint": EXPECTED_ENDPOINT, "payload": payload, "request_identity": {"x_opencode_session": session_id}})
    result = post_once(config, prompt, timeout=timeout, session_id=session_id, budget=budget)
    result_path = output / f"{name}.raw_response.json"
    if result["raw_response"] is not None:
        result_path.write_text(result["raw_response"], encoding="utf-8")
    if result["error"] is not None:
        write_json(output / f"{name}.failure.json", {"http_status": result["http_status"], "duration_seconds": result["duration_seconds"], "error": result["error"]})
        return {key: value for key, value in result.items() if key != "raw_response"}
    try:
        parsed, metadata = inspect_envelope(result["raw_response"])
    except (ValueError, ProbeError, json.JSONDecodeError) as exc:
        result["error"] = str(exc)[:300]
        result["content_valid"] = False
        write_json(output / f"{name}.parse_failure.json", {"http_status": result["http_status"], "duration_seconds": result["duration_seconds"], "error": result["error"]})
        return {key: value for key, value in result.items() if key != "raw_response"}
    result.update(metadata)
    if name == "01-contract-sanity":
        result["content_valid"] = validate_sanity(parsed, prompt["expected_content"])
    else:
        result["content_validation"] = validate_language(parsed, prompt["expected_cases"])
    write_json(output / f"{name}.parsed.json", {"content_object": parsed, "validation": result.get("content_valid", result.get("content_validation"))})
    return {key: value for key, value in result.items() if key != "raw_response"}


def safe_config_metadata(config: ProviderConfig) -> dict[str, Any]:
    public = {
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
        "credential_value_recorded": False,
        "config_fingerprint_sha256_nonsecret_projection": canonical_sha256(public),
    }


def source_files() -> dict[str, Path]:
    return {
        "probe": HERE / "probe.py",
        "sanity_prompt": SANITY_PROMPT,
        "language_prompt": LANGUAGE_PROMPT,
        "fake_http_tests": HERE / "tests" / "test_probe.py",
        "legacy_provider_adapter_read_only": PROVIDER_DIR / "live_provider.py",
        "teacher_status_t1_v1": REPO / "agent" / "docs" / "t1" / "TEACHER_STATUS-T1-v1.md",
        "business_acceptance_t1": REPO / "agent" / "docs" / "t1" / "BUSINESS_ACCEPTANCE.md",
        "t1_freeze": REPO / "agent" / "docs" / "t1" / "FREEZE-T1.md",
        "model_preregistration_read_only": REPO / "agent" / "docs" / "t1" / "MODEL_PREREG-T1-v1.json",
        "training_guide": REPO / "agent" / "docs" / "shared-ledger-agent-development-guide-v0.4.html",
    }


def compute_source_hashes() -> dict[str, str]:
    return {name: sha256_bytes(path.read_bytes()) for name, path in source_files().items()}


def create_preregistration(config_path: Path, *, created_utc: str) -> str:
    if PREREGISTRATION.exists() or PREREGISTRATION_SHA.exists():
        raise ProbeError("Preregistration already exists; refusing to replace the frozen plan.")
    config = load_env(config_path)
    endpoint_for(config)
    prompt_hashes = {
        "contract_sanity": sha256_bytes(SANITY_PROMPT.read_bytes()),
        "language_pilot": sha256_bytes(LANGUAGE_PROMPT.read_bytes()),
    }
    plan = {
        "preregistration_version": "t1-teacher-probe-preregistration-v1",
        "status": "FROZEN_BEFORE_EXTERNAL_REQUESTS",
        "created_utc": created_utc,
        "local_date": "2026-10-11",
        "local_timezone": "Asia/Shanghai",
        "scope": "synthetic protocol canary and optional three-case language candidate only",
        "configuration": safe_config_metadata(config),
        "configuration_source": {
            "path": "D:/project/Android/shared-ledger/scripts/ai_teacher_generator/.env",
            "read_only": True,
            "secret_value_recorded_or_hashed": False,
            "secret_loaded_into_memory_only": True,
        },
        "route_and_identity": {
            "endpoint": EXPECTED_ENDPOINT,
            "configured_model": EXPECTED_MODEL,
            "user_agent": USER_AGENT,
            "session_header": "x-opencode-session",
            "session_id_policy": "one UUID stable across the two possible requests; record only as request identity",
            "response_server_request_id": "record envelope id when returned; provider-reported identifiers are metadata, not proof of model identity",
        },
        "request_budget": {
            "maximum_total_posts": MAX_REQUESTS,
            "sequential_only": True,
            "per_request_timeout_seconds": MAX_TIMEOUT_SECONDS,
            "max_output_tokens_per_request": MAX_OUTPUT_TOKENS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "automatic_retry_count": 0,
            "route_or_model_fallback": False,
        },
        "request_1_contract_sanity": {
            "prompt_version": "t1-teacher-contract-sanity-v1",
            "purpose": ["HTTP reachability", "configured authentication path", "completion content", "strict JSON object and exact schema", "finish reason", "usage metadata", "request identity metadata"],
            "pass_criteria": "HTTP 200, exact canary object, finish_reason=stop, prompt/completion/total token counts present, response id present, and provider-returned model label present (label is not treated as model identity proof)",
            "failure_behavior": "record bounded failure and stop; do not retry or send language pilot",
        },
        "request_2_language_pilot": {
            "prompt_version": "t1-teacher-language-pilot-v1",
            "sent_only_if": "request 1 meets all pass criteria",
            "synthetic_cases": ["ordinary Activity prepayment refusal", "explicit expense.create with two payers and equal split", "locked Expense presentation-only note change"],
            "candidate_checks": "exact three IDs and dispositions, exact item schema, reply length cap; human semantic review still required",
            "execution_boundary": "no tools, no write, no tool result, no claim of completed write, no hidden reasoning",
        },
        "interpretation_limits": {
            "transport_success_is_not_teacher_dataset_quality_acceptance": True,
            "three_case_pilot_is_not_teacher_quality_acceptance": True,
            "student_model_quality": "DEFERRED_NOT_TESTED",
            "training_eligible": False,
            "sealed_data_used": False,
            "business_data_used": False,
        },
        "prompt_sha256": prompt_hashes,
        "source_sha256": compute_source_hashes(),
        "evidence_output_directory": "D:/AI/runs/shared-ledger/t1-teacher-probe-20261011",
    }
    write_json(PREREGISTRATION, plan)
    digest = sha256_bytes(PREREGISTRATION.read_bytes())
    PREREGISTRATION_SHA.write_text(f"{digest}  {PREREGISTRATION.name}\n", encoding="ascii")
    return digest


def verify_preregistration(config: ProviderConfig) -> tuple[dict[str, Any], str]:
    if not PREREGISTRATION.is_file() or not PREREGISTRATION_SHA.is_file():
        raise ProbeError("Frozen preregistration is missing; no request was sent.")
    digest = sha256_bytes(PREREGISTRATION.read_bytes())
    expected_sha = PREREGISTRATION_SHA.read_text(encoding="ascii").split()[0]
    if digest != expected_sha:
        raise ProbeError("Frozen preregistration hash check failed; no request was sent.")
    plan = strict_json_loads(PREREGISTRATION.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("status") != "FROZEN_BEFORE_EXTERNAL_REQUESTS":
        raise ProbeError("Frozen preregistration status is invalid; no request was sent.")
    if plan.get("configuration") != safe_config_metadata(config):
        raise ProbeError("Non-secret configuration projection differs from preregistration; no request was sent.")
    if plan.get("prompt_sha256") != {
        "contract_sanity": sha256_bytes(SANITY_PROMPT.read_bytes()),
        "language_pilot": sha256_bytes(LANGUAGE_PROMPT.read_bytes()),
    }:
        raise ProbeError("Prompt hash check failed; no request was sent.")
    if plan.get("source_sha256") != compute_source_hashes():
        raise ProbeError("Source hash check failed; no request was sent.")
    if plan.get("request_budget", {}).get("maximum_total_posts") != MAX_REQUESTS:
        raise ProbeError("Request budget differs from preregistration; no request was sent.")
    return plan, digest


def run_probe(config_path: Path, output: Path, *, include_language: bool = True, timeout: float = 60.0) -> dict[str, Any]:
    config = load_env(config_path)
    endpoint_for(config)
    prereg, prereg_hash = verify_preregistration(config)
    if output.exists():
        raise ProbeError("Evidence output path already exists; refusing to overwrite it.")
    output.mkdir(parents=True, exist_ok=False)
    session_id = str(uuid.uuid4())
    budget = RequestBudget()
    started_utc = utc_now()
    config_metadata = safe_config_metadata(config)
    results = [_process_call(config, SANITY_PROMPT, "01-contract-sanity", timeout=timeout, session_id=session_id, budget=budget, output=output)]
    first = results[0]
    usage = first.get("usage", {})
    sanity_passed = (
        first.get("http_status") == 200
        and first.get("content_valid") is True
        and first.get("finish_reason") == "stop"
        and all(name in usage for name in ("prompt_tokens", "completion_tokens", "total_tokens"))
        and bool(first.get("server_request_id"))
        and bool(first.get("provider_returned_model_label"))
    )
    if include_language and sanity_passed and budget.used < MAX_REQUESTS:
        results.append(_process_call(config, LANGUAGE_PROMPT, "02-language-pilot", timeout=timeout, session_id=session_id, budget=budget, output=output))
    manifest = {
        "probe": "t1-teacher-availability-and-tiny-language-pilot",
        "started_utc": started_utc,
        "completed_utc": utc_now(),
        "preregistration_sha256": prereg_hash,
        "source_sha256": prereg["source_sha256"],
        "prompt_sha256": prereg["prompt_sha256"],
        "config": config_metadata,
        "request_identity": {"x_opencode_session": session_id, "stable_for_run": True, "response_server_request_ids": [item.get("server_request_id") for item in results]},
        "limits": {"max_requests": MAX_REQUESTS, "requests_sent": budget.used, "timeout_seconds_per_request": timeout, "max_output_tokens_per_request": MAX_OUTPUT_TOKENS, "max_response_bytes": MAX_RESPONSE_BYTES, "automatic_retries": 0},
        "availability": "AVAILABLE_PROTOCOL_SANITY" if sanity_passed else "UNAVAILABLE_OR_CONTRACT_FAILURE",
        "teacher_data_quality": "NOT_ASSESSED",
        "student_model_quality": "DEFERRED_NOT_TESTED",
        "results": results,
        "remote_provider_called": budget.used > 0,
        "training_eligible": False,
        "candidate_only": True,
    }
    write_json(output / "run_manifest.json", manifest)
    return manifest


def _safe_cli_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "availability": manifest["availability"],
        "requests_sent": manifest["limits"]["requests_sent"],
        "max_requests": manifest["limits"]["max_requests"],
        "results": [
            {
                "call_number": item["call_number"],
                "http_status": item["http_status"],
                "duration_seconds": item["duration_seconds"],
                "provider_returned_model_label": item.get("provider_returned_model_label"),
                "server_request_id_present": bool(item.get("server_request_id")),
                "finish_reason": item.get("finish_reason"),
                "usage": item.get("usage", {}),
                "content_valid": item.get("content_valid", item.get("content_validation")),
                "error": item.get("error"),
            }
            for item in manifest["results"]
        ],
    }


def main() -> int:
    config_path = Path(r"D:\project\Android\shared-ledger\scripts\ai_teacher_generator\.env")
    output = Path(r"D:\AI\runs\shared-ledger\t1-teacher-probe-20261011")
    try:
        manifest = run_probe(config_path, output)
    except (LiveProviderError, ProbeError, OSError, ValueError) as exc:
        safe_failure = {"availability": "NOT_AVAILABLE_OR_NOT_RUN", "error": str(exc)[:300], "requests_sent": 0}
        print(json.dumps(safe_failure, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(_safe_cli_summary(manifest), ensure_ascii=False, sort_keys=True))
    return 0 if manifest["availability"] == "AVAILABLE_PROTOCOL_SANITY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
