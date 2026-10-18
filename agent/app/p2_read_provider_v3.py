"""Opt-in facade for sending exact P2 v3 candidate bodies via the shared provider.

This module is not imported by application assembly. It validates the paired
public/private v3 context and prepared bytes, then uses the existing single
counter/transport/parse/drain path without selecting or retrying decisions.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import ValidationError

from . import p2_read_contracts_v3 as contracts
from .p2_model_provider import (
    LMStudioOpenAIProvider,
    LMStudioProviderError,
    LMStudioProviderErrorCode,
    LMStudioTransportObservation,
)
from .p2_read_prompt_v3 import (
    P2V3PreparedRequest,
    P2V3PromptBuildConfig,
    P2V3PromptInputError,
    P2V3RepairFeedback,
    _strict_config,
    _strict_feedback,
    _strict_private_intent,
    _strict_public_context,
    build_p2_v3_request,
)
from .p2_local_endpoint import parse_local_p2_endpoint
from .p2_token_budget import P2TokenBudgetMeasurement


class P2V3ReadProvider:
    """Disabled-by-default candidate facade around one shared provider instance.

    This facade returns raw completion text. It does not parse/authorize reads,
    access source data, choose repair, or decide whether a result is acceptable.
    """

    def __init__(
        self,
        provider: LMStudioOpenAIProvider,
        *,
        config: P2V3PromptBuildConfig,
    ) -> None:
        if type(provider) is not LMStudioOpenAIProvider:
            raise TypeError("provider must be an exact LMStudioOpenAIProvider")
        try:
            selected = _strict_config(config)
            provider_endpoint = parse_local_p2_endpoint(provider._config.endpoint_url)
        except (TypeError, ValueError, ValidationError, UnicodeError, P2V3PromptInputError):
            raise ValueError("v3 server config is outside the reviewed local candidate policy") from None
        provider_config = provider._config
        if (
            selected.model_id != provider_config.model_key
            or selected.endpoint_url != provider_endpoint.endpoint_url
            or provider_config.max_output_tokens != selected.max_output_tokens
            or float(provider_config.temperature) != selected.temperature
            or not provider_config.structured_output
            or provider_config.schema_wire_selection is not None
            or provider_config.max_concurrency != selected.parallel_requests
        ):
            raise ValueError("v3 prompt config does not match the shared provider's server selection")
        self._provider = provider
        self._bound_config = selected
        self._assert_current_provider_binding()

    def start(self) -> None:
        """Start only the adapter state; does not probe or load a model."""
        self._provider.start()

    async def prepare(self) -> None:
        """Prepare the bound counter session before Runtime starts its scheduler."""
        self.start()
        await self._provider.prepare()

    def close(self) -> None:
        self._provider.close()

    def health(self):
        return self._provider.health()

    async def generate(
        self,
        public_context: contracts.P2ModelContext,
        private_intent: contracts.P2IntentContext,
        prepared: P2V3PreparedRequest,
        *,
        repair_feedback: P2V3RepairFeedback | None = None,
        before_dispatch: Callable[[str, P2TokenBudgetMeasurement], None] | None = None,
        on_transport_result: Callable[[LMStudioTransportObservation], None] | None = None,
    ) -> str:
        """Validate and send one exact body; format repair is caller-controlled."""
        self._provider._ensure_available()
        try:
            self._assert_current_provider_binding()
            public = _strict_public_context(public_context)
            private = _strict_private_intent(private_intent)
            supplied = self._strict_prepared(prepared)
            feedback = _strict_feedback(repair_feedback)
            if feedback != supplied.repair_feedback:
                raise ValueError("separate repair feedback does not match prepared feedback")

            # First enforce exact public/private projection equality before any
            # body generation. The builder independently repeats this check.
            contracts.validate_p2_clarification_projection(public, private)
            rebuilt = build_p2_v3_request(
                public,
                private,
                config=self._bound_config,
                repair_feedback=feedback,
            )
            if supplied.schema_sha256 != rebuilt.schema_sha256:
                raise ValueError("prepared decision schema differs from the validated server allowlist")
            if supplied != rebuilt:
                raise ValueError("prepared request does not rebuild from current v3 inputs")
            if supplied.body_bytes != rebuilt.body_bytes or supplied.request_sha256 != rebuilt.request_sha256:
                raise ValueError("prepared body or hash differs from current v3 reconstruction")

            # Recheck the public/private pair immediately before entering the
            # shared counter/dispatch path, so a forged or mismatched DTO never
            # reaches JIT counting.
            contracts.validate_p2_clarification_projection(public, private)
            self._assert_current_provider_binding()
        except (TypeError, ValueError, ValidationError, P2V3PromptInputError):
            self._provider._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None

        def guarded_before_dispatch(
            actual_body_sha256: str,
            measurement: P2TokenBudgetMeasurement,
        ) -> Any:
            # The shared provider waits for its gate and token checker before
            # invoking this synchronous callback. Revalidate the selected
            # endpoint/config at that exact boundary, not only before either
            # await, so a config replacement cannot redirect a prepared body.
            self._assert_current_provider_binding()
            if actual_body_sha256 != supplied.request_sha256:
                raise ValueError("v3 prepared body hash changed before dispatch")
            expected_origin = parse_local_p2_endpoint(supplied.endpoint_url).origin
            if (
                measurement.model_key != supplied.config.model_id
                or measurement.api_host != expected_origin
            ):
                raise ValueError("v3 token measurement differs from prepared model/origin")
            if before_dispatch is not None:
                # Preserve the shared provider's hook contract. Its validator
                # rejects any non-None value and any awaitable, and sanitizes
                # callback exceptions before the transport can be dispatched.
                return before_dispatch(actual_body_sha256, measurement)
            return None

        return await self._provider._generate_bound_body(
            supplied.body_bytes,
            expected_body_sha256=supplied.request_sha256,
            initial_state_checked=True,
            before_dispatch=guarded_before_dispatch,
            on_transport_result=on_transport_result,
        )

    def _assert_current_provider_binding(self) -> None:
        """Refuse cached bodies if the wrapped provider's selected wire target drifts."""
        try:
            current = self._provider._config
            endpoint = parse_local_p2_endpoint(current.endpoint_url)
        except (AttributeError, TypeError, ValueError, ValidationError, UnicodeError):
            raise ValueError("shared provider selection no longer matches the v3 prepared binding") from None
        expected = self._bound_config
        if (
            current.model_key != expected.model_id
            or endpoint.endpoint_url != expected.endpoint_url
            or current.max_output_tokens != expected.max_output_tokens
            or float(current.temperature) != expected.temperature
            or current.structured_output is not expected.structured_output
            or current.schema_wire_selection is not None
            or current.max_concurrency != expected.parallel_requests
        ):
            raise ValueError("shared provider selection no longer matches the v3 prepared binding")

    @staticmethod
    def _strict_prepared(prepared: Any) -> P2V3PreparedRequest:
        if type(prepared) is not P2V3PreparedRequest:
            raise TypeError("prepared must be an exact P2V3PreparedRequest")
        return P2V3PreparedRequest.model_validate(
            prepared.model_dump(mode="python", by_alias=True, exclude_none=False),
            strict=True,
        )

