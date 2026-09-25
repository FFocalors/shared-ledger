"""Execute a Scenario v1 through the current authenticated client RPCs."""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from . import (
    ArchiveActivity,
    CreateExpense,
    CreatePrepayment,
    CreateSubActivity,
    FifoRepayment,
    FinalSettlement,
    LinkedRefund,
    PreviewFinalSettlement,
    ReturnPrepayment,
    Scenario,
    ScenarioValidationError,
    TargetedRepayment,
    UnarchiveActivity,
    VoidTransfer,
    load_scenario,
)
from .collector import collect_state
from .result import write_run_artifacts
from .supabase import (
    SupabaseApiError,
    SupabaseConfigurationError,
    SupabaseRestClient,
    verification_root,
)


BUSINESS_LOGIC_DOCUMENT = "docs/backend/BUSINESS_LOGIC.md"


def _business_logic_commit() -> str | None:
    repository_root = verification_root().parent
    try:
        completed = subprocess.run(
            ["git", "log", "-n1", "--format=%H", "--", BUSINESS_LOGIC_DOCUMENT, "supabase/migrations"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = completed.stdout.strip()
    return commit or None


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _record(row_or_rows: Any, operation: str) -> dict[str, Any]:
    if isinstance(row_or_rows, dict):
        return row_or_rows
    if isinstance(row_or_rows, list) and len(row_or_rows) == 1 and isinstance(row_or_rows[0], dict):
        return row_or_rows[0]
    raise RuntimeError(f"{operation} returned an unexpected result shape")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _version(client: SupabaseRestClient, activity_id: str) -> int:
    rows = client.select(
        "activities",
        filters={"id": f"eq.{activity_id}"},
        columns="financial_version",
    )
    if not rows or rows[0].get("financial_version") is None:
        raise RuntimeError("Activity did not expose its latest financial_version")
    raw = rows[0]["financial_version"]
    if isinstance(raw, Decimal):
        if raw != raw.to_integral_value():
            raise RuntimeError("Activity financial_version was not an integer")
        return int(raw)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Activity financial_version was not an integer") from exc


def _occurred_at(started_at: datetime, step: int) -> str:
    return (started_at + timedelta(seconds=step)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _retry_idempotent_rpc(client: SupabaseRestClient, rpc: str, payload: Mapping[str, Any]) -> tuple[Any, bool]:
    """Retry a lost response once with exactly the original v2 payload/request_id."""

    try:
        return client.rpc(rpc, payload), False
    except SupabaseApiError as exc:
        if exc.code != "NETWORK_ERROR":
            raise
        return client.rpc(rpc, payload), True


def _expense_payload(
    operation: CreateExpense | LinkedRefund,
    *,
    ledger_unit_id: str,
    participant_ids: Mapping[str, str],
    occurred_at: str,
    original_expense_id: str | None,
) -> dict[str, Any]:
    payments = [
        {"participant_id": participant_ids[ref], "amount": _decimal_text(amount)}
        for ref, amount in operation.payments.items()
    ]
    manual_splits = (
        [
            {"participant_id": participant_ids[ref], "amount": _decimal_text(amount)}
            for ref, amount in operation.splits.items()
        ]
        if operation.splits is not None
        else []
    )
    return {
        "ledger_unit_id": ledger_unit_id,
        "title": operation.title,
        "original_amount": _decimal_text(operation.amount),
        "original_currency": operation.currency,
        "split_method": operation.split_method,
        "payments": payments,
        "manual_splits": manual_splits,
        "aa_participant_ids": [participant_ids[ref] for ref in operation.aa_participants],
        "occurred_at": occurred_at,
        "note": None,
        "original_expense_id": original_expense_id,
        "icon_key": "money",
    }


def _summary(operation: Any) -> dict[str, Any]:
    if isinstance(operation, (CreateExpense, LinkedRefund)):
        value: dict[str, Any] = {
            "ref": operation.ref,
            "amount": _decimal_text(operation.amount),
            "currency": operation.currency,
            "payments": {ref: _decimal_text(amount) for ref, amount in operation.payments.items()},
            "split_method": operation.split_method,
        }
        if operation.splits is not None:
            value["splits"] = {ref: _decimal_text(amount) for ref, amount in operation.splits.items()}
        else:
            value["aa_participants"] = list(operation.aa_participants)
        if isinstance(operation, LinkedRefund):
            value["original_expense_ref"] = operation.original_expense_ref
        return value
    if isinstance(operation, (TargetedRepayment, FifoRepayment)):
        value = {
            "ref": operation.ref,
            "from_participant": operation.from_participant,
            "to_participant": operation.to_participant,
            "amount": _decimal_text(operation.amount),
            "currency": operation.currency,
            "mode": "TARGETED" if isinstance(operation, TargetedRepayment) else "FIFO",
        }
        if isinstance(operation, TargetedRepayment):
            value["target_expense_refs"] = list(operation.target_expense_refs)
        return value
    if isinstance(operation, (CreatePrepayment, ReturnPrepayment)):
        return {
            "ref": operation.ref,
            "owner_participant": operation.owner_participant,
            "custodian_participant": operation.custodian_participant,
            "amount": _decimal_text(operation.amount),
            "currency": operation.currency,
        }
    if isinstance(operation, VoidTransfer):
        return {"transfer_ref": operation.transfer_ref, "reason": operation.reason}
    if isinstance(operation, CreateSubActivity):
        return {"ref": operation.ref, "name": operation.name}
    if isinstance(operation, FinalSettlement):
        return {
            "ref": operation.ref,
            "from_participant": operation.from_participant,
            "to_participant": operation.to_participant,
            "mode": operation.mode,
        }
    if isinstance(operation, PreviewFinalSettlement):
        return {"ref": operation.ref, "mode": operation.mode}
    if isinstance(operation, (ArchiveActivity, UnarchiveActivity)):
        return {"ref": operation.ref}
    return {}


def _error_details(error: BaseException) -> tuple[str, str]:
    if isinstance(error, SupabaseApiError):
        return error.code or f"HTTP_{error.status_code}", error.message
    if isinstance(error, SupabaseConfigurationError):
        return "CONFIGURATION_ERROR", str(error)
    if isinstance(error, ScenarioValidationError):
        return "SCENARIO_FORMAT", str(error)
    return type(error).__name__.upper(), str(error)[:500]


def _notify(callback: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if callback is not None:
        callback(event)


def _initial_state() -> dict[str, Any]:
    return {
        "activity": None,
        "participants": [],
        "expenses": [],
        "expense_debts": [],
        "bilateral_debts": [],
        "transfers": [],
        "transfer_components": [],
        "transfer_allocations": [],
        "transfer_expense_allocations": [],
        "prepayment_accounts": [],
        "prepayment_usages": [],
        "final_settlement_paths": [],
    }


def run_scenario(
    scenario_path: str | Path,
    *,
    runs_dir: str | Path | None = None,
    env_path: str | Path | None = None,
    client: SupabaseRestClient | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one scenario and always write scenario/result/trace/final-state files."""

    source = Path(scenario_path)
    output_root = Path(runs_dir) if runs_dir else verification_root() / "runs"
    run_id = _run_id()
    run_dir = output_root / run_id
    started_at = datetime.now(timezone.utc)
    business_commit = _business_logic_commit()
    try:
        scenario_bytes = source.read_bytes()
    except OSError:
        scenario_bytes = None

    scenario: Scenario | None = None
    api = client
    operations: list[dict[str, Any]] = []
    state_final = _initial_state()
    failed_step: int | None = None
    failed_operation: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    status = "EXECUTED"
    activity_id: str | None = None
    participant_ids: dict[str, str] = {}
    expense_ids: dict[str, str] = {}
    transfer_ids: dict[str, str] = {}
    ledger_unit_id: str | None = None
    ledger_unit_ids: dict[str, str] = {}
    request_ids: dict[str, str] = {}
    setup_complete = False

    try:
        scenario = load_scenario(source)
        _notify(progress, {"kind": "scenario", "scenario_id": scenario.scenario_id, "status": "loaded"})
        if api is None:
            api = SupabaseRestClient.from_env(env_path)
        api.create_test_user()

        setup_step = 1
        try:
            activity_record = _record(
                api.rpc(
                    "create_activity",
                    {
                        "name": f"Verifier {scenario.scenario_id}",
                        "type": scenario.activity.type,
                        "base_currency": scenario.activity.base_currency,
                        "multi_currency_enabled": scenario.activity.multi_currency_enabled,
                    },
                ),
                "create_activity",
            )
            activity_id = str(activity_record.get("activity_id") or "")
            if not activity_id:
                raise RuntimeError("create_activity response omitted activity_id")
            operations.append(
                {
                    "step": 0,
                    "phase": "setup",
                    "operation": "create_activity",
                    "status": "success",
                    "rpc": "create_activity",
                    "input": {
                        "type": scenario.activity.type,
                        "base_currency": scenario.activity.base_currency,
                        "multi_currency_enabled": scenario.activity.multi_currency_enabled,
                    },
                }
            )

            units = api.select(
                "ledger_units",
                filters={"activity_id": f"eq.{activity_id}"},
                columns="id,type,is_deleted",
            )
            root = next(
                (
                    row
                    for row in units
                    if str(row.get("type", "")).lower()
                    == ("default" if scenario.activity.type == "normal" else "root")
                    and not row.get("is_deleted", False)
                ),
                None,
            )
            if not root or not root.get("id"):
                raise RuntimeError("create_activity did not initialize a root LedgerUnit")
            ledger_unit_id = str(root["id"])

            for participant_ref in scenario.participants:
                created = _record(
                    api.rpc(
                        "create_participant",
                        {"activity_id": activity_id, "name": participant_ref},
                    ),
                    "create_participant",
                )
                participant_id = str(created.get("participant_id") or "")
                if not participant_id:
                    raise RuntimeError("create_participant response omitted participant_id")
                participant_ids[participant_ref] = participant_id
                setup_step += 1
                operations.append(
                    {
                        "step": 0,
                        "setup_step": setup_step,
                        "phase": "setup",
                        "operation": "create_participant",
                        "status": "success",
                        "rpc": "create_participant",
                    "participant_ref": participant_ref,
                }
            )
            setup_complete = True
        except Exception as exc:
            failed_step = 0
            failed_operation = "initialize_activity"
            error_code, error_message = _error_details(exc)
            operations.append(
                {
                    "step": 0,
                    "phase": "setup",
                    "operation": "initialize_activity",
                    "status": "failed",
                    "error_code": _error_details(exc)[0],
                    "error_message": _error_details(exc)[1],
                }
            )
            raise

        assert activity_id is not None and ledger_unit_id is not None
        for step, operation in enumerate(scenario.operations, start=1):
            operation_name = operation.type
            rpc_name = ""
            trace: dict[str, Any] = {
                "step": step,
                "operation": operation_name,
                "status": "success",
                "rpc": "",
                "input": _summary(operation),
            }
            try:
                if isinstance(operation, (CreateExpense, LinkedRefund)):
                    rpc_name = "create_expense_auto_rate"
                    original_id = (
                        expense_ids[operation.original_expense_ref]
                        if isinstance(operation, LinkedRefund)
                        else None
                    )
                    response = api.rpc(
                        rpc_name,
                        _expense_payload(
                            operation,
                            ledger_unit_id=(
                                ledger_unit_ids.get(operation.ledger_unit_ref, ledger_unit_id)
                                if operation.ledger_unit_ref
                                else ledger_unit_id
                            ),
                            participant_ids=participant_ids,
                            occurred_at=_occurred_at(started_at, step),
                            original_expense_id=original_id,
                        ),
                    )
                    record = _record(response, rpc_name)
                    identifier = str(record.get("expense_id") or "")
                    if not identifier:
                        raise RuntimeError("create_expense_auto_rate response omitted expense_id")
                    expense_ids[operation.ref] = identifier
                    trace["result"] = {
                        "base_amount": str(record["base_amount"]) if record.get("base_amount") is not None else None,
                        "financial_version": record.get("version"),
                    }
                elif isinstance(operation, (TargetedRepayment, FifoRepayment)):
                    rpc_name = "create_expense_repayment_v2"
                    version = _version(api, activity_id)
                    request_id = request_ids.setdefault(operation.ref, str(uuid.uuid4()))
                    target_ids = (
                        sorted({expense_ids[ref] for ref in operation.target_expense_refs})
                        if isinstance(operation, TargetedRepayment)
                        else []
                    )
                    payload = {
                        "activity_id": activity_id,
                        "from_participant_id": participant_ids[operation.from_participant],
                        "to_participant_id": participant_ids[operation.to_participant],
                        "amount": _decimal_text(operation.amount),
                        "currency": operation.currency,
                        "mode": "TARGETED" if isinstance(operation, TargetedRepayment) else "FIFO",
                        "target_expense_ids": target_ids,
                        "occurred_at": _occurred_at(started_at, step),
                        "on_behalf_of_participant_id": participant_ids[operation.from_participant],
                        "expected_financial_version": version,
                        "request_id": request_id,
                    }
                    response, replayed = _retry_idempotent_rpc(api, rpc_name, payload)
                    record = _record(response, rpc_name)
                    identifier = str(record.get("transfer_id") or "")
                    if not identifier:
                        raise RuntimeError(f"{rpc_name} response omitted transfer_id")
                    transfer_ids[operation.ref] = identifier
                    trace["financial_version"] = version
                    trace["result"] = {
                        "amount": str(record["amount"]) if record.get("amount") is not None else _decimal_text(operation.amount),
                        "currency": record.get("currency", operation.currency),
                        "financial_version": record.get("financial_version"),
                    }
                    if replayed:
                        trace["replayed_after_network_error"] = True
                elif isinstance(operation, (CreatePrepayment, ReturnPrepayment)):
                    rpc_name = (
                        "create_prepayment_v2"
                        if isinstance(operation, CreatePrepayment)
                        else "create_prepayment_return_v2"
                    )
                    version = _version(api, activity_id)
                    request_id = request_ids.setdefault(operation.ref, str(uuid.uuid4()))
                    payload = {
                        "activity_id": activity_id,
                        "owner_participant_id": participant_ids[operation.owner_participant],
                        "custodian_participant_id": participant_ids[operation.custodian_participant],
                        "amount": _decimal_text(operation.amount),
                        "currency": operation.currency,
                        "occurred_at": _occurred_at(started_at, step),
                        # Section 4: creating a prepayment needs no behalf, but a
                        # Return follows the ordinary claim/Creator-behalf rule and
                        # moves money Custodian -> Owner, so the payer (the
                        # custodian) is the party the caller acts for.
                        "on_behalf_of_participant_id": (
                            None
                            if isinstance(operation, CreatePrepayment)
                            else participant_ids[operation.custodian_participant]
                        ),
                        "expected_financial_version": version,
                        "request_id": request_id,
                    }
                    response, replayed = _retry_idempotent_rpc(api, rpc_name, payload)
                    record = _record(response, rpc_name)
                    identifier = str(record.get("transfer_id") or "")
                    if not identifier:
                        raise RuntimeError(f"{rpc_name} response omitted transfer_id")
                    transfer_ids[operation.ref] = identifier
                    trace["financial_version"] = version
                    trace["result"] = {
                        "amount": _decimal_text(operation.amount),
                        "financial_version": record.get("financial_version"),
                        "new_prepayment_balance": str(record.get("new_prepayment_balance"))
                        if record.get("new_prepayment_balance") is not None
                        else str(record.get("new_balance"))
                        if record.get("new_balance") is not None
                        else None,
                    }
                    if replayed:
                        trace["replayed_after_network_error"] = True
                elif isinstance(operation, VoidTransfer):
                    transfer_id = transfer_ids[operation.transfer_ref]
                    transfer_rows = api.select(
                        "transfers",
                        filters={"activity_id": f"eq.{activity_id}", "id": f"eq.{transfer_id}"},
                        columns="type",
                    )
                    if not transfer_rows:
                        raise RuntimeError("Transfer ref was not visible for void")
                    transfer_type = str(transfer_rows[0].get("type", ""))
                    rpc_name = (
                        "void_settlement_transfer"
                        if transfer_type in {"settlement", "final_settlement"}
                        else "void_prepayment_transfer"
                    )
                    response = _record(
                        api.rpc(rpc_name, {"transfer_id": transfer_id, "void_reason": operation.reason.strip()}),
                        rpc_name,
                    )
                    trace["result"] = {"voided": bool(response.get("voided", True))}
                elif isinstance(operation, CreateSubActivity):
                    rpc_name = "create_sub_activity"
                    record = _record(
                        api.rpc(
                            rpc_name,
                            {"activity_id": activity_id, "name": operation.name},
                        ),
                        rpc_name,
                    )
                    unit_id = str(record.get("ledger_unit_id") or "")
                    if not unit_id:
                        raise RuntimeError("create_sub_activity response omitted ledger_unit_id")
                    ledger_unit_ids[operation.ref] = unit_id
                    trace["result"] = {
                        "name": record.get("created_name"),
                        "ledger_unit_type": record.get("created_type"),
                    }
                elif isinstance(operation, PreviewFinalSettlement):
                    # Read-only: record the plan the server would offer right now.
                    rpc_name = "preview_final_settlement_v2"
                    rows = api.rpc(rpc_name, {"p_activity_id": activity_id, "p_mode": operation.mode})
                    rows = rows if isinstance(rows, list) else ([rows] if rows else [])
                    ref_by_id = {value: key for key, value in participant_ids.items()}
                    trace["result"] = {
                        "mode": operation.mode,
                        "plan": [
                            {
                                "from": ref_by_id.get(str(row.get("from_participant_id")), "unknown"),
                                "to": ref_by_id.get(str(row.get("to_participant_id")), "unknown"),
                                "amount": _decimal_text(Decimal(str(row["amount"])))
                                if row.get("amount") is not None else None,
                                "currency": row.get("currency"),
                                "is_prepayment_return": bool(row.get("is_prepayment_return")),
                            }
                            for row in rows
                        ],
                    }
                elif isinstance(operation, FinalSettlement):
                    # Section 14: execute one complete suggestion item as-is.
                    rpc_name = "execute_final_settlement_v2"
                    rows = api.rpc(
                        "preview_final_settlement_v2",
                        {"p_activity_id": activity_id, "p_mode": operation.mode},
                    )
                    rows = rows if isinstance(rows, list) else ([rows] if rows else [])
                    if operation.from_participant is None:
                        # Section 14: execute one complete suggestion item; with no
                        # parties named, take the first item of the current plan.
                        match = rows[0] if rows else None
                    else:
                        wanted_from = participant_ids[operation.from_participant]
                        wanted_to = participant_ids[operation.to_participant]
                        match = next(
                            (
                                row for row in rows
                                if str(row.get("from_participant_id")) == wanted_from
                                and str(row.get("to_participant_id")) == wanted_to
                            ),
                            None,
                        )
                    if match is None:
                        raise RuntimeError(
                            "the current final plan offers no item to execute"
                        )
                    wanted_from = str(match.get("from_participant_id"))
                    wanted_to = str(match.get("to_participant_id"))
                    version = _version(api, activity_id)
                    request_id = request_ids.setdefault(operation.ref, str(uuid.uuid4()))
                    payload = {
                        "activity_id": activity_id,
                        "from_participant_id": wanted_from,
                        "to_participant_id": wanted_to,
                        "amount": _decimal_text(Decimal(str(match["amount"]))),
                        "currency": str(match["currency"]),
                        "mode": operation.mode,
                        "expected_financial_version": version,
                        "request_id": request_id,
                        "occurred_at": _occurred_at(started_at, step),
                        # Section 4: any member may submit the current suggestion.
                        "on_behalf_of_participant_id": None,
                    }
                    response, replayed = _retry_idempotent_rpc(api, rpc_name, payload)
                    record = _record(response, rpc_name)
                    identifier = str(record.get("transfer_id") or "")
                    if not identifier:
                        raise RuntimeError("execute_final_settlement_v2 response omitted transfer_id")
                    transfer_ids[operation.ref] = identifier
                    trace["financial_version"] = version
                    trace["result"] = {
                        "amount": _decimal_text(Decimal(str(record["amount"])))
                        if record.get("amount") is not None else None,
                        "currency": record.get("currency"),
                        "mode": record.get("mode"),
                        "financial_version": record.get("financial_version"),
                    }
                    if replayed:
                        trace["replayed_after_network_error"] = True
                elif isinstance(operation, (ArchiveActivity, UnarchiveActivity)):
                    rpc_name = (
                        "archive_activity"
                        if isinstance(operation, ArchiveActivity) else "unarchive_activity"
                    )
                    record = _record(api.rpc(rpc_name, {"p_activity_id": activity_id}), rpc_name)
                    trace["result"] = {
                        "archived": bool(record.get("archived")),
                        "changed": bool(record.get("changed")),
                        "completed": bool(record.get("completed")),
                        "warning": record.get("warning"),
                    }
                else:
                    raise RuntimeError(f"Unsupported operation type: {operation_name}")
            except Exception as exc:
                error_code, error_message = _error_details(exc)
                trace["status"] = "failed"
                trace["error_code"] = error_code
                trace["error_message"] = error_message
                trace["rpc"] = rpc_name or None
                operations.append(trace)
                status = "FAILED"
                failed_step = step
                failed_operation = operation_name
                _notify(
                    progress,
                    {
                        "kind": "operation",
                        "scenario_id": scenario.scenario_id,
                        "step": step,
                        "count": len(scenario.operations),
                        "operation": operation_name,
                        "status": "failed",
                    },
                )
                break
            trace["rpc"] = rpc_name
            operations.append(trace)
            _notify(
                progress,
                {
                    "kind": "operation",
                    "scenario_id": scenario.scenario_id,
                    "step": step,
                    "count": len(scenario.operations),
                    "operation": operation_name,
                    "status": "success",
                },
            )
    except Exception as exc:
        if status == "EXECUTED":
            status = "FAILED"
        if error_code is None:
            error_code, error_message = _error_details(exc)
        if failed_step is None and (scenario is None or not setup_complete):
            failed_step = 0

    if activity_id is not None and api is not None:
        try:
            state_final = collect_state(
                api,
                activity_id,
                participant_ids=participant_ids,
                expense_ids=expense_ids,
                transfer_ids=transfer_ids,
            )
        except Exception as exc:
            if status == "EXECUTED":
                status = "FAILED"
                error_code, error_message = _error_details(exc)
            else:
                state_final["collection_error"] = _error_details(exc)[1]
    completed_at = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "run_id": run_id,
        "scenario_id": scenario.scenario_id if scenario else None,
        "status": status,
        "business_logic_commit": business_commit,
        "business_logic_document": BUSINESS_LOGIC_DOCUMENT,
        "operation_count": len(scenario.operations) if scenario else 0,
        "failed_step": failed_step,
        "failed_operation": failed_operation,
        "started_at": started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if error_code is not None:
        result["error_code"] = error_code
        result["error_message"] = error_message
    write_run_artifacts(
        run_dir,
        scenario_bytes=scenario_bytes,
        result=result,
        operations=operations,
        state_final=state_final,
    )
    if api is not None:
        close = getattr(api, "close", None)
        if callable(close):
            close()
    summary = {
        "run_id": run_id,
        "scenario_id": scenario.scenario_id if scenario else source.stem,
        "status": status,
        "operation_count": len(scenario.operations) if scenario else 0,
        "failed_step": failed_step,
        "failed_operation": failed_operation,
        "error_code": error_code,
        "error_message": error_message,
        "run_dir": str(run_dir),
    }
    _notify(progress, {"kind": "scenario", **summary})
    return summary
