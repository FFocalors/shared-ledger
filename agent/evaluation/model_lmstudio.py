"""Isolated LM Studio adapter for the T1 model evaluation runner.

This module does not load/unload models or start LM Studio. It only performs
read-only catalog requests and requests to an already-running loopback API.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.app import contracts as c
from agent.app.harness import ModelPrompt


PROMPT_PATH = Path(__file__).with_name("model_prompt.md")
DEFAULT_ENDPOINT = "http://127.0.0.1:1234/api/v1/chat"
DEFAULT_MODELS_ENDPOINT = "http://127.0.0.1:1234/api/v1/models"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class LMStudioError(RuntimeError):
    """Sanitized local transport or response-contract failure."""

    def __init__(self, status: str, *, http_status: int | None = None):
        super().__init__(status)
        self.status = status
        self.http_status = http_status


@dataclass(frozen=True)
class InferenceResult:
    status: str
    text: str
    duration_seconds: float
    model_instance_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    tokens_per_second: float | None
    time_to_first_token_seconds: float | None
    output_kinds: tuple[str, ...]
    http_status: int | None = 200

    def metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "model_instance_id": self.model_instance_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "tokens_per_second": self.tokens_per_second,
            "time_to_first_token_seconds": self.time_to_first_token_seconds,
            "output_kinds": list(self.output_kinds),
            "http_status": self.http_status,
        }


def _loopback_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LM Studio endpoint must be a credential-free loopback URL")
    return endpoint


def _prompt_text(prompt: ModelPrompt) -> str:
    payload = prompt.model_dump(mode="json", by_alias=True, exclude_none=False)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_number(value: Any, kind: type[int] | type[float]) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = kind(value)
    except (OverflowError, ValueError):
        return None
    if isinstance(converted, float) and (converted != converted or abs(converted) == float("inf")):
        return None
    return converted


class LMStudioV1Provider:
    """Small native-v1 adapter; no model-management API is exposed."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        models_endpoint: str = DEFAULT_MODELS_ENDPOINT,
        model_key: str,
        artifact_path: str,
        expected_artifact_sha256: str,
        expected_artifact_size_bytes: int = 2_708_804_480,
        expected_quantization: str = "Q4_K_M",
        timeout_seconds: float = 120.0,
        max_output_tokens: int = 768,
        context_length: int = 8192,
        temperature: float = 0.0,
    ) -> None:
        self.endpoint = _loopback_endpoint(endpoint)
        self.models_endpoint = _loopback_endpoint(models_endpoint)
        self.model_key = model_key
        self.artifact_path = Path(artifact_path)
        self.expected_artifact_sha256 = expected_artifact_sha256
        self.expected_artifact_size_bytes = expected_artifact_size_bytes
        self.expected_quantization = expected_quantization
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self.max_output_tokens = max(768, min(int(max_output_tokens), 2048))
        self.context_length = max(8192, min(int(context_length), 32768))
        self.temperature = max(0.0, min(float(temperature), 1.0))
        template = PROMPT_PATH.read_text(encoding="utf-8")
        semantic_schema = c.SEMANTIC_DECISION_ADAPTER.json_schema()
        schema_text = json.dumps(semantic_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if "{{SEMANTIC_DECISION_SCHEMA}}" not in template:
            raise ValueError("prompt is missing the generated semantic schema placeholder")
        self.system_prompt = template.replace("{{SEMANTIC_DECISION_SCHEMA}}", schema_text)
        self.semantic_schema_sha256 = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
        self.system_prompt_sha256 = hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()
        self._loaded_instance_id: str | None = None
        self._auth_token = os.environ.get("LMSTUDIO_API_TOKEN", "")

    def _request(self, url: str, *, payload: dict[str, Any] | None = None, method: str = "GET") -> tuple[int, bytes]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self._auth_token:
            headers["Authorization"] = "Bearer " + self._auth_token
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise LMStudioError("response_too_large", http_status=response.status)
                return response.status, body
        except urllib.error.HTTPError as error:
            raise LMStudioError("http_error", http_status=error.code) from None
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, TimeoutError):
                raise LMStudioError("timeout") from None
            raise LMStudioError("connection_error") from None
        except (TimeoutError, OSError) as error:
            if isinstance(error, TimeoutError):
                raise LMStudioError("timeout") from None
            raise LMStudioError("connection_error") from None

    def inspect_loaded_candidate(self) -> dict[str, Any]:
        """Read catalog and local file metadata; never loads or manages a model."""
        _, body = self._request(self.models_endpoint)
        try:
            document = json.loads(body)
            models = document["models"]
        except (ValueError, TypeError, KeyError):
            raise LMStudioError("catalog_schema_error") from None
        if not isinstance(models, list):
            raise LMStudioError("catalog_schema_error")
        matches = [model for model in models if isinstance(model, dict) and model.get("key") == self.model_key]
        if len(matches) != 1:
            raise LMStudioError("candidate_key_missing_or_ambiguous")
        candidate = matches[0]
        quantization = candidate.get("quantization")
        quant_name = quantization.get("name") if isinstance(quantization, dict) else None
        instances = candidate.get("loaded_instances")
        if candidate.get("type") != "llm" or quant_name != self.expected_quantization:
            raise LMStudioError("candidate_metadata_mismatch")
        if not isinstance(instances, list) or len(instances) != 1:
            raise LMStudioError("candidate_instance_missing_or_ambiguous")
        instance_id = instances[0].get("id") if isinstance(instances[0], dict) else None
        if not isinstance(instance_id, str) or not instance_id:
            raise LMStudioError("candidate_instance_id_missing")
        config = instances[0].get("config", {})
        context_length = config.get("context_length") if isinstance(config, dict) else None
        parallel = config.get("parallel") if isinstance(config, dict) else None
        if not isinstance(context_length, int) or context_length < self.context_length:
            raise LMStudioError("candidate_context_below_preregistered_minimum")
        if parallel != 1:
            raise LMStudioError("candidate_parallelism_mismatch")
        reasoning = candidate.get("reasoning")
        allowed_reasoning = reasoning.get("allowed_options", []) if isinstance(reasoning, dict) else []
        if "off" not in allowed_reasoning:
            raise LMStudioError("reasoning_off_not_advertised")
        try:
            stat = self.artifact_path.stat()
        except OSError:
            raise LMStudioError("candidate_artifact_metadata_unavailable") from None
        catalog_size = candidate.get("size_bytes")
        if stat.st_size != self.expected_artifact_size_bytes or catalog_size != stat.st_size:
            raise LMStudioError("candidate_artifact_size_mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", self.expected_artifact_sha256):
            raise LMStudioError("candidate_artifact_sha256_invalid")
        # The v1 catalog does not expose the loaded file path. This verifies a
        # prior-index hash and matching local/catalog size but cannot prove the
        # loaded key is cryptographically bound to that file without rehashing.
        self._loaded_instance_id = instance_id
        return {
            "key": candidate["key"],
            "type": candidate["type"],
            "quantization": quant_name,
            "size_bytes": stat.st_size,
            "artifact_sha256_from_prior_index": self.expected_artifact_sha256,
            "artifact_file_id": {"device": getattr(stat, "st_dev", None), "inode": getattr(stat, "st_ino", None)},
            "loaded_key_to_file_binding": "UNVERIFIED_CATALOG_DOES_NOT_EXPOSE_PATH",
            "params_string": candidate.get("params_string"),
            "loaded_instance_id": instance_id,
            "context_length": context_length,
            "parallel": parallel,
            "reasoning_allowed_options": allowed_reasoning,
            "reasoning_requested": "off",
            "semantic_schema_sha256": self.semantic_schema_sha256,
            "system_prompt_sha256": self.system_prompt_sha256,
        }

    def infer(self, prompt: ModelPrompt) -> InferenceResult:
        if self._loaded_instance_id is None:
            raise LMStudioError("candidate_catalog_preflight_required")
        payload = {
            "model": self.model_key,
            "input": _prompt_text(prompt),
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "context_length": self.context_length,
            "reasoning": "off",
            "stream": False,
            "store": False,
        }
        started = time.monotonic()
        status, body = self._request(self.endpoint, payload=payload, method="POST")
        elapsed = round(time.monotonic() - started, 3)
        try:
            document = json.loads(body)
        except (ValueError, TypeError):
            return InferenceResult("invalid_json_response", "", elapsed, None, None, None, None, None, None, (), status)
        instance_id = document.get("model_instance_id") if isinstance(document, dict) else None
        output = document.get("output") if isinstance(document, dict) else None
        if not isinstance(output, list):
            return InferenceResult("invalid_response_schema", "", elapsed, instance_id if isinstance(instance_id, str) else None, None, None, None, None, None, (), status)
        output_kinds = tuple(str(item.get("type", "unknown")) for item in output if isinstance(item, dict))
        messages = [item for item in output if isinstance(item, dict) and item.get("type") == "message"]
        if instance_id != self._loaded_instance_id:
            return InferenceResult("wrong_model_instance", "", elapsed, instance_id if isinstance(instance_id, str) else None, None, None, None, None, None, output_kinds, status)
        if any(kind in {"tool_call", "invalid_tool_call"} for kind in output_kinds):
            return InferenceResult("unexpected_tool_output", "", elapsed, instance_id, None, None, None, None, None, output_kinds, status)
        text = "\n".join(item["content"] for item in messages if isinstance(item.get("content"), str))
        stats = document.get("stats", {}) if isinstance(document, dict) else {}
        stats = stats if isinstance(stats, dict) else {}
        status_label = "empty_content" if not text.strip() else "response_received"
        return InferenceResult(
            status_label,
            text,
            elapsed,
            instance_id,
            _safe_number(stats.get("input_tokens"), int),
            _safe_number(stats.get("total_output_tokens"), int),
            _safe_number(stats.get("reasoning_output_tokens"), int),
            _safe_number(stats.get("tokens_per_second"), float),
            _safe_number(stats.get("time_to_first_token_seconds"), float),
            output_kinds,
            status,
        )

    async def generate(self, prompt: ModelPrompt) -> InferenceResult:
        return await asyncio.to_thread(self.infer, prompt)


def resource_snapshot() -> dict[str, Any]:
    """Read free system RAM and the primary GPU's free VRAM without app control."""
    free_ram_gib: float | None = None
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        memory = MemoryStatusEx()
        memory.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            free_ram_gib = round(memory.ullAvailPhys / (1024**3), 2)

    free_vram_mib: int | None = None
    try:
        output = subprocess.run(
            ["nvidia-smi.exe", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip().splitlines()
        values = [int(line.strip()) for line in output if re.fullmatch(r"\s*\d+\s*", line)]
        if len(values) == 1:
            free_vram_mib = values[0]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return {"free_ram_gib": free_ram_gib, "free_vram_mib": free_vram_mib}


def check_resource_floor(snapshot: dict[str, Any], phase: str, config: dict[str, Any]) -> dict[str, Any]:
    thresholds = config["resource_thresholds"]
    if phase == "before_load":
        min_ram = thresholds["before_load_ram_gib"]
        min_vram = thresholds["before_load_vram_mib"]
    elif phase == "ready":
        min_ram = thresholds["ready_ram_gib"]
        min_vram = thresholds["ready_vram_mib"]
    else:
        raise ValueError("phase must be before_load or ready")
    missing = snapshot["free_ram_gib"] is None or snapshot["free_vram_mib"] is None
    passed = not missing and snapshot["free_ram_gib"] >= min_ram and snapshot["free_vram_mib"] >= min_vram
    return {
        "phase": phase,
        "passed": passed,
        "free_ram_gib": snapshot["free_ram_gib"],
        "required_free_ram_gib": min_ram,
        "free_vram_mib": snapshot["free_vram_mib"],
        "required_free_vram_mib": min_vram,
    }
