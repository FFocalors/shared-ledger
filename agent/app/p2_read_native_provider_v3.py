"""Explicit opt-in native-chat candidate for P2 v3 decisions.

This adapter is separate from the compatibility provider facade. It rebuilds
the native system/input body from a strictly reconstructed v3 request, binds
the actual native bytes and counted messages, and delegates only bounded
transport, token counting, lifecycle, and error handling to the shared P2
provider. Native schema text is guidance only; Runtime sent guards remain
authoritative.
"""

from __future__ import annotations

from hashlib import sha256
import json
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
    _canonical_json,
    _strict_feedback,
    _strict_private_intent,
    _strict_public_context,
    build_p2_v3_request,
)
from .p2_read_provider_v3 import P2V3ReadProvider
from .p2_local_endpoint import parse_local_p2_endpoint
from .p2_token_budget import P2TokenBudgetMeasurement


_DIRECT_DECISION_HINT_R3 = """【当前输出协议：P2 v3；direct-decision-hint-r3】
只输出符合本轮 schema 的一条决策 JSON，根对象直接包含 kind。禁止旧的 candidates 数组、arguments 外壳或 type="decision" 包装。
read/query_request 的 message_type、profile_id、versions、operation、criteria、scope 都是根字段；profile_id 和 versions 逐字复制本轮 context，criteria 按 operation 对应 schema 填写。读取请求必须是 kind="read"，不得因尚无来源而改成 kind="answer"。
answer 的根字段是 kind、basis、text、citations，业务引用只取本轮 fresh_receipt_refs。始终只选择本轮 guard 允许的 kind，不输出解释或 Markdown。
根对象不得含 schema 未声明的任何字段；尤其禁止 type、candidates、arguments、content、reason、evidence_refs、intent_id 等旧协议或 MIME 字段。kind=answer 时根对象恰好是 kind、basis、text、citations 四个字段，不得多也不得少，也不得添加 type="application/json"；该 MIME 描述不属于答案。不得把上下文、query evidence 或 page summary 里的任何字段名（如 source_query_complete、model_projection_complete、has_more、range_contiguous、stable_total_verified、unique_items_verified、expected_total 等）复制到答案根对象或任何决策对象中：这些是服务端投影，只能据以判断，不是模型可回述的字段，模型不得把它们当作自己的输出字段。
当 trusted_intent.classification="proposal_intent" 且 guard.allowed_decision_kinds 只包含 "propose" 时，本轮 propose 仅识别用户意图，不预览、不确认、不执行任何业务写入。必须输出根 kind="propose"，operation 只能取自 guard.allowed_proposal_operations，recognized_intent_text 只简要概述用户意图。识别意图不需要财务来源或业务写入执行授权；不得因缺少财务来源或写入执行授权而改成 answer，也不得声称已经执行。正常用户身份校验和本轮服务器 guard 仍须满足；此规则不扩大任何 financial read/source 授权，也不改变其他 kind 的规则。"""


class P2V3NativeCandidateReadProvider(P2V3ReadProvider):
    """A native `/api/v1/chat` candidate, opt-in and never an implicit fallback."""

    def __init__(
        self,
        provider: LMStudioOpenAIProvider,
        *,
        config: P2V3PromptBuildConfig,
    ) -> None:
        super().__init__(provider, config=config)
        timeout = provider._config.request_timeout_seconds
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0.1 <= timeout <= 90:
            raise ValueError("native candidate HTTP timeout must be within 0.1–90 seconds")
        self._native_transport_binding = (
            float(timeout),
            provider._config.max_prompt_bytes,
            provider._config.max_request_bytes,
            provider._config.max_response_bytes,
            provider._config.max_content_bytes,
            provider._config.api_token,
        )

    def _assert_native_provider_binding(self) -> None:
        self._assert_current_provider_binding()
        current = self._provider._config
        if self._native_transport_binding != (
            float(current.request_timeout_seconds),
            current.max_prompt_bytes,
            current.max_request_bytes,
            current.max_response_bytes,
            current.max_content_bytes,
            current.api_token,
        ):
            raise ValueError("native candidate transport limits changed after assembly")

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
        """Send exactly one native body; decision acceptance stays in Runtime."""
        self._provider._ensure_available()
        try:
            self._assert_native_provider_binding()
            public = _strict_public_context(public_context)
            private = _strict_private_intent(private_intent)
            supplied = self._strict_prepared(prepared)
            feedback = _strict_feedback(repair_feedback)
            if feedback != supplied.repair_feedback:
                raise ValueError("separate repair feedback does not match prepared feedback")
            contracts.validate_p2_clarification_projection(public, private)
            rebuilt = build_p2_v3_request(
                public,
                private,
                config=self._bound_config,
                repair_feedback=feedback,
            )
            if supplied.schema_sha256 != rebuilt.schema_sha256 or supplied != rebuilt:
                raise ValueError("prepared v3 request does not rebuild from current server context")

            compat_body = json.loads(supplied.body_bytes.decode("utf-8", errors="strict"))
            if type(compat_body) is not dict:
                raise ValueError("prepared compatibility body is not an object")
            messages = compat_body.get("messages")
            response_format = compat_body.get("response_format")
            if (
                type(messages) is not list
                or len(messages) not in (2, 3)
                or any(type(item) is not dict or set(item) != {"role", "content"} for item in messages)
                or messages[0]["role"] != "system"
                or messages[-1]["role"] != "user"
                or (len(messages) == 3 and messages[1]["role"] != "system")
                or type(response_format) is not dict
                or response_format.get("type") != "json_schema"
                or type(response_format.get("json_schema")) is not dict
                or type(response_format["json_schema"].get("schema")) is not dict
            ):
                raise ValueError("prepared v3 body does not contain its fixed system/user/schema projection")
            schema = response_format["json_schema"]["schema"]
            schema_text = _canonical_json(schema)
            if sha256(schema_text.encode("utf-8")).hexdigest() != supplied.schema_sha256:
                raise ValueError("prepared schema digest does not bind the native text hint")
            system_parts = [messages[0]["content"]]
            if len(messages) == 3:
                system_parts.append(messages[1]["content"])
            system_prompt = (
                "\n\n".join(system_parts)
                + "\n\n[ISOLATED NATIVE CANDIDATE SCHEMA HINT: this endpoint does not receive response_format; "
                  "the following schema text is informational and does not enforce structured output.]\n"
                + schema_text
                + "\n\n"
                + _DIRECT_DECISION_HINT_R3
            )
            input_text = messages[-1]["content"]
            if type(input_text) is not str or type(system_prompt) is not str:
                raise ValueError("prepared native system/input projection is invalid")
            native_payload = {
                "model": self._bound_config.model_id,
                "input": input_text,
                "system_prompt": system_prompt,
                "stream": False,
                "temperature": self._bound_config.temperature,
                "max_output_tokens": self._bound_config.max_output_tokens,
                "reasoning": "off",
                "context_length": 8192,
                "store": False,
            }
            native_body = _canonical_json(native_payload).encode("utf-8")
            native_body_sha256 = sha256(native_body).hexdigest()
            contracts.validate_p2_clarification_projection(public, private)
            self._assert_native_provider_binding()
        except (TypeError, ValueError, ValidationError, P2V3PromptInputError, UnicodeError, json.JSONDecodeError):
            self._provider._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None

        try:
            origin = parse_local_p2_endpoint(self._provider._config.endpoint_url).origin
        except (TypeError, ValueError, ValidationError, UnicodeError):
            self._provider._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None

        def guarded_before_dispatch(
            actual_body_sha256: str,
            measurement: P2TokenBudgetMeasurement,
        ) -> Any:
            self._assert_native_provider_binding()
            if actual_body_sha256 != native_body_sha256:
                raise ValueError("native wire hash changed before dispatch")
            if (
                measurement.model_key != self._bound_config.model_id
                or measurement.api_host != origin
                or measurement.actual_context_tokens != 8192
                or measurement.max_input_tokens != 6144
                or measurement.requested_output_tokens != self._bound_config.max_output_tokens
                or measurement.max_output_tokens != self._bound_config.max_output_tokens
                or measurement.safety_margin_tokens != 512
                or measurement.response_format_tokens != 0
                or measurement.budgeted_input_tokens != measurement.prompt_tokens + 512
                or measurement.budgeted_input_tokens > 6144
            ):
                raise ValueError("native token measurement differs from the pinned body/config budget")
            if before_dispatch is not None:
                return before_dispatch(actual_body_sha256, measurement)
            return None

        return await self._provider._generate_bound_body(
            native_body,
            expected_body_sha256=native_body_sha256,
            initial_state_checked=True,
            native_candidate_wire=True,
            before_dispatch=guarded_before_dispatch,
            on_transport_result=on_transport_result,
        )
