"""Read the small set of business projections needed for a run."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .supabase import SupabaseRestClient


def _decimal(value: Any) -> str | None:
    if value is None:
        return None
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return format(amount, "f")


def _pick(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _in_filter(values: list[str]) -> str:
    return "in.(" + ",".join(values) + ")"


def collect_state(
    client: SupabaseRestClient,
    activity_id: str,
    *,
    participant_ids: Mapping[str, str],
    expense_ids: Mapping[str, str],
    transfer_ids: Mapping[str, str],
) -> dict[str, Any]:
    """Collect activity facts/projections and replace database UUIDs with scenario refs."""

    participant_refs = {identifier: ref for ref, identifier in participant_ids.items()}
    expense_refs = {identifier: ref for ref, identifier in expense_ids.items()}
    transfer_refs = {identifier: ref for ref, identifier in transfer_ids.items()}
    participant_ref = lambda identifier: participant_refs.get(identifier, "unknown_participant")
    expense_ref = lambda identifier: expense_refs.get(identifier, "unknown_expense")
    transfer_ref = lambda identifier: transfer_refs.get(identifier, "unknown_transfer")

    activity_rows = client.select(
        "activities",
        filters={"id": f"eq.{activity_id}"},
        columns="id,type,base_currency,multi_currency_enabled,financial_version,archived_at",
    )
    if not activity_rows:
        raise RuntimeError("Activity state was not visible to its authenticated creator")
    activity = activity_rows[0]

    ledger_units = client.select(
        "ledger_units",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="id,type,name,is_deleted",
    )
    unit_ids = [str(row["id"]) for row in ledger_units if row.get("id")]
    unit_type_by_id = {str(row["id"]): row.get("type") for row in ledger_units if row.get("id")}
    participant_rows = client.select(
        "participants",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="id,name,participant_order,is_deleted",
    )
    participant_name_by_id = {str(row["id"]): str(row.get("name", "")) for row in participant_rows}

    expense_rows: list[dict[str, Any]] = []
    if unit_ids:
        expense_rows = client.select(
            "expenses",
            filters={"ledger_unit_id": _in_filter(unit_ids)},
            columns=(
                "id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,"
                "split_method,original_expense_id,is_deleted,financial_locked"
            ),
        )
    expense_db_ids = [str(row["id"]) for row in expense_rows if row.get("id")]
    payment_rows = (
        client.select(
            "payments",
            filters={"expense_id": _in_filter(expense_db_ids)},
            columns="expense_id,participant_id,amount,base_amount",
        )
        if expense_db_ids
        else []
    )
    split_rows = (
        client.select(
            "splits",
            filters={"expense_id": _in_filter(expense_db_ids)},
            columns="expense_id,participant_id,amount,base_amount",
        )
        if expense_db_ids
        else []
    )
    payments_by_expense: dict[str, list[dict[str, Any]]] = {}
    for row in payment_rows:
        payments_by_expense.setdefault(str(row.get("expense_id")), []).append(
            {
                "participant": participant_ref(str(row.get("participant_id", ""))),
                "amount": _decimal(row.get("amount")),
                "base_amount": _decimal(row.get("base_amount")),
            }
        )
    splits_by_expense: dict[str, list[dict[str, Any]]] = {}
    for row in split_rows:
        splits_by_expense.setdefault(str(row.get("expense_id")), []).append(
            {
                "participant": participant_ref(str(row.get("participant_id", ""))),
                "amount": _decimal(row.get("amount")),
                "base_amount": _decimal(row.get("base_amount")),
            }
        )

    normalized_expenses = []
    for row in expense_rows:
        identifier = str(row.get("id", ""))
        original_id = row.get("original_expense_id")
        normalized_expenses.append(
            {
                "ref": expense_ref(identifier),
                "ledger_unit_type": unit_type_by_id.get(str(row.get("ledger_unit_id", ""))),
                "title": row.get("title"),
                "amount": _decimal(row.get("original_amount")),
                "currency": row.get("original_currency"),
                "base_amount": _decimal(row.get("base_amount")),
                "fx_rate": _decimal(row.get("fx_rate")),
                "split_method": row.get("split_method"),
                "original_expense_ref": expense_ref(str(original_id)) if original_id else None,
                "is_deleted": bool(row.get("is_deleted", False)),
                "financial_locked": bool(row.get("financial_locked", False)),
                "payments": sorted(
                    payments_by_expense.get(identifier, []), key=lambda item: item["participant"] or ""
                ),
                "splits": sorted(
                    splits_by_expense.get(identifier, []), key=lambda item: item["participant"] or ""
                ),
            }
        )
    normalized_expenses.sort(key=lambda row: row["ref"] or "")

    expense_debts = client.select(
        "expense_debts",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="*",
    )
    normalized_expense_debts = [
        {
            "expense_ref": expense_ref(str(row.get("expense_id", ""))),
            "debtor": participant_ref(str(row.get("debtor_participant_id", ""))),
            "creditor": participant_ref(str(row.get("creditor_participant_id", ""))),
            "amount": _decimal(_pick(row, "original_amount", "amount")),
            "currency": row.get("original_currency"),
            "base_amount": _decimal(row.get("amount")),
        }
        for row in expense_debts
    ]
    normalized_expense_debts.sort(key=lambda row: (row["expense_ref"] or "", row["debtor"], row["creditor"]))

    bilateral_debts = client.select(
        "bilateral_debts",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="*",
    )
    normalized_bilateral_debts = [
        {
            "debtor": participant_ref(str(row.get("debtor_participant_id", ""))),
            "creditor": participant_ref(str(row.get("creditor_participant_id", ""))),
            "amount": _decimal(_pick(row, "original_amount", "amount")),
            "currency": row.get("currency"),
            "base_amount": _decimal(_pick(row, "base_amount", "amount")),
        }
        for row in bilateral_debts
    ]
    normalized_bilateral_debts.sort(key=lambda row: (row["debtor"], row["creditor"], row["currency"] or ""))

    transfers = client.select(
        "transfers",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="id,from_participant_id,to_participant_id,type,amount,currency,is_voided",
    )
    normalized_transfers = [
        {
            "ref": transfer_ref(str(row.get("id", ""))),
            "from": participant_ref(str(row.get("from_participant_id", ""))),
            "to": participant_ref(str(row.get("to_participant_id", ""))),
            "type": row.get("type"),
            "amount": _decimal(row.get("amount")),
            "currency": row.get("currency"),
            "is_voided": bool(row.get("is_voided", False)),
        }
        for row in transfers
    ]
    normalized_transfers.sort(key=lambda row: row["ref"] or "")

    components = client.select(
        "transfer_components",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="transfer_id,component_type,amount",
    )
    normalized_components = [
        {
            "transfer_ref": transfer_ref(str(row.get("transfer_id", ""))),
            "type": row.get("component_type"),
            "amount": _decimal(row.get("amount")),
        }
        for row in components
    ]
    normalized_components.sort(key=lambda row: (row["transfer_ref"] or "", row["type"] or ""))

    transfer_allocations = client.select(
        "transfer_allocations",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="transfer_id,expense_debt_id,amount,original_amount,base_amount",
    )
    debt_by_id = {str(row.get("id")): row for row in expense_debts if row.get("id")}
    normalized_transfer_allocations = []
    for row in transfer_allocations:
        debt = debt_by_id.get(str(row.get("expense_debt_id", "")), {})
        normalized_transfer_allocations.append(
            {
                "transfer_ref": transfer_ref(str(row.get("transfer_id", ""))),
                "expense_ref": expense_ref(str(debt.get("expense_id", ""))),
                "debtor": participant_ref(str(debt.get("debtor_participant_id", ""))),
                "creditor": participant_ref(str(debt.get("creditor_participant_id", ""))),
                "amount": _decimal(row.get("amount")),
                "original_amount": _decimal(row.get("original_amount")),
                "base_amount": _decimal(row.get("base_amount")),
            }
        )
    normalized_transfer_allocations.sort(
        key=lambda row: (row["transfer_ref"] or "", row["expense_ref"] or "", row["debtor"], row["creditor"])
    )

    durable_allocations = client.select(
        "transfer_expense_allocations",
        filters={"activity_id": f"eq.{activity_id}"},
        columns=(
            "transfer_id,expense_id,debtor_participant_id,creditor_participant_id,allocation_mode,"
            "payment_currency,payment_amount,original_currency,original_amount,base_amount"
        ),
    )
    normalized_durable_allocations = [
        {
            "transfer_ref": transfer_ref(str(row.get("transfer_id", ""))),
            "expense_ref": expense_ref(str(row.get("expense_id", ""))),
            "debtor": participant_ref(str(row.get("debtor_participant_id", ""))),
            "creditor": participant_ref(str(row.get("creditor_participant_id", ""))),
            "mode": row.get("allocation_mode"),
            "payment_currency": row.get("payment_currency"),
            "payment_amount": _decimal(row.get("payment_amount")),
            "original_currency": row.get("original_currency"),
            "original_amount": _decimal(row.get("original_amount")),
            "base_amount": _decimal(row.get("base_amount")),
        }
        for row in durable_allocations
    ]
    normalized_durable_allocations.sort(
        key=lambda row: (row["transfer_ref"] or "", row["expense_ref"] or "", row["mode"] or "")
    )

    accounts = client.select(
        "prepayment_accounts",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="*",
    )
    account_refs = {str(row["id"]): row for row in accounts if row.get("id")}
    normalized_accounts = [
        {
            "owner": participant_ref(str(row.get("owner_participant_id", ""))),
            "custodian": participant_ref(str(row.get("custodian_participant_id", ""))),
            "currency": _pick(row, "currency_code", "currency") or activity.get("base_currency"),
            "balance": _decimal(row.get("balance")),
            "base_balance": _decimal(row.get("base_balance")),
        }
        for row in accounts
    ]
    normalized_accounts.sort(key=lambda row: (row["owner"], row["custodian"], row["currency"] or ""))

    usages = client.select(
        "prepayment_usages",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="account_id,expense_debt_id,amount,gross_amount",
    )
    normalized_usages = []
    for row in usages:
        account = account_refs.get(str(row.get("account_id", "")), {})
        debt = debt_by_id.get(str(row.get("expense_debt_id", "")), {})
        normalized_usages.append(
            {
                "expense_ref": expense_ref(str(debt.get("expense_id", ""))),
                "owner": participant_ref(str(account.get("owner_participant_id", ""))),
                "custodian": participant_ref(str(account.get("custodian_participant_id", ""))),
                "amount": _decimal(row.get("amount")),
                "gross_amount": _decimal(row.get("gross_amount")),
                "currency": _pick(account, "currency_code", "currency") or activity.get("base_currency"),
            }
        )
    normalized_usages.sort(key=lambda row: (row["expense_ref"] or "", row["owner"], row["custodian"]))

    paths = client.select(
        "final_settlement_paths",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="*",
    )
    normalized_paths = [
        {
            "transfer_ref": transfer_ref(str(row.get("transfer_id", ""))),
            "path_no": row.get("path_no"),
            "hop_no": row.get("hop_no"),
            "from": participant_ref(str(row.get("from_participant_id", ""))),
            "to": participant_ref(str(row.get("to_participant_id", ""))),
            "amount": _decimal(row.get("amount")),
            "type": row.get("component_type"),
            "currency": _pick(row, "path_currency", "currency_code"),
            "original_amount": _decimal(row.get("original_amount")),
            "base_amount": _decimal(row.get("base_amount")),
        }
        for row in paths
    ]
    normalized_paths.sort(key=lambda row: (row["transfer_ref"] or "", row["path_no"] or 0, row["hop_no"] or 0))

    normalized_units = [
        {
            "ref": row.get("name"),
            "name": row.get("name"),
            "type": row.get("type"),
            "is_deleted": bool(row.get("is_deleted", False)),
        }
        for row in sorted(ledger_units, key=lambda item: str(item.get("created_at") or ""))
    ]

    statuses = client.select(
        "activity_financial_status",
        filters={"activity_id": f"eq.{activity_id}"},
        columns="*",
    )
    status = statuses[0] if statuses else {}

    return {
        "activity": {
            "type": activity.get("type"),
            "base_currency": activity.get("base_currency"),
            "multi_currency_enabled": activity.get("multi_currency_enabled"),
            "financial_version": activity.get("financial_version"),
            "is_archived": activity.get("archived_at") is not None,
            "financial_status": status.get("financial_status"),
            "completed": status.get("completed"),
            "has_unsettled_debt": status.get("has_unsettled_debt"),
            "total_debt": _decimal(status.get("total_debt")),
            "total_prepayment": _decimal(status.get("total_prepayment")),
            "prepayment_by_currency": [
                {"currency": row.get("currency"), "balance": _decimal(row.get("balance"))}
                for row in (status.get("prepayment_by_currency") or [])
                if isinstance(row, dict)
            ],
        },
        "participants": [
            {
                "ref": participant_ref(str(row.get("id", ""))),
                "name": row.get("name"),
                "order": row.get("participant_order"),
                "is_deleted": bool(row.get("is_deleted", False)),
            }
            for row in sorted(participant_rows, key=lambda item: item.get("participant_order", 0))
        ],
        "expenses": normalized_expenses,
        "expense_debts": normalized_expense_debts,
        "bilateral_debts": normalized_bilateral_debts,
        "transfers": normalized_transfers,
        "transfer_components": normalized_components,
        "transfer_allocations": normalized_transfer_allocations,
        "transfer_expense_allocations": normalized_durable_allocations,
        "prepayment_accounts": normalized_accounts,
        "prepayment_usages": normalized_usages,
        "final_settlement_paths": normalized_paths,
        "ledger_units": normalized_units,
    }
