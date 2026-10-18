from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid

from fastapi.testclient import TestClient

from app import contracts as c
from app.p2_harness import P2PromptEnvelope

from test_p2_runtime import (
    ACTIVITY, OWNER, _Backend, _auth, _build_client, _create_session, _events, _submit, _wait,
)


def _sequence_provider(
    provider: Any,
    operations: tuple[c.ReadOperation, ...],
    citation_operations: tuple[c.ReadOperation, ...],
    before_operation: Callable[[P2PromptEnvelope, int], None] | None = None,
) -> None:
    async def generate(prompt: P2PromptEnvelope) -> str:
        provider.prompts.append(prompt)
        results = prompt.context.read_results
        if len(results) < len(operations):
            if before_operation is not None:
                before_operation(prompt, len(results))
            operation = operations[len(results)]
            operation_name = {
                c.ReadOperation.ACTIVITIES: "read.activities",
                c.ReadOperation.EXPENSES: "read.expenses",
                c.ReadOperation.DEBTS: "read.debts",
            }[operation]
            criteria: dict[str, Any] = {"kind": operation.value.removeprefix("read.")}
            if operation != c.ReadOperation.ACTIVITIES:
                criteria["activity_ref"] = prompt.context.verified_scope.activity_ref.value
            return json.dumps({
                "kind": "read", "operation": operation_name, "criteria": criteria,
            })

        citations: list[str] = []
        for operation in citation_operations:
            result = next(item for item in reversed(results) if item.operation == operation)
            citations.append(result.body.items[0].evidence_ref.value)
        return json.dumps({
            "kind": "answer", "basis": "grounded",
            "text": "请按各自证据分别说明，不做合并。", "citations": citations,
        })

    provider.generate = generate


def _message(client: TestClient, turn_id: uuid.UUID) -> dict[str, Any]:
    return next(item for item in _events(client, turn_id)["events"] if item["type"] == "message")


def test_two_distinct_financial_reads_remain_current_and_ground_one_answer(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "multi-expense-debt.sqlite3")
    _sequence_provider(
        provider,
        (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
        (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
    )

    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "查询消费和欠款", scoped=True)
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})

        assert aggregate.checkpoint.model_calls == 3
        assert aggregate.checkpoint.read_calls == 2
        assert backend.read_operations == [c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS]
        assert [len(item.context.read_results) for item in provider.prompts] == [0, 1, 2]
        final_prompt = provider.prompts[-1]
        assert [item.operation for item in final_prompt.provenance] == [
            c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS,
        ]
        assert all(item.current for item in final_prompt.provenance)
        assert len(final_prompt.expense_supplements) == 1
        supplement = final_prompt.expense_supplements[0]
        assert supplement.payments[0].role == "payer"
        assert supplement.payments[0].amount == "12.50"
        assert {item.display_name for item in supplement.splits} == {"Alex", "Rin"}
        assert backend.version_checks

        message = _message(client, turn_id)
        assert set(message["payload"]["citations"]) == {
            item.body.items[0].evidence_ref.value
            for item in aggregate.checkpoint.model_context.read_results
        }
        assert "12.50 USD" in message["payload"]["text"]
        assert "3.00 USD" in message["payload"]["text"]
        assert "付款 Alex" in message["payload"]["text"]
        assert "分摊 Rin" in message["payload"]["text"]


def test_reread_stales_prior_same_operation_without_blocking_latest_supplement(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "multi-reread.sqlite3")
    _sequence_provider(
        provider,
        (c.ReadOperation.EXPENSES, c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
        (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
    )

    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "重新查询消费和欠款", scoped=True)
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})

        assert aggregate.checkpoint.read_calls == 3
        assert aggregate.checkpoint.model_calls == 4
        assert backend.read_operations == [
            c.ReadOperation.EXPENSES, c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS,
        ]
        final_prompt = provider.prompts[-1]
        assert [item.operation for item in final_prompt.provenance] == [
            c.ReadOperation.EXPENSES, c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS,
        ]
        current = {item.result_ref: item.current for item in final_prompt.provenance}
        expenses = [item for item in final_prompt.provenance
                    if item.operation == c.ReadOperation.EXPENSES]
        assert [item.current for item in expenses] == [False, True]
        assert all(item.current for item in final_prompt.provenance
                   if item.operation == c.ReadOperation.DEBTS)
        assert len(final_prompt.expense_supplements) == 1
        assert final_prompt.expense_supplements[0].result_ref == expenses[-1].result_ref
        assert len(current) == 3
        assert "12.50 USD" in _message(client, turn_id)["payload"]["text"]


def test_missing_prior_provenance_is_stale_and_does_not_enter_answer_context(tmp_path: Path) -> None:
    client, components, provider, _backend = _build_client(tmp_path / "multi-missing-metadata.sqlite3")
    runtime = components.runtime

    def drop_previous_provenance(prompt: P2PromptEnvelope, result_count: int) -> None:
        if result_count != 1:
            return
        state = next(iter(runtime._p2_states.values()))
        old_ref = next(iter(state.provenance))
        del state.provenance[old_ref]

    _sequence_provider(
        provider,
        (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
        (c.ReadOperation.DEBTS,),
        before_operation=drop_previous_provenance,
    )

    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "查询欠款", scoped=True)
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})

        assert aggregate.checkpoint.read_calls == 2
        final_prompt = provider.prompts[-1]
        assert [item.operation for item in final_prompt.provenance] == [c.ReadOperation.DEBTS]
        assert final_prompt.expense_supplements == []
        assert "3.00 USD" in _message(client, turn_id)["payload"]["text"]
        assert "12.50 USD" not in _message(client, turn_id)["payload"]["text"]


def test_changed_financial_version_cannot_be_mixed_into_one_answer(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "multi-fv-change.sqlite3")
    _sequence_provider(
        provider,
        (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
        (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS),
    )
    original_read = backend.read

    async def changed_version(*args: Any, **kwargs: Any) -> Any:
        result = await original_read(*args, **kwargs)
        if result.operation == c.ReadOperation.DEBTS:
            return result.model_copy(update={"financial_versions": {ACTIVITY: 2}})
        return result

    backend.read = changed_version

    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "查询消费和欠款", scoped=True)
        aggregate = _wait(components, turn_id, {c.TurnState.FAILED, c.TurnState.COMPLETED})

        assert aggregate.record.turn.state == c.TurnState.FAILED
        assert aggregate.checkpoint.read_calls == 2
        assert len(aggregate.checkpoint.read_results) == 1
        assert aggregate.checkpoint.read_results[0].operation == c.ReadOperation.EXPENSES
        events = _events(client, turn_id)["events"]
        assert not any(item["type"] == "message" for item in events)
        assert len(provider.prompts) == 2


def test_cancel_and_claim_loss_during_late_read_do_not_commit_result_or_message(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "multi-late-read-cancel.sqlite3")
    _sequence_provider(provider, (c.ReadOperation.EXPENSES,), ())
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    original_read = backend.read

    async def blocked_read(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        if not await asyncio.to_thread(release.wait, 5.0):
            raise TimeoutError("test read release deadline expired")
        try:
            return await original_read(*args, **kwargs)
        finally:
            returned.set()

    backend.read = blocked_read

    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "查询消费", scoped=True)
        assert entered.wait(3.0), "backend read did not reach the controlled pause"
        running = components.store.get_turn(OWNER, turn_id)
        assert running.record.turn.state == c.TurnState.RUNNING
        assert running.checkpoint.read_calls == 1
        assert running.claim_token is not None
        assert components.store.release_claim(turn_id, running.claim_token)
        assert components.store.get_turn(OWNER, turn_id).claim_token is None

        response = client.post(
            f"/v1/turns/{turn_id}/cancel",
            headers=_auth(),
            json={
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": running.record.turn.state_revision,
            },
        )
        assert response.status_code == 202, response.text
        release.set()
        cancelled = _wait(components, turn_id, {c.TurnState.CANCELLED})
        assert returned.wait(3.0), "late backend result did not return within the test deadline"
        task_deadline = time.monotonic() + 3.0
        while turn_id in components.runtime._tasks and time.monotonic() < task_deadline:
            time.sleep(0.01)
        assert turn_id not in components.runtime._tasks, "runtime did not finish the late read task"
        final = components.store.get_turn(OWNER, turn_id)
        view = components.store.read_turn_view(OWNER, turn_id)
        assert cancelled.record.turn.state == final.record.turn.state == c.TurnState.CANCELLED
        assert final.checkpoint.read_calls == 1
        assert final.checkpoint.read_results == []
        assert all(event.event.type != c.EventType.MESSAGE for event in view.events)
        assert len(provider.prompts) == 1
