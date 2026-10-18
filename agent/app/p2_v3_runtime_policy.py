"""Small server-side intent gate for the isolated P2 v3 candidate runtime.

This is a conservative routing hint, not a natural-language classifier or a
source-authority check. Ambiguous and unsupported input can only be clarified;
an operation-specific grant is still minted after the model selects a typed
query and the result is still checked by the sent guard and strict parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .p2_read_contracts_v3 import P2ProposalOperation, P2ReadOperation


@dataclass(frozen=True, slots=True)
class P2V3IntentPlan:
    classification: Literal["non_business", "proposal_intent", "factual_business", "ambiguous"]
    operation: P2ReadOperation | None
    proposal_operation: P2ProposalOperation | None
    allowed_decision_kinds: tuple[Literal["answer", "clarify", "read", "propose"], ...]
    allowed_read_operations: tuple[P2ReadOperation, ...]
    allowed_proposal_operations: tuple[P2ProposalOperation, ...]
    source_free_business_answer_allowed: bool
    proposal_clarification_required: bool | None
    proposal_target_resolved: bool
    pending: tuple[tuple[str, str, P2ReadOperation | P2ProposalOperation | None], ...]


_NON_BUSINESS = (
    "你好", "您好", "早上好", "晚上好", "谢谢", "再见", "hello", "hi", "thanks",
    "你能做什么", "你可以做什么", "能帮我什么", "what can you do", "help me",
)
_CREATE = ("新增消费", "新建消费", "添加消费", "记录消费", "记一笔消费", "create expense", "add expense")
_UPDATE = ("修改消费", "编辑消费", "更新消费", "更改消费", "update expense", "edit expense")
_READ_MARKERS: tuple[tuple[P2ReadOperation, tuple[str, ...]], ...] = (
    (P2ReadOperation.PREPAYMENT_RETURN_EVENTS, ("预存返还", "预存退回", "退还预存", "返还记录", "return event")),
    (P2ReadOperation.PREPAYMENT_USAGES, ("预存使用", "使用预存", "预付款使用", "usage")),
    (P2ReadOperation.PREPAYMENT_ACCOUNTS, ("预存账户", "预存余额", "预付款账户", "prepayment account")),
    (P2ReadOperation.REFUND_EVENTS, ("退款记录", "退款", "refund")),
    (P2ReadOperation.DEBTS, ("欠款", "债务", "谁欠", "debt")),
    (P2ReadOperation.EXPENSES, ("消费", "支出", "花费", "账单", "expense")),
    (P2ReadOperation.ACTIVITIES, ("活动列表", "我的活动", "有哪些活动", "活动", "activity")),
)


def classify_p2_v3_input(text: str, *, scope_verified: bool) -> P2V3IntentPlan:
    """Produce a narrow server allowlist; keep the original input untouched."""
    if type(text) is not str or not text.strip() or len(text) > 4000 or type(scope_verified) is not bool:
        raise ValueError("invalid candidate input classification request")
    detector = text.casefold().strip()

    # Greetings/capability questions are source-free only when the whole input
    # is non-business. A greeting prefixed to a ledger request cannot suppress
    # the financial route.
    if detector in _NON_BUSINESS:
        return P2V3IntentPlan(
            classification="non_business", operation=None, proposal_operation=None,
            allowed_decision_kinds=("answer",), allowed_read_operations=(),
            allowed_proposal_operations=(), source_free_business_answer_allowed=True,
            proposal_clarification_required=None, proposal_target_resolved=False, pending=(),
        )

    if any(marker in detector for marker in _CREATE):
        return P2V3IntentPlan(
            classification="proposal_intent", operation=None,
            proposal_operation=P2ProposalOperation.EXPENSE_CREATE,
            allowed_decision_kinds=("propose",), allowed_read_operations=(),
            allowed_proposal_operations=(P2ProposalOperation.EXPENSE_CREATE,),
            source_free_business_answer_allowed=False, proposal_clarification_required=False,
            proposal_target_resolved=True, pending=(),
        )
    if any(marker in detector for marker in _UPDATE):
        proposal = P2ProposalOperation.EXPENSE_UPDATE
        return P2V3IntentPlan(
            classification="proposal_intent", operation=None, proposal_operation=proposal,
            allowed_decision_kinds=("clarify",), allowed_read_operations=(),
            allowed_proposal_operations=(), source_free_business_answer_allowed=False,
            proposal_clarification_required=True, proposal_target_resolved=False,
            pending=(("proposal_target", "required_target_missing", proposal),),
        )

    matches = [operation for operation, markers in _READ_MARKERS if any(marker in detector for marker in markers)]
    if P2ReadOperation.ACTIVITIES in matches and len(matches) > 1:
        # "活动" often names the scope for a separate read operation.
        matches.remove(P2ReadOperation.ACTIVITIES)
    if len(matches) != 1:
        return P2V3IntentPlan(
            classification="ambiguous", operation=None, proposal_operation=None,
            allowed_decision_kinds=("clarify",), allowed_read_operations=(),
            allowed_proposal_operations=(), source_free_business_answer_allowed=False,
            proposal_clarification_required=None, proposal_target_resolved=False,
            pending=(("activity_scope", "ambiguous_user_reference", None),),
        )

    operation = matches[0]
    if operation != P2ReadOperation.ACTIVITIES and not scope_verified:
        return P2V3IntentPlan(
            classification="factual_business", operation=operation, proposal_operation=None,
            allowed_decision_kinds=("clarify",), allowed_read_operations=(),
            allowed_proposal_operations=(), source_free_business_answer_allowed=False,
            proposal_clarification_required=None, proposal_target_resolved=False,
            pending=(("activity_scope", "missing_required_scope", operation),),
        )

    return P2V3IntentPlan(
        classification="factual_business", operation=operation, proposal_operation=None,
        allowed_decision_kinds=("read",),
        allowed_read_operations=(operation,), allowed_proposal_operations=(),
        source_free_business_answer_allowed=False, proposal_clarification_required=None,
        proposal_target_resolved=False, pending=(),
    )
