from __future__ import annotations

"""Harness guard: a clarification may not ask for an already verified activity.

The trained model can identify the bound activity and still emit
``clarify(activity_ref)``. The Harness now rejects that output, which routes it
into the existing one-shot repair path (the runtime catches ``ModelOutputError``
and re-asks once). These tests pin both the rejection and the repair call.
"""

import asyncio
import json
import uuid
from pathlib import Path

from agent.app import contracts as c
from agent.app.harness import MockModelProvider, ModelOutputError, ModelPrompt, parse_model_output
from agent.app.store import SQLiteAgentStore
from test_mock_runtime import OWNER, _runtime, _wait_state
from test_sqlite_persistence import _session, _submit


def _context(*, activity_scope: bool) -> c.ModelContext:
    if activity_scope:
        scope: c.ModelVerifiedScope = c.ModelActivityScope(
            kind="activity", activity_ref=c.ActivityRef.A01, permissions=[],
        )
        refs: list[c.ModelReference] = [
            c.ModelActivityReference(kind="activity", ref=c.ActivityRef.A01),
        ]
    else:
        scope = c.ModelNoActivityScope(kind="none", permissions=[])
        refs = []
    return c.ModelContext(
        context_version=1,
        input_text="how much did this activity cost",
        verified_scope=scope,
        recent_messages=[],
        pending_slots=[],
        bound_references=refs,
        read_results=[],
        policy_evidence=[],
        available_permissions=[],
    )


def _clarify(*slots: str) -> str:
    return json.dumps(
        {"kind": "clarify", "prompt": "请补充信息", "missing_slots": list(slots)},
        ensure_ascii=False, separators=(",", ":"),
    )


def test_clarify_for_verified_activity_is_rejected() -> None:
    raw = _clarify("activity_ref")
    try:
        parse_model_output(raw, _context(activity_scope=True))
    except ModelOutputError:
        pass
    else:  # pragma: no cover - the guard must fail closed
        raise AssertionError("a verified activity must not be re-requested as missing")


def test_clarify_for_missing_activity_is_still_allowed() -> None:
    decision = parse_model_output(_clarify("activity_ref"), _context(activity_scope=False))
    assert isinstance(decision, c.ClarifyDecision)
    assert decision.missing_slots == [c.ClarificationSlot.ACTIVITY]


def test_clarify_for_other_slots_is_unaffected() -> None:
    decision = parse_model_output(
        _clarify("original_amount", "original_currency"), _context(activity_scope=True),
    )
    assert isinstance(decision, c.ClarifyDecision)


class _ClarifyThenRepairProvider(MockModelProvider):
    """First call contradicts the verified scope; the repair asks for real slots."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[ModelPrompt] = []

    async def generate(self, prompt: ModelPrompt) -> str:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return _clarify("activity_ref")
        return _clarify("original_amount", "original_currency")


def test_runtime_repairs_once_instead_of_persisting_the_contradiction(
    tmp_path: Path,
) -> None:
    store = SQLiteAgentStore(tmp_path / "clarify-guard.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER, text="查询消费")
        provider = _ClarifyThenRepairProvider()
        runtime, _ = _runtime(store, provider)

        async def run() -> c.TurnAggregate:
            await runtime.start()
            try:
                return await _wait_state(store, turn_id, {c.TurnState.WAIT_INPUT})
            finally:
                await runtime.close()

        aggregate = asyncio.run(run())

        checkpoint = aggregate.checkpoint
        assert len(provider.prompts) == 2
        assert checkpoint.model_calls == 2
        assert checkpoint.repair_calls == 1
        assert provider.prompts[0].repair_feedback is None
        assert provider.prompts[1].repair_feedback is not None
        assert checkpoint.last_clarification is not None
        assert checkpoint.last_clarification.missing_slots == [
            c.ClarificationSlot.AMOUNT, c.ClarificationSlot.CURRENCY,
        ]
    finally:
        store.close()
