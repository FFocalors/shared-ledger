package com.ffocalors.sharedledger.data.transfer

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
internal data class TransferActivityRowDto(
    @SerialName("base_currency") val baseCurrency: String,
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
)

@Serializable
internal data class BilateralDebtRowDto(
    @SerialName("debtor_participant_id") val debtorParticipantId: String,
    @SerialName("creditor_participant_id") val creditorParticipantId: String,
    val amount: JsonElement? = null,
)

@Serializable
internal data class CreateSettlementTransferRpcDto(
    @SerialName("transfer_id") val transferId: String,
    val amount: JsonElement? = null,
    val currency: String,
    @SerialName("financial_version") val financialVersion: Long,
)

