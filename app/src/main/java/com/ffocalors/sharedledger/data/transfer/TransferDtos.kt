package com.ffocalors.sharedledger.data.transfer

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
internal data class TransferActivityRowDto(
    @SerialName("base_currency") val baseCurrency: String,
    @SerialName("multi_currency_enabled") val multiCurrencyEnabled: Boolean = false,
    @SerialName("created_by") val createdBy: String? = null,
)

@Serializable
internal data class TransferParticipantRowDto(
    val id: String,
    val name: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
internal data class TransferClaimRowDto(
    @SerialName("participant_id") val participantId: String,
    @SerialName("user_id") val userId: String? = null,
)

@Serializable
internal data class TransferProfileRowDto(
    val id: String,
    @SerialName("avatar_style") val avatarStyle: String? = null,
)

@Serializable
internal data class BilateralDebtRowDto(
    @SerialName("debtor_participant_id") val debtorParticipantId: String,
    @SerialName("creditor_participant_id") val creditorParticipantId: String,
    val amount: JsonElement? = null,
)

@Serializable
internal data class SettlementOptionRowDto(
    @SerialName("debtor_participant_id") val debtorParticipantId: String,
    @SerialName("creditor_participant_id") val creditorParticipantId: String,
    val currency: String,
    @SerialName("original_amount") val originalAmount: JsonElement? = null,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
    @SerialName("financial_version") val financialVersion: Long,
    @SerialName("base_total") val baseTotal: JsonElement? = null,
)

/**
 * Expense-level rows returned by the targeted repayment read model.  Every
 * amount is a residual after prepayment and previous valid settlement facts.
 */
@Serializable
internal data class SettlementExpenseRowDto(
    @SerialName("expense_id") val expenseId: String,
    @SerialName("debtor_participant_id") val debtorParticipantId: String? = null,
    @SerialName("creditor_participant_id") val creditorParticipantId: String? = null,
    @SerialName("ledger_unit_id") val ledgerUnitId: String? = null,
    @SerialName("ledger_unit_name") val ledgerUnitName: String? = null,
    val title: String? = null,
    @SerialName("occurred_at") val occurredAt: String? = null,
    @SerialName("debt_currency") val debtCurrency: String? = null,
    @SerialName("debt_original_amount") val debtOriginalAmount: JsonElement? = null,
    @SerialName("debt_base_amount") val debtBaseAmount: JsonElement? = null,
    @SerialName("offset_original_amount") val offsetOriginalAmount: JsonElement? = null,
    @SerialName("settled_original_amount") val settledOriginalAmount: JsonElement? = null,
    @SerialName("prepayment_original_amount") val prepaymentOriginalAmount: JsonElement? = null,
    @SerialName("remaining_original_amount") val remainingOriginalAmount: JsonElement? = null,
    @SerialName("remaining_base_amount") val remainingBaseAmount: JsonElement? = null,
    @SerialName("payment_currency_amount") val paymentCurrencyAmount: JsonElement? = null,
    @SerialName("financial_version") val financialVersion: Long? = null,
)

@Serializable
internal data class SettlementPreviewRowDto(
    @SerialName("expense_id") val expenseId: String,
    @SerialName("payment_amount") val paymentAmount: JsonElement? = null,
    @SerialName("original_amount") val originalAmount: JsonElement? = null,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
    @SerialName("remaining_amount") val remainingAmount: JsonElement? = null,
    @SerialName("remaining_original_amount") val remainingOriginalAmount: JsonElement? = null,
    @SerialName("remaining_base_amount") val remainingBaseAmount: JsonElement? = null,
    @SerialName("financial_version") val financialVersion: Long? = null,
    @SerialName("payment_currency") val paymentCurrency: String? = null,
    @SerialName("original_currency") val originalCurrency: String? = null,
    @SerialName("source_financial_version") val sourceFinancialVersion: Long? = null,
)

@Serializable
internal data class CreateSettlementTransferRpcDto(
    @SerialName("transfer_id") val transferId: String,
    val amount: JsonElement? = null,
    val currency: String,
    @SerialName("financial_version") val financialVersion: Long,
)
