"""Closed parser and deterministic mock provider for the P1-05 Harness."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import contracts as c, mock_fixtures


class ModelPrompt(BaseModel):
    """Only a typed Harness context and one sanitized repair hint reach a provider."""

    model_config = ConfigDict(extra="forbid", strict=True)
    context: c.ModelContext
    repair_feedback: str | None = Field(default=None, max_length=256)


class ModelOutputError(ValueError):
    """Model response was not a valid closed semantic decision for this context."""


def parse_model_output(raw: str, context: c.ModelContext) -> c.SemanticDecision:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8", "ignore")) > 16_384:
        raise ModelOutputError("model response size is invalid")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def no_constant(value: str) -> Any:
        raise ValueError("non-standard JSON value")

    try:
        document = json.loads(raw, object_pairs_hook=unique, parse_constant=no_constant)
        if not isinstance(document, dict):
            raise ValueError("decision must be an object")
        # Use JSON mode for date/time strings inside WriteIntent while retaining
        # the duplicate-key and non-standard-constant checks above.  The Python
        # mode adapter is intentionally strict about datetime objects and would
        # reject a valid wire timestamp such as ``2026-10-07T00:00:00Z``.
        decision = c.SEMANTIC_DECISION_ADAPTER.validate_json(raw)
        c.validate_decision_against_context(decision, context)
        return decision
    except (ValueError, ValidationError, TypeError, json.JSONDecodeError, RecursionError):
        raise ModelOutputError("model response failed closed semantic validation") from None


class MockModelProvider:
    """Deterministic, asynchronous behavior for local simulation and tests only."""

    def __init__(self, *, scripted_responses: Sequence[str | BaseException] = (), delay_seconds: float = 0) -> None:
        self._script = list(scripted_responses)
        self._script_lock = asyncio.Lock()
        self._delay = max(0.0, min(float(delay_seconds), 30.0))
        self._closed = False

    def start(self) -> None:
        self._closed = False

    def health(self) -> Any:
        from .ports import ProviderHealth
        return ProviderHealth(status="simulation", inference_available=False)

    async def generate(self, prompt: ModelPrompt) -> str:
        if self._closed:
            raise RuntimeError("mock provider is closed")
        if self._delay:
            await asyncio.sleep(self._delay)
        async with self._script_lock:
            if self._script:
                item = self._script.pop(0)
                if isinstance(item, BaseException):
                    raise item
                return item
        return _deterministic_output(prompt)

    def close(self) -> None:
        self._closed = True


def _decision_json(decision: c.SemanticDecision) -> str:
    return json.dumps(decision.model_dump(mode="json", by_alias=True, exclude_none=False),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deterministic_output(prompt: ModelPrompt) -> str:
    context = prompt.context
    conversation = " ".join([*(item.text for item in context.recent_messages), context.input_text])
    if prompt.repair_feedback:
        if context.verified_scope.kind == "none":
            return _decision_json(c.AnswerDecision(kind="answer", basis="conversation",
                text="我可以继续帮你整理这段对话。", citations=[]))
        if context.read_results:
            fact = next((fact for result in context.read_results for fact in result.body.items), None)
            if fact is not None:
                return _decision_json(c.AnswerDecision(kind="answer", basis="grounded",
                    text="这是当前模拟数据中的一条记录。", citations=[fact.evidence_ref]))
        return _clarification_json()

    text = context.input_text
    if context.verified_scope.kind == "none":
        if any(word in text for word in ("确认", "执行", "写入", "规则", "可以记录吗")) and context.policy_evidence:
            evidence = context.policy_evidence[0]
            return _decision_json(c.AnswerDecision(kind="answer", basis="grounded",
                text="模拟策略说明：任何写入提议仍需用户确认；此服务不会执行真实写入。",
                citations=[evidence.evidence_ref]))
        return _decision_json(c.AnswerDecision(kind="answer", basis="conversation",
            text="我已收到。当前是模拟运行，尚未读取或修改任何业务数据。", citations=[]))

    proposal_request = _is_proposal_request(conversation) or bool(context.pending_slots)
    if proposal_request:
        adjustment = next((item.text for item in context.recent_messages
                           if item.role == "assistant"
                           and item.text.startswith("Existing simulated proposal: ")), None)
        if adjustment is not None:
            decision = _proposal_for_adjustment(text, adjustment, context)
            return _decision_json(decision) if decision is not None else _clarification_json()
        if _is_update_request(conversation) and not context.read_results:
            return _decision_json(_expense_read(context))
        decision = _proposal_for_text(conversation, context)
        return _decision_json(decision) if decision is not None else _clarification_json()

    if context.read_results:
        fact = next((fact for result in context.read_results for fact in result.body.items), None)
        if fact is not None:
            return _decision_json(c.AnswerDecision(kind="answer", basis="grounded",
                text="这是模拟结果，不能代表当前真实账本数据。", citations=[fact.evidence_ref]))

    if _is_read_request(conversation):
        return _decision_json(_read_for_text(conversation, context))

    if any(word in text for word in ("确认", "执行", "写入", "规则")) and context.policy_evidence:
        evidence = context.policy_evidence[0]
        return _decision_json(c.AnswerDecision(kind="answer", basis="grounded",
            text="模拟策略说明：任何写入提议仍需用户确认；此服务不会执行真实写入。",
            citations=[evidence.evidence_ref]))

    return _decision_json(c.AnswerDecision(kind="answer", basis="conversation",
        text="我已收到。当前是模拟运行，尚未读取或修改任何业务数据。", citations=[]))


def _clarification_json() -> str:
    return _decision_json(c.ClarifyDecision(kind="clarify",
        prompt="请补充金额和币种，我会生成仅供预览的模拟提议。",
        missing_slots=[c.ClarificationSlot.AMOUNT, c.ClarificationSlot.CURRENCY]))


def _is_read_request(text: str) -> bool:
    return any(word in text for word in ("查", "查询", "看一下", "多少", "消费", "欠款", "债务", "支出"))


def _is_proposal_request(text: str) -> bool:
    return any(word in text for word in ("记录", "新增", "添加", "创建", "记一笔", "改成", "更新", "修改"))


def _is_update_request(text: str) -> bool:
    return any(word in text for word in ("改成", "更新", "修改"))


def _read_for_text(text: str, context: c.ModelContext) -> c.ReadDecision:
    if any(word in text for word in ("欠款", "债务", "谁欠")):
        return c.ReadDecision(kind="read", operation=c.ReadOperation.DEBTS,
            criteria=c.ReadDebtsCriteria(kind="debts", activity_ref=context.verified_scope.activity_ref))
    if any(word in text for word in ("活动", "有哪些")):
        return c.ReadDecision(kind="read", operation=c.ReadOperation.ACTIVITIES,
            criteria=c.ReadActivitiesCriteria(kind="activities"))
    return _expense_read(context)


def _expense_read(context: c.ModelContext) -> c.ReadDecision:
    return c.ReadDecision(kind="read", operation=c.ReadOperation.EXPENSES,
        criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=context.verified_scope.activity_ref))


def _proposal_for_text(text: str, context: c.ModelContext) -> c.ProposeDecision | None:
    """Build a small deterministic intent from explicit simulation examples."""
    refs = mock_fixtures.references()
    ref = lambda kind: next(item.ref for item in refs if item.kind == kind)
    amount_match = re.search(r"(?<!\d)(\d{1,8}(?:\.\d{1,2})?)(?!\d)", text)
    is_create = any(word in text for word in ("记录", "新增", "添加", "创建", "记一笔"))
    is_presentation = any(word in text for word in ("备注", "标题", "图标", "描述")) and not is_create
    if not amount_match and is_create:
        return None

    if is_create:
        amount = amount_match.group(1)
        participants = [ref("participant")]
        participant_refs = [item.ref for item in refs if item.kind == "participant"]
        intent = c.ExpenseCreateIntent(
            kind="expense.create",
            ledger_unit_ref=ref("ledger_unit"),
            title=_extract_title(text) or "模拟消费",
            original_amount=amount,
            original_currency=_currency_from_text(text),
            payment_allocations=[c.PaymentAllocation(participant_ref=participants[0], amount=amount)],
            split=c.EqualSplitIntent(mode="equal", participant_refs=participant_refs),
            occurred_at=mock_fixtures.NOW,
        )
    elif is_presentation:
        title = _extract_title(text)
        note = "模拟修改备注" if "备注" in text or title is None else None
        icon = _extract_icon(text) if "图标" in text else None
        intent = c.ExpensePresentationUpdateIntent(
            kind="expense.presentation.update", expense_ref=ref("expense"), title=title,
            note=note, icon_key=icon,
        )
    else:
        if not amount_match:
            return None
        amount = amount_match.group(1)
        participant_refs = [item.ref for item in refs if item.kind == "participant"]
        intent = c.ExpenseUpdateIntent(
            kind="expense.update", expense_ref=ref("expense"),
            original_amount=amount,
            payment_allocations=[c.PaymentAllocation(participant_ref=participant_refs[0], amount=amount)],
            split=c.EqualSplitIntent(mode="equal", participant_refs=participant_refs),
        )
    return c.ProposeDecision(kind="propose", operation=intent.kind, fields=intent)


def _proposal_for_adjustment(
    latest_text: str, summary: str, context: c.ModelContext,
) -> c.ProposeDecision | None:
    """Keep the original simulated write kind while applying the latest fields."""
    summary = summary.removeprefix("Existing simulated proposal: ")
    fields = dict(re.findall(r"(?:^|; )([a-z_]+)=([^;]*)", summary))
    operation = fields.get("operation")
    amount_match = re.search(r"(?<!\d)(\d{1,8}(?:\.\d{1,2})?)(?!\d)", latest_text)
    amount = amount_match.group(1) if amount_match else fields.get("original_amount")
    title = _extract_title(latest_text) or fields.get("title")
    refs = mock_fixtures.references()
    ref = lambda kind: next(item.ref for item in refs if item.kind == kind)
    if operation == "expense.create":
        if amount is None:
            return None
        currency = fields.get("original_currency", "CNY")
        if any(marker in latest_text for marker in ("USD", "美元", "$", "EUR", "欧元", "JPY", "日元")):
            currency = _currency_from_text(latest_text)
        amount_text = amount
        participant_refs = [item.ref for item in refs if item.kind == "participant"]
        intent: c.WriteIntent = c.ExpenseCreateIntent(
            kind="expense.create", ledger_unit_ref=ref("ledger_unit"),
            title=title or "模拟消费", original_amount=amount_text,
            original_currency=currency,
            payment_allocations=[c.PaymentAllocation(participant_ref=participant_refs[0], amount=amount_text)],
            split=c.EqualSplitIntent(mode="equal", participant_refs=participant_refs),
            occurred_at=mock_fixtures.NOW,
        )
    elif operation == "expense.update":
        if amount is None and title is None:
            return None
        intent = c.ExpenseUpdateIntent(
            kind="expense.update", expense_ref=ref("expense"),
            title=title if title != fields.get("title") else None,
            original_amount=amount,
            original_currency=fields.get("original_currency") if amount is not None else None,
            payment_allocations=(
                [c.PaymentAllocation(participant_ref=ref("participant"), amount=amount)]
                if amount is not None else None
            ),
            split=(c.EqualSplitIntent(mode="equal", participant_refs=[
                item.ref for item in refs if item.kind == "participant"
            ]) if amount is not None else None),
        )
    elif operation == "expense.presentation.update":
        icon = _extract_icon(latest_text) if "图标" in latest_text else None
        note = "模拟修改备注" if "备注" in latest_text else None
        next_title = title if title != fields.get("title") else None
        if next_title is None and note is None and icon is None:
            # A generic change request can still update the presentation title.
            next_title = title or "模拟消费"
        intent = c.ExpensePresentationUpdateIntent(
            kind="expense.presentation.update", expense_ref=ref("expense"),
            title=next_title, note=note, icon_key=icon,
        )
    else:
        return None
    return c.ProposeDecision(kind="propose", operation=intent.kind, fields=intent)


def _extract_title(text: str) -> str | None:
    match = re.search(r"(?:标题|叫|记录|新增|添加|创建|记一笔)\s*[：:]?\s*[“\"]?([\u3400-\u9fffA-Za-z0-9 _-]{1,32})", text)
    if not match:
        return None
    title = match.group(1).strip(" \t\r\n，。;；:：\"“”")
    title = re.sub(r"\s+\d+$", "", title)
    return title or None


def _currency_from_text(text: str) -> str:
    if "USD" in text.upper() or "美元" in text or "$" in text:
        return "USD"
    if "EUR" in text.upper() or "欧元" in text:
        return "EUR"
    if "JPY" in text.upper() or "日元" in text:
        return "JPY"
    return "CNY"


def _extract_icon(text: str) -> str | None:
    match = re.search(r"(?:图标|icon)\s*[：:]?\s*([a-z0-9_]{1,48})", text, re.IGNORECASE)
    return match.group(1).lower() if match else "receipt"
