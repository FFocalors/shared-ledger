"""Explicit P1-02 service configuration; importing this module performs no I/O."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = AGENT_ROOT / ".env"


class ConfigurationError(RuntimeError):
    """Sanitized configuration error suitable for a one-line CLI message."""


class Settings(BaseSettings):
    """Validated settings with environment-over-dotenv precedence.

    Relative storage paths are anchored to the tracked ``agent/`` directory, not
    to the caller's current working directory. No path is created during parsing.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    storage_path: Path
    listen_host: str = "127.0.0.1"
    listen_port: int = Field(default=8765, ge=1, le=65535)
    provider_mode: Literal["disabled", "mock", "p2"] = "disabled"
    model_concurrency: int = Field(default=1, ge=1, le=1)
    runtime_task_concurrency: int = Field(default=4, ge=1, le=8)
    mock_model_timeout_seconds: float = Field(default=2.0, ge=0.05, le=10.0)
    p2_lmstudio_enabled: bool = False
    p2_lmstudio_model_key: str = "local-model"
    p2_lmstudio_endpoint_url: str = "http://127.0.0.1:1234/v1/chat/completions"
    p2_lmstudio_api_token: SecretStr | None = None
    p2_token_budget_enabled: bool = False
    p2_model_artifact_path: Path | None = None
    p2_lmstudio_model_path: str | None = None
    p2_model_artifact_sha256: str | None = None
    p2_model_artifact_size_bytes: int | None = Field(default=None, ge=1)
    p2_model_context_tokens: int = Field(default=8192, ge=1, le=8192)
    p2_max_input_tokens: int = Field(default=6144, ge=1, le=6144)
    p2_schema_safety_margin_tokens: int = Field(default=512, ge=0, le=512)
    p2_token_counter_python: Path | None = None
    p2_token_counter_deadline_seconds: float = Field(default=5.0, ge=0.1, le=5.0)
    p2_model_timeout_seconds: float = Field(default=30.0, ge=0.1, le=90.0)
    p2_max_output_tokens: int = Field(default=768, ge=1, le=1536)
    p2_max_prompt_bytes: int = Field(default=49_152, ge=256, le=49_152)
    p2_max_request_bytes: int = Field(default=65_536, ge=512, le=65_536)
    p2_max_response_bytes: int = Field(default=32_768, ge=256, le=32_768)
    p2_max_content_bytes: int = Field(default=16_384, ge=1, le=16_384)
    p2_v3_candidate_enabled: bool = False
    p2_v3_native_candidate_enabled: bool = False
    p2_v3_execution_manifest_path: Path | None = None
    p2_v3_execution_manifest_sha256: str | None = None
    p2_v3_execution_repository_root: Path | None = None
    p2_v3_execution_external_component_roots: dict[str, Path] = Field(default_factory=dict)
    p2_turn_grant_lease_seconds: int = Field(default=300, ge=30, le=300)
    p2_turn_grant_max_entries: int = Field(default=1024, ge=1, le=4096)
    p2_max_model_calls: int = Field(default=6, ge=1, le=6)
    p2_max_read_calls: int = Field(default=4, ge=1, le=4)
    p2_max_repair_calls: int = Field(default=1, ge=0, le=1)
    p2_journal_path: Path | None = None
    runtime_shutdown_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10.0)
    supabase_auth_base_url: str | None = None
    supabase_api_key: SecretStr | None = None
    allow_insecure_loopback_auth_http: bool = False
    cursor_signing_secret: SecretStr | None = None
    agent_enabled: bool = False
    disable_revision: int = Field(default=1, ge=0)
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    api_requests_per_minute: int = Field(default=120, ge=1, le=10000)

    @field_validator("supabase_api_key", "cursor_signing_secret", "p2_lmstudio_api_token", mode="before")
    @classmethod
    def blank_optional_secrets_are_unset(cls, value: object) -> object:
        # Keep an empty value in the checked-in env example equivalent to an
        # omitted optional secret, without weakening required storage_path.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("storage_path", mode="before")
    @classmethod
    def storage_path_is_present(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError("required")
        return value

    @field_validator("storage_path")
    @classmethod
    def storage_path_is_stable(cls, value: Path) -> Path:
        try:
            path = value.expanduser()
            if not path.is_absolute():
                path = AGENT_ROOT / path
            return path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            raise ValueError("path cannot be resolved") from None

    @field_validator("listen_host")
    @classmethod
    def listen_host_is_valid(cls, value: str) -> str:
        if not value or value != value.strip() or any(char in value for char in "/\\\r\n\t"):
            raise ValueError("invalid host")
        return value

    @field_validator("supabase_auth_base_url")
    @classmethod
    def auth_url_is_trusted_and_explicit(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if value != value.strip() or any(char in value for char in "\r\n\t"):
            raise ValueError("invalid Auth endpoint")
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            # Accessing .port forces urllib's parser to reject malformed or
            # out-of-range port values rather than deferring failure to runtime.
            _ = parsed.port
            if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("invalid Auth endpoint")
            if parsed.path not in ("", "/", "/auth/v1", "/auth/v1/"):
                raise ValueError("Auth endpoint path must be the project root or /auth/v1")
            if parsed.scheme not in ("https", "http"):
                raise ValueError("Auth endpoint must use HTTPS")
            return value.rstrip("/")
        except (UnicodeError, ValueError):
            raise ValueError("invalid Auth endpoint") from None

    @field_validator("supabase_api_key")
    @classmethod
    def api_key_is_public_client_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        if not raw or any(char in raw for char in "\r\n\t"):
            raise ValueError("invalid API key")
        if raw.startswith("sb_secret_"):
            raise ValueError("secret API keys are not accepted for Auth verification")
        parts = raw.split(".")
        if len(parts) == 3 and parts[1]:
            try:
                payload = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
                claims = json.loads(payload)
            except (ValueError, UnicodeError, json.JSONDecodeError):
                claims = None
            if isinstance(claims, dict) and claims.get("role") == "service_role":
                raise ValueError("service role API keys are not accepted for Auth verification")
        return value

    @field_validator("cursor_signing_secret")
    @classmethod
    def cursor_secret_has_entropy_floor(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("cursor secret must be at least 32 bytes")
        return value

    @field_validator("p2_journal_path", mode="before")
    @classmethod
    def p2_journal_path_is_absolute(cls, value: object) -> object:
        if value is None:
            return None
        try:
            path = Path(value)
            if not path.is_absolute():
                raise ValueError("journal path must be absolute")
            return path.resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ValueError("journal path must be absolute") from None

    @field_validator("p2_model_artifact_path", "p2_token_counter_python", mode="before")
    @classmethod
    def p2_token_budget_paths_are_absolute(cls, value: object) -> object:
        if value is None:
            return None
        try:
            path = Path(value)
            if not path.is_absolute():
                raise ValueError("path must be absolute")
            return path.resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ValueError("P2 token budget paths must be absolute") from None

    @field_validator(
        "p2_v3_execution_manifest_path", "p2_v3_execution_repository_root",
        mode="before",
    )
    @classmethod
    def p2_v3_paths_are_absolute(cls, value: object) -> object:
        if value is None:
            return None
        try:
            path = Path(value)
            if not path.is_absolute():
                raise ValueError("path must be absolute")
            return path.resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ValueError("P2 v3 execution paths must be absolute") from None

    @field_validator("p2_v3_execution_external_component_roots", mode="before")
    @classmethod
    def p2_v3_external_roots_are_absolute(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("external component roots must be a mapping")
        try:
            roots: dict[str, Path] = {}
            for key, raw_path in value.items():
                if type(key) is not str or not key or len(key) > 128:
                    raise ValueError("invalid external component key")
                path = Path(raw_path)
                if not path.is_absolute():
                    raise ValueError("path must be absolute")
                roots[key] = path.resolve(strict=False)
            return roots
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ValueError("P2 v3 external component paths must be absolute") from None

    @field_validator("p2_v3_execution_manifest_sha256")
    @classmethod
    def p2_v3_manifest_hash_is_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("P2 v3 execution manifest hash must be SHA-256")
        return value.casefold()

    @field_validator("p2_model_artifact_sha256")
    @classmethod
    def p2_artifact_hash_is_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("P2 model artifact hash must be SHA-256")
        return value.casefold()

    @model_validator(mode="after")
    def loopback_http_requires_explicit_opt_in(self) -> "Settings":
        if self.p2_max_prompt_bytes > self.p2_max_request_bytes:
            raise ValueError("P2 prompt bytes cannot exceed request bytes")
        if self.p2_max_content_bytes > self.p2_max_response_bytes:
            raise ValueError("P2 content bytes cannot exceed response bytes")
        if self.p2_max_output_tokens > self.p2_model_context_tokens:
            raise ValueError("P2 output budget cannot exceed the configured context length")
        if self.p2_max_input_tokens + self.p2_max_output_tokens > self.p2_model_context_tokens:
            raise ValueError("P2 input and output budgets exceed the configured context length")
        if self.p2_v3_native_candidate_enabled and not self.p2_v3_candidate_enabled:
            raise ValueError("P2 native v3 candidate requires the v3 candidate gate")
        if self.p2_model_timeout_seconds > 30.0 and not self.p2_v3_native_candidate_enabled:
            raise ValueError("P2 HTTP timeout above 30 seconds is available only to the native v3 candidate")
        if self.p2_v3_native_candidate_enabled and self.provider_mode != "p2":
            raise ValueError("P2 native v3 candidate requires provider_mode=p2")
        if self.p2_token_budget_enabled:
            if any(value is None for value in (
                self.p2_model_artifact_path,
                self.p2_lmstudio_model_path,
                self.p2_model_artifact_sha256,
                self.p2_model_artifact_size_bytes,
                self.p2_token_counter_python,
            )):
                raise ValueError("P2 token budget requires an explicit frozen model and counter binding")
            if not self.p2_lmstudio_model_path or len(self.p2_lmstudio_model_path) > 512:
                raise ValueError("P2 LM Studio model path is invalid")
        if self.p2_v3_candidate_enabled:
            if self.provider_mode != "p2" or not self.p2_lmstudio_enabled:
                raise ValueError("P2 v3 candidate requires the P2 provider and LM Studio to be enabled")
            if not self.p2_token_budget_enabled:
                raise ValueError("P2 v3 candidate requires the exact token budget gate")
            if (
                self.p2_model_context_tokens != 8192
                or self.p2_max_input_tokens != 6144
                or self.p2_schema_safety_margin_tokens != 512
                or self.p2_max_input_tokens + self.p2_max_output_tokens + self.p2_schema_safety_margin_tokens
                > self.p2_model_context_tokens
            ):
                raise ValueError("P2 v3 candidate requires its fixed reviewed token budgets")
            if any(value is None for value in (
                self.p2_v3_execution_manifest_path,
                self.p2_v3_execution_manifest_sha256,
                self.p2_v3_execution_repository_root,
            )):
                raise ValueError("P2 v3 candidate requires a pinned execution cohort")
        if self.provider_mode == "p2":
            if self.supabase_auth_base_url is None or self.supabase_api_key is None:
                raise ValueError("P2 mode requires the configured Supabase Auth project and public API key")
            journal = self.p2_journal_path or self.storage_path.with_suffix(".p2journal.sqlite3")
            if not journal.is_absolute() or journal.drive.upper() != "D:":
                raise ValueError("P2 journal must be on the D: drive")
        value = self.supabase_auth_base_url
        if value is None:
            return self
        parsed = urlsplit(value)
        if parsed.scheme != "http":
            return self
        host = parsed.hostname or ""
        loopback = host.lower() == "localhost"
        try:
            loopback = loopback or ip_address(host).is_loopback
        except ValueError:
            pass
        if not loopback or not self.allow_insecure_loopback_auth_http:
            raise ValueError("plain HTTP Auth is allowed only for explicitly enabled loopback development")
        return self


def load_settings() -> Settings:
    """Read ``agent/.env`` and process environment at an explicit call site."""
    try:
        return Settings()
    except ValidationError as exc:
        fields = sorted({str(error.get("loc", ("configuration",))[0]) for error in exc.errors()})
        if "storage_path" in fields:
            raise ConfigurationError(
                "AGENT_STORAGE_PATH is required and must be a valid path; copy agent/.env.example to agent/.env"
            ) from None
        if fields:
            env_names = ", ".join("AGENT_" + name.upper() for name in fields)
            raise ConfigurationError("invalid service configuration for " + env_names) from None
        raise ConfigurationError("invalid service configuration") from None
