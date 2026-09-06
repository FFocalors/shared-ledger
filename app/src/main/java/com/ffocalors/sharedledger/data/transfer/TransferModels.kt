package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal

enum class SettlementDirection {
    TRANSFER,
    RECEIVE,
}

data class SettlementCandidate(
    val participantId: String,
    val participantName: String,
    val amount: BigDecimal,
)

data class SettlementContext(
    val activityId: String,
    val currentParticipantId: String?,
    val currentParticipantName: String?,
    val baseCurrency: String,
    val candidates: List<SettlementCandidate>,
)

data class CreateSettlementTransferInput(
    val activityId: String,
    val currentParticipantId: String,
    val selectedParticipantId: String,
    val amount: BigDecimal,
    val direction: SettlementDirection,
    val occurredAt: String,
)

data class SettlementTransferResult(
    val transferId: String,
    val amount: BigDecimal,
    val currency: String,
    val financialVersion: Long,
)

