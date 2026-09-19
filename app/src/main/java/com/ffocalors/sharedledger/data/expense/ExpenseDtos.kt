package com.ffocalors.sharedledger.data.expense

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class ExpenseRowDto(
    val id: String,
    @SerialName("ledger_unit_id") val ledgerUnitId: String,
    val title: String,
    @SerialName("original_amount") val originalAmount: JsonElement,
    @SerialName("original_currency") val originalCurrency: String,
    @SerialName("fx_rate") val fxRate: JsonElement,
    @SerialName("base_amount") val baseAmount: JsonElement,
    @SerialName("split_method") val splitMethod: String,
    @SerialName("occurred_at") val occurredAt: String,
    val note: String? = null,
    @SerialName("original_expense_id") val originalExpenseId: String? = null,
    @SerialName("created_by") val createdBy: String,
    @SerialName("updated_by") val updatedBy: String,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    val version: Long,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
    @SerialName("fx_rate_source") val fxRateSource: String = "legacy_manual",
    @SerialName("fx_rate_observed_at") val fxRateObservedAt: String? = null,
    @SerialName("icon_key") val iconKey: String = ExpenseIconKey.MONEY,
)

@Serializable
data class PaymentRowDto(
    val id: String,
    @SerialName("expense_id") val expenseId: String,
    @SerialName("participant_id") val participantId: String,
    val amount: JsonElement,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
)

@Serializable
data class SplitRowDto(
    val id: String,
    @SerialName("expense_id") val expenseId: String,
    @SerialName("participant_id") val participantId: String,
    val amount: JsonElement,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
)

@Serializable
data class ExpenseDebtRowDto(
    val id: String,
    @SerialName("debtor_participant_id") val debtorParticipantId: String,
    val amount: JsonElement,
)

@Serializable
data class TransferAllocationRowDto(
    @SerialName("expense_debt_id") val expenseDebtId: String,
    val amount: JsonElement,
)

@Serializable
data class PrepaymentUsageRowDto(
    @SerialName("expense_debt_id") val expenseDebtId: String,
    val amount: JsonElement,
)

@Serializable
data class ExpenseLedgerUnitRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    val name: String,
    val type: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
data class ExpenseActivityCurrencyRowDto(
    @SerialName("base_currency") val baseCurrency: String,
)

@Serializable
data class ExpenseParticipantRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    val name: String,
    @SerialName("participant_order") val participantOrder: Int,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
data class CreateExpenseRpcDto(
    @SerialName("expense_id") val expenseId: String,
    @SerialName("base_amount") val baseAmount: JsonElement,
    val version: Long,
    @SerialName("fx_rate") val fxRate: JsonElement? = null,
    @SerialName("fx_rate_source") val fxRateSource: String? = null,
    @SerialName("fx_rate_observed_at") val fxRateObservedAt: String? = null,
)

@Serializable
data class UpdateExpenseRpcDto(
    @SerialName("updated_expense_id") val updatedExpenseId: String,
    @SerialName("base_amount") val baseAmount: JsonElement,
    val version: Long,
    @SerialName("fx_rate") val fxRate: JsonElement? = null,
    @SerialName("fx_rate_source") val fxRateSource: String? = null,
    @SerialName("fx_rate_observed_at") val fxRateObservedAt: String? = null,
)

@Serializable
data class DeleteExpenseRpcDto(
    @SerialName("deleted_expense_id") val deletedExpenseId: String,
    val deleted: Boolean,
    val version: Long,
)

@Serializable
data class RestoreExpenseRpcDto(
    @SerialName("restored_expense_id") val restoredExpenseId: String,
    val restored: Boolean,
    val version: Long,
)
