"""Opt-in provider bridge for the disabled P2 read-paged candidate.

This module is intentionally not imported by application assembly. It binds a
strict server context and prepared request to the selected local model, then
passes those exact bytes through the existing bounded LM Studio provider path.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .p2_model_provider import (
    LMStudioOpenAIProvider,
    LMStudioProviderError,
    LMStudioProviderErrorCode,
)
from .p2_read_contracts import P2ModelContext
from .p2_local_endpoint import parse_local_p2_endpoint
from .p2_read_prompt import (
    P2PreparedRequest,
    P2PromptBuildConfig,
    P2PromptInputError,
    P2RepairFeedback,
    _strict_repair_feedback,
    build_p2_request,
)


class P2ReadProvider:
    """Disabled-by-default candidate facade over the shared bounded provider.

    The wrapped provider remains responsible for lifecycle state, the single
    concurrency slot, trusted just-in-time token measurement, HTTP dispatch,
    cancellation draining, and OpenAI response parsing. This facade only
    validates that the body belongs to the supplied P2 context and to the
    server-selected model before invoking that common path.
    """

    def __init__(self, provider: LMStudioOpenAIProvider) -> None:
        if type(provider) is not LMStudioOpenAIProvider:
            raise TypeError("provider must be an exact LMStudioOpenAIProvider")
        config = provider._config
        try:
            endpoint = parse_local_p2_endpoint(config.endpoint_url).endpoint_url
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("provider endpoint is outside the local P2 candidate policy") from None
        if (
            config.max_output_tokens != 768
            or float(config.temperature) != 0.0
            or not config.structured_output
            or config.schema_wire_selection is not None
        ):
            raise ValueError("provider config is outside the local P2 candidate wire profile")
        self._provider = provider
        self._endpoint_url = endpoint

    def start(self) -> None:
        """Start only the local adapter state; this does not probe or load a model."""
        self._provider.start()

    def close(self) -> None:
        self._provider.close()

    def health(self):
        return self._provider.health()

    async def generate(
        self,
        context: P2ModelContext,
        prepared: P2PreparedRequest,
        *,
        repair_feedback: P2RepairFeedback | None = None,
    ) -> str:
        """Generate from one exact P2 body or fail before counter/HTTP dispatch.

        This method exposes one bounded prepared-body repair mechanism only; it
        does not retry, choose a repair, or interpret a previous model output.
        """
        self._provider._ensure_available()
        try:
            validated_context = self._strict_context(context)
            validated_prepared = self._strict_prepared(prepared)
            validated_feedback = _strict_repair_feedback(repair_feedback)
            if validated_prepared.repair_feedback != validated_feedback:
                raise ValueError("separately supplied repair feedback does not match the prepared request")
            expected_config = P2PromptBuildConfig(
                model_id=self._provider._config.model_key,
                endpoint_url=self._endpoint_url,
            )
            provider_endpoint = parse_local_p2_endpoint(self._provider._config.endpoint_url).endpoint_url
            if validated_prepared.endpoint_url != provider_endpoint:
                raise ValueError("prepared endpoint does not match the selected local provider")
            if validated_prepared.config != expected_config:
                raise ValueError("prepared model or bounded wire config does not match server settings")
            rebuilt = build_p2_request(
                validated_context, config=expected_config, repair_feedback=validated_feedback
            )
            if validated_prepared != rebuilt:
                raise ValueError("prepared body does not match the supplied server context")
        except (TypeError, ValueError, ValidationError, P2PromptInputError):
            self._provider._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None

        # _generate_bound_body reconstructs the typed counter request from the
        # same body object passed unchanged to the HTTP transport.
        return await self._provider._generate_bound_body(
            validated_prepared.body_bytes,
            expected_body_sha256=validated_prepared.request_sha256,
            initial_state_checked=True,
        )

    @staticmethod
    def _strict_context(context: Any) -> P2ModelContext:
        if type(context) is not P2ModelContext:
            raise TypeError("context must be an exact P2ModelContext")
        return P2ModelContext.model_validate(
            context.model_dump(mode="python", by_alias=True, exclude_none=False),
            strict=True,
        )

    @staticmethod
    def _strict_prepared(prepared: Any) -> P2PreparedRequest:
        if type(prepared) is not P2PreparedRequest:
            raise TypeError("prepared must be an exact P2PreparedRequest")
        return P2PreparedRequest.model_validate(
            prepared.model_dump(mode="python", by_alias=True, exclude_none=False),
            strict=True,
        )
