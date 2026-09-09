package com.ffocalors.sharedledger.ui.navigation

import com.ffocalors.sharedledger.domain.financial.FinalSettlementPath
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponent
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.ui.screens.FinalSettlementRequest
import java.math.BigDecimal

internal fun demoFinalSettlementRecord(request: FinalSettlementRequest, transferId: String, actor: RecorderInfo): FundRecord {
    val from = demoParticipant(request.fromParticipantId)
    val to = demoParticipant(request.toParticipantId)
    val components = listOfNotNull(
        request.ordinaryAmount.takeIf { it > BigDecimal.ZERO }
            ?.let { FundRecordComponent("$transferId-ordinary", FundRecordComponentType.SETTLEMENT, it) },
        request.prepaymentReturnAmount.takeIf { it > BigDecimal.ZERO }
            ?.let { FundRecordComponent("$transferId-prepayment-return", FundRecordComponentType.PREPAYMENT_RETURN, it) },
    )
    return FundRecord(
        transferId = transferId,
        activityId = request.activityId,
        from = from,
        to = to,
        type = FundRecordType.FINAL_SETTLEMENT,
        amount = request.amount,
        currency = request.currency,
        occurredAt = "2026-09-02 10:20",
        recordedAt = "2026-09-02 10:20",
        recordedBy = actor,
        components = components,
        finalSettlementPaths = components.mapIndexed { index, component ->
            FinalSettlementPath(index + 1, 1, from, to, component.amount, component.type)
        },
    )
}

private fun demoParticipant(participantId: String): ParticipantInfo = when (participantId) {
    "fake-alice" -> ParticipantInfo(participantId, "Alice")
    "fake-bob" -> ParticipantInfo(participantId, "Bob")
    "fake-carol" -> ParticipantInfo(participantId, "Carol")
    else -> ParticipantInfo(participantId, participantId)
}
