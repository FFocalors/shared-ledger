from __future__ import annotations

import pytest

from agent.app.components import _CandidateProfileStore
from agent.app.p2_read_contracts_v3 import P2ProposalOperation, P2ReadOperation
from agent.app.p2_v3_runtime_policy import classify_p2_v3_input
from agent.app.settings import Settings


def test_candidate_profile_store_selects_only_the_server_profile() -> None:
    class Store:
        def __init__(self) -> None:
            self.calls = []

        def submit_turn(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return "receipt"

        def get_turn(self, *args, **kwargs):
            return "turn"

    inner = Store()
    wrapper = _CandidateProfileStore(inner, "p2.read-paged-prepayment-refund.v3-candidate")
    assert wrapper.submit_turn("owner", "session", "request") == "receipt"
    assert inner.calls[0][1]["candidate_profile_id"] == "p2.read-paged-prepayment-refund.v3-candidate"
    assert wrapper.get_turn("owner", "turn") == "turn"
    with pytest.raises(ValueError):
        wrapper.submit_turn("owner", "session", "request", candidate_profile_id="other")


def test_p2_v3_server_policy_routes_only_narrow_decision_sets() -> None:
    greeting = classify_p2_v3_input("你好", scope_verified=False)
    assert greeting.classification == "non_business"
    assert greeting.allowed_decision_kinds == ("answer",)
    assert greeting.source_free_business_answer_allowed is True

    discovery = classify_p2_v3_input("查询我的活动", scope_verified=False)
    assert discovery.operation == P2ReadOperation.ACTIVITIES
    assert discovery.allowed_read_operations == (P2ReadOperation.ACTIVITIES,)
    assert discovery.allowed_decision_kinds == ("read",)
    assert discovery.pending == ()

    greeted_query = classify_p2_v3_input("你好，请查我的活动", scope_verified=False)
    assert greeted_query.classification == "factual_business"
    assert greeted_query.source_free_business_answer_allowed is False
    assert greeted_query.allowed_read_operations == (P2ReadOperation.ACTIVITIES,)

    missing_scope = classify_p2_v3_input("查询活动里的消费", scope_verified=False)
    assert missing_scope.classification == "factual_business"
    assert missing_scope.allowed_decision_kinds == ("clarify",)
    assert missing_scope.allowed_read_operations == ()
    assert missing_scope.pending[0][0:2] == ("activity_scope", "missing_required_scope")

    scoped = classify_p2_v3_input("查询活动里的消费", scope_verified=True)
    assert scoped.allowed_read_operations == (P2ReadOperation.EXPENSES,)
    assert scoped.source_free_business_answer_allowed is False

    create = classify_p2_v3_input("新增消费", scope_verified=False)
    assert create.classification == "proposal_intent"
    assert create.allowed_decision_kinds == ("propose",)
    assert create.allowed_proposal_operations == (P2ProposalOperation.EXPENSE_CREATE,)
    assert create.allowed_read_operations == ()

    update = classify_p2_v3_input("修改消费", scope_verified=True)
    assert update.allowed_decision_kinds == ("clarify",)
    assert update.pending[0][0] == "proposal_target"
    assert update.allowed_proposal_operations == ()

    ambiguous = classify_p2_v3_input("帮我处理一下", scope_verified=True)
    assert ambiguous.classification == "ambiguous"
    assert ambiguous.allowed_decision_kinds == ("clarify",)
    assert ambiguous.allowed_read_operations == ()
    assert ambiguous.source_free_business_answer_allowed is False


def test_p2_v3_candidate_settings_are_default_off_and_require_the_cohort_gate() -> None:
    settings = Settings(storage_path="D:/tmp/p2-settings.sqlite3")
    assert settings.p2_v3_candidate_enabled is False
    assert settings.p2_v3_native_candidate_enabled is False
    with pytest.raises(ValueError, match="requires the P2 provider"):
        Settings(
            storage_path="D:/tmp/p2-settings.sqlite3",
            p2_v3_candidate_enabled=True,
        )
    with pytest.raises(ValueError, match="requires the v3 candidate gate"):
        Settings(
            storage_path="D:/tmp/p2-settings.sqlite3",
            p2_v3_native_candidate_enabled=True,
        )
