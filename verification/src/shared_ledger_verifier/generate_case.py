"""Generate one raw business case, compile it, and validate Scenario v1.

This stage never executes a scenario or asks the business Judge for a verdict.
It applies two gates in order: the Scenario Loader (is this a legal Scenario v1
document?) and the focus contract (does it actually exercise the business shape
its focus claims?). A document that passes the Loader but fails its focus
contract is reported as ``FOCUS_MISMATCH`` and must not be counted as coverage.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .deepseek import DeepSeekApiError, DeepSeekConfigurationError
from .duplicates import raw_case_fingerprint, scenario_fingerprint
from .focus_contract import check_focus
from .loader import ScenarioValidationError, load_scenario
from .local_llm import LocalLLMError
from .local_llm_v2 import FOCUS_SECTIONS
from .raw_case import RawCaseError, SMOKE_CNY_FOCUSES, generate_raw_case
from .scenario_compiler import CompilerError, compile_once
from .scenario_plan import ScenarioPlan, plan_for
from .supabase import verification_root


_SECRET_PATTERN = re.compile(
    r"\b(?:Bearer\s+\S+|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}"
    r"|(?:sk|rk|pk)[-_][A-Za-z0-9_-]{8,})\b",
    re.IGNORECASE,
)
_SECRET_ENV_NAMES = ("DEEPSEEK_API_KEY", "LOCAL_LLM_API_KEY", "SUPABASE_ANON_KEY")


def _has_secret(value: Any) -> bool:
    rendered = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if _SECRET_PATTERN.search(rendered):
        return True
    return any((secret := os.environ.get(name, "")) and len(secret) >= 8 and secret in rendered
               for name in _SECRET_ENV_NAMES)


def _safe_error(error: Exception) -> str:
    """Retain a useful Loader summary without exposing credentials or long text."""
    message = str(error)[:400]
    for name in _SECRET_ENV_NAMES:
        secret = os.environ.get(name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return _SECRET_PATTERN.sub("[REDACTED]", message)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _business_logic_commit(path: Path) -> str | None:
    repository = verification_root().parent
    try:
        relative = path.resolve().relative_to(repository.resolve())
        completed = subprocess.run(
            ["git", "log", "-n1", "--format=%H", "--", relative.as_posix()],
            cwd=repository, check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _output_directory(focus: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return verification_root() / "local_llm_probe" / "generated_cases" / f"{stamp}_{focus}_{secrets.token_hex(3)}"


def _validate_smoke_currency(scenario: dict[str, Any], focus: str) -> None:
    """Reject FX in basic E2E smoke cases before any Runner invocation."""
    if focus not in SMOKE_CNY_FOCUSES:
        return
    activity = scenario["activity"]
    if activity["base_currency"] != "CNY" or activity["multi_currency_enabled"] is not False:
        raise ScenarioValidationError("basic smoke focus requires a CNY-only activity")
    for index, operation in enumerate(scenario["operations"]):
        if "currency" in operation and operation["currency"] != "CNY":
            raise ScenarioValidationError(
                f"basic smoke focus requires CNY at scenario.operations[{index}].currency"
            )


def generate_case(
    focus: str,
    *,
    local_client: Any = None,
    compiler_client: Any = None,
    output_dir: Path | None = None,
    business_logic_path: Path | None = None,
    on_progress: Callable[[str, str, dict[str, Any]], None] | None = None,
    plan: ScenarioPlan | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run one Qwen request and at most two Compiler requests.

    ``plan`` (or a ``seed`` from which one is derived) fixes the business shape
    the model must encode.  The second Compiler request is used when the Loader
    or the focus contract rejected the first Scenario.  Returned diagnostics
    contain controlled categories and redacted Loader text.
    """
    if focus not in FOCUS_SECTIONS and focus not in _registry_names():
        raise ValueError(f"unsupported focus: {focus}")
    if plan is None and seed is not None:
        plan = plan_for(focus, seed)
    if plan is not None and plan.focus != focus:
        raise ValueError(f"plan focus {plan.focus!r} does not match requested focus {focus!r}")
    output_dir = Path(output_dir) if output_dir else _output_directory(focus)
    business_logic_path = (Path(business_logic_path) if business_logic_path else
                           verification_root().parent / "docs/backend/BUSINESS_LOGIC.md")
    output_dir.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "focus": focus,
        "status": "PENDING",
        "plan_seed": plan.seed if plan is not None else None,
        "plan_fingerprint": plan.fingerprint() if plan is not None else None,
        "focus_result": None,
        "focus_error": None,
        "local_model": None,
        "compiler_model": None,
        "business_logic_commit": _business_logic_commit(business_logic_path),
        "generation_latency_seconds": None,
        "compiler_latency_seconds": 0.0,
        "repair_count": 0,
        "loader_result": None,
        "loader_error": None,
        "error_category": None,
        "output_dir": str(output_dir),
    }
    if plan is not None:
        _write_json(output_dir / "plan.json", plan.as_dict())

    def save() -> dict[str, Any]:
        _write_json(output_dir / "result.json", result)
        return result

    try:
        business_logic = business_logic_path.read_text(encoding="utf-8")
    except OSError:
        result.update(status="ERROR", error_category="BUSINESS_LOGIC_UNAVAILABLE")
        return save()
    if not business_logic.strip():
        result.update(status="ERROR", error_category="BUSINESS_LOGIC_EMPTY")
        return save()

    if on_progress:
        on_progress("generator", "running", {"focus": focus, "seed": result["plan_seed"]})
    try:
        raw_case, local_meta = generate_raw_case(
            focus, client=local_client, business_logic_path=business_logic_path, plan=plan,
        )
    except (RawCaseError, LocalLLMError) as error:
        if on_progress:
            on_progress("generator", "failed", {"error": error.category})
        result.update(status="RAW_CASE_ERROR", error_category=error.category)
        return save()
    if plan is not None and tuple(raw_case.get("participants") or ()) != plan.participants:
        # The plan fixes the roster; a different roster means the model did not
        # encode the plan and the case cannot satisfy its focus contract.
        if on_progress:
            on_progress("generator", "failed", {"error": "PLAN_PARTICIPANTS_IGNORED"})
        result.update(status="RAW_CASE_ERROR", error_category="PLAN_PARTICIPANTS_IGNORED")
        return save()
    if focus in SMOKE_CNY_FOCUSES and raw_case.get("currency") != "CNY":
        if on_progress:
            on_progress("generator", "failed", {"error": "CURRENCY_MISMATCH"})
        result.update(status="RAW_CASE_ERROR", error_category="CURRENCY_MISMATCH")
        return save()
    if _has_secret(raw_case):
        if on_progress:
            on_progress("generator", "failed", {"error": "FORBIDDEN_CONTENT"})
        result.update(status="RAW_CASE_ERROR", error_category="FORBIDDEN_CONTENT")
        return save()
    if on_progress:
        on_progress("generator", "completed", {
            "model": local_meta.get("local_model"),
            "latency": local_meta.get("generation_latency_seconds"),
        })
    _write_json(output_dir / "raw_case.json", raw_case)
    result["raw_case_fingerprint"] = raw_case_fingerprint(raw_case)
    for key in ("local_model", "business_logic_sections", "business_logic_characters",
                "input_characters", "generation_latency_seconds", "prompt_tokens", "completion_tokens"):
        value = local_meta.get(key)
        if value is not None and not _has_secret(value):
            result[key] = value
    save()

    attempts: list[dict[str, Any]] = []
    prior_output: dict[str, Any] | None = None
    rejection: str | None = None
    for attempt_no in range(2):
        if attempt_no:
            result["repair_count"] = 1
        if on_progress:
            on_progress("compiler", "running", {
                "attempt": attempt_no + 1, "repair": bool(attempt_no),
                "reason": None if rejection is None else "rejected",
            })
        try:
            compiled = compile_once(
                raw_case, business_logic, client=compiler_client,
                prior_output=prior_output, loader_error=rejection,
                smoke_currency="CNY" if focus in SMOKE_CNY_FOCUSES else None,
                plan=plan,
            )
        except CompilerError as error:
            if on_progress:
                on_progress("compiler", "failed", {"error": error.category})
            result.update(status="COMPILER_INVALID", error_category=error.category)
            _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
            return save()
        except (DeepSeekApiError, DeepSeekConfigurationError) as error:
            err_kind = error.error_kind if isinstance(error, DeepSeekApiError) else "CONFIGURATION_ERROR"
            if on_progress:
                on_progress("compiler", "failed", {"error": err_kind})
            result.update(status="COMPILER_ERROR", error_category=err_kind)
            _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
            return save()
        result["compiler_model"] = compiled.model if not _has_secret(compiled.model) else None
        result["compiler_latency_seconds"] = round(
            result["compiler_latency_seconds"] + compiled.latency_seconds, 3)
        if _has_secret(compiled.scenario):
            if on_progress:
                on_progress("compiler", "failed", {"error": "FORBIDDEN_CONTENT"})
            result.update(status="COMPILER_INVALID", error_category="FORBIDDEN_CONTENT")
            _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
            return save()
        if on_progress:
            on_progress("compiler", "completed", {
                "model": compiled.model,
                "latency": compiled.latency_seconds,
            })
            on_progress("loader", "running", {})
        attempts.append({"attempt": attempt_no + 1, "repair": bool(attempt_no),
                         "latency_seconds": compiled.latency_seconds,
                         "scenario": compiled.scenario})
        _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
        scenario_path = output_dir / "scenario.json"
        _write_json(scenario_path, compiled.scenario)
        result["scenario_fingerprint"] = scenario_fingerprint(compiled.scenario)

        # Gate 1: the Scenario Loader.
        try:
            load_scenario(scenario_path)
            _validate_smoke_currency(compiled.scenario, focus)
        except ScenarioValidationError as error:
            rejection = _safe_error(error)
            if on_progress:
                on_progress("loader", "failed", {"error": rejection, "can_retry": attempt_no == 0})
            result.update(loader_result="INVALID", loader_error=rejection)
            attempts[-1]["loader_result"] = "INVALID"
            attempts[-1]["loader_error"] = rejection
            _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
            prior_output = compiled.scenario
            save()
            continue
        result.update(loader_result="VALID", loader_error=None)

        # Gate 2: the focus contract. A legal document that does not exercise
        # its focus is a FOCUS_MISMATCH, not a valid coverage sample.
        focus_result, focus_error = check_focus(load_scenario(scenario_path), focus)
        attempts[-1]["focus_result"] = focus_result
        attempts[-1]["focus_error"] = focus_error
        result.update(focus_result=focus_result, focus_error=focus_error)
        if focus_result != "FOCUS_VALID":
            rejection = focus_error
            if on_progress:
                on_progress("focus", "failed", {
                    "error": focus_error, "can_retry": attempt_no == 0,
                })
            attempts[-1]["loader_result"] = "VALID"
            _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
            prior_output = compiled.scenario
            save()
            continue

        attempts[-1]["loader_result"] = "VALID"
        _write_json(output_dir / "compiler_result.json", {"attempts": attempts})
        if on_progress:
            on_progress("loader", "completed", {"loader_result": "VALID"})
            on_progress("focus", "completed", {"focus_result": "FOCUS_VALID"})
        result.update(status="VALID", loader_result="VALID", loader_error=None)
        return save()

    if result.get("focus_result") == "FOCUS_MISMATCH":
        if on_progress:
            on_progress("focus", "failed", {"error": "FOCUS_MISMATCH"})
        result.update(status="FOCUS_MISMATCH", error_category="FOCUS_MISMATCH")
        return save()
    if on_progress:
        on_progress("loader", "failed", {"error": "LOADER_INVALID"})
    result.update(status="COMPILER_INVALID", error_category="LOADER_INVALID")
    return save()


def _registry_names() -> frozenset[str]:
    from .focus_contract import ALL_FOCUSES

    return frozenset(ALL_FOCUSES)
