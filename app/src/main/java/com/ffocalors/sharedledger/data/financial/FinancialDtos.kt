package com.ffocalors.sharedledger.data.financial

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
internal data class FinancialTransferRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("from_participant_id") val fromParticipantId: String,
    @SerialName("to_participant_id") val toParticipantId: String,
    val type: String,
    val amount: JsonElement? = null,
    val currency: String,
    @SerialName("occurred_at") val occurredAt: String,
    @SerialName("recorded_by") val recordedBy: String,
    @SerialName("on_behalf_of_participant_id") val onBehalfOfParticipantId: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("is_voided") val isVoided: Boolean = false,
    @SerialName("voided_at") val voidedAt: String? = null,
    @SerialName("voided_by") val voidedBy: String? = null,
    @SerialName("void_reason") val voidReason: String? = null,
)

@Serializable
internal data class FinancialParticipantRowDto(
    val id: String,
    val name: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
internal data class FinancialProfileRowDto(
    val id: String,
    @SerialName("display_name") val displayName: String? = null,
)

@Serializable
internal data class FinancialComponentRowDto(
    val id: String,
    @SerialName("transfer_id") val transferId: String,
    @SerialName("component_type") val componentType: String,
    val amount: JsonElement? = null,
)

@Serializable
internal data class FinancialDisputeRowDto(
    val id: String,
    @SerialName("transfer_id") val transferId: String,
    @SerialName("participant_id") val participantId: String,
    @SerialName("disputed_by") val disputedBy: String,
    val note: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("resolved_at") val resolvedAt: String? = null,
    @SerialName("resolved_by") val resolvedBy: String? = null,
)

@Serializable
internal data class FinancialPathRowDto(
    val id: String,
    @SerialName("transfer_id") val transferId: String,
    @SerialName("path_no") val pathNo: Int,
    @SerialName("hop_no") val hopNo: Int,
    @SerialName("from_participant_id") val fromParticipantId: String,
    @SerialName("to_participant_id") val toParticipantId: String,
    val amount: JsonElement? = null,
    @SerialName("component_type") val componentType: String,
)

@Serializable
internal data class FinancialAccountRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("owner_participant_id") val ownerParticipantId: String,
    @SerialName("custodian_participant_id") val custodianParticipantId: String,
    val balance: JsonElement? = null,
)

@Serializable
internal data class FinancialPrepaymentUsageRowDto(
    val id: String,
    @SerialName("account_id") val accountId: String,
    val amount: JsonElement? = null,
    @SerialName("expense_debt_id") val expenseDebtId: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
internal data class FinancialExpenseDebtRowDto(
    val id: String,
    @SerialName("expense_id") val expenseId: String,
)

@Serializable
internal data class FinancialExpenseTimelineRowDto(
    val id: String,
    val title: String,
    @SerialName("occurred_at") val occurredAt: String,
)

@Serializable
internal data class FinancialActivityRowDto(
    @SerialName("base_currency") val baseCurrency: String,
)

@Serializable
internal data class FinancialClaimRowDto(
    @SerialName("participant_id") val participantId: String,
)

@Serializable
internal data class FinancialVoidRpcDto(
    @SerialName("transfer_id") val transferId: String,
    val voided: Boolean,
    @SerialName("financial_version") val financialVersion: Long,
)

@Serializable
internal data class FinancialDisputeRpcDto(
    @SerialName("dispute_id") val disputeId: String,
    val created: Boolean,
)

@Serializable
internal data class FinancialTransferRpcDto(
    @SerialName("transfer_id") val transferId: String,
    val amount: JsonElement? = null,
    val currency: String,
    @SerialName("financial_version") val financialVersion: Long,
)

@Serializable
internal data class FinancialPrepaymentRpcDto(
    @SerialName("transfer_id") val transferId: String,
    @SerialName("settlement_amount") val settlementAmount: JsonElement? = null,
    @SerialName("prepayment_amount") val prepaymentAmount: JsonElement? = null,
    val currency: String,
    @SerialName("financial_version") val financialVersion: Long,
)

@Serializable
internal data class FinancialPreviewRowDto(
    @SerialName("activity_id") val activityId: String,
    @SerialName("from_participant_id") val fromParticipantId: String,
    @SerialName("to_participant_id") val toParticipantId: String,
    val amount: JsonElement? = null,
    @SerialName("ordinary_amount") val ordinaryAmount: JsonElement? = null,
    @SerialName("prepayment_return_amount") val prepaymentReturnAmount: JsonElement? = null,
    val currency: String,
    @SerialName("source_financial_version") val sourceFinancialVersion: Long,
    @SerialName("is_prepayment_return") val isPrepaymentReturn: Boolean = false,
)
