package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.domain.financial.FinalSettlementPath
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponent
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.FundRecordSource
import com.ffocalors.sharedledger.domain.financial.OnBehalfInfo
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.domain.financial.TransferDispute
import com.ffocalors.sharedledger.domain.financial.VoidMetadata
import java.math.BigDecimal
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

internal fun JsonElement?.toFinancialBigDecimal(): BigDecimal = when (this) {
    null, JsonNull -> BigDecimal.ZERO
    is JsonPrimitive -> content.toBigDecimalOrNull() ?: error("invalid numeric financial value")
    else -> error("invalid numeric financial value")
}

internal fun FinancialParticipantRowDto.toParticipant(): ParticipantInfo = ParticipantInfo(id, name)

internal fun FinancialProfileRowDto.toRecorder(): RecorderInfo = RecorderInfo(id, displayName?.takeIf { it.isNotBlank() } ?: "未命名用户")

internal fun aggregatePrepaymentUsageAmounts(
    usages: List<FinancialPrepaymentUsageRowDto>,
): Map<String, BigDecimal> = usages
    .groupBy { it.accountId }
    .mapValues { (_, rows) -> rows.fold(BigDecimal.ZERO) { total, row -> total + row.amount.toFinancialBigDecimal() } }

internal fun mapFinancialRecord(
    transfer: FinancialTransferRowDto,
    participants: Map<String, ParticipantInfo>,
    profiles: Map<String, RecorderInfo>,
    components: List<FinancialComponentRowDto>,
    disputes: List<FinancialDisputeRowDto>,
    paths: List<FinancialPathRowDto>,
): FundRecord {
    fun participant(id: String) = participants[id] ?: ParticipantInfo(id, "未命名参与人")
    fun recorder(id: String?) = id?.let { profiles[it] } ?: RecorderInfo("unknown", "未知用户")
    return FundRecord(
        transferId = transfer.id,
        activityId = transfer.activityId,
        from = participant(transfer.fromParticipantId),
        to = participant(transfer.toParticipantId),
        type = FundRecordType.fromDatabaseValue(transfer.type),
        amount = transfer.amount.toFinancialBigDecimal(),
        currency = transfer.currency.trim().uppercase(),
        occurredAt = transfer.occurredAt,
        recordedAt = transfer.createdAt,
        recordedBy = recorder(transfer.recordedBy),
        onBehalfOf = transfer.onBehalfOfParticipantId?.let { OnBehalfInfo(it, participant(it).displayName) },
        components = components.map {
            FundRecordComponent(it.id, FundRecordComponentType.fromDatabaseValue(it.componentType), it.amount.toFinancialBigDecimal())
        },
        voidMetadata = if (transfer.isVoided) {
            VoidMetadata(transfer.voidedAt.orEmpty(), recorder(transfer.voidedBy), transfer.voidReason.orEmpty())
        } else null,
        disputes = disputes.map {
            TransferDispute(
                disputeId = it.id,
                transferId = it.transferId,
                participant = participant(it.participantId),
                note = it.note.orEmpty().ifBlank { "未填写说明" },
                createdAt = it.createdAt,
                disputedBy = recorder(it.disputedBy),
                resolvedAt = it.resolvedAt,
                resolvedBy = it.resolvedBy?.let(::recorder),
            )
        },
        finalSettlementPaths = paths.map {
            FinalSettlementPath(
                pathNo = it.pathNo,
                hopNo = it.hopNo,
                from = participant(it.fromParticipantId),
                to = participant(it.toParticipantId),
                amount = it.amount.toFinancialBigDecimal(),
                componentType = FundRecordComponentType.fromDatabaseValue(it.componentType),
            )
        },
        source = FundRecordSource.TRANSFER,
    )
}

internal fun mapPrepaymentUsageRecord(
    usage: FinancialPrepaymentUsageRowDto,
    account: FinancialAccountRowDto,
    debt: FinancialExpenseDebtRowDto,
    expense: FinancialExpenseTimelineRowDto,
    participants: Map<String, ParticipantInfo>,
    currency: String,
): FundRecord? {
    val from = participants[account.ownerParticipantId] ?: return null
    val to = participants[account.custodianParticipantId] ?: return null
    val amount = usage.amount.toFinancialBigDecimal()
    if (amount <= BigDecimal.ZERO) return null
    return FundRecord(
        // Both projection row IDs are regenerated during a rebuild; owner + custodian + debt is stable.
        transferId = "usage:${account.ownerParticipantId}:${account.custodianParticipantId}:${debt.id}",
        activityId = account.activityId,
        from = from,
        to = to,
        type = FundRecordType.AUTO_PREPAYMENT_USAGE,
        amount = amount,
        currency = currency,
        occurredAt = expense.occurredAt,
        recordedAt = usage.createdAt ?: expense.occurredAt,
        recordedBy = RecorderInfo("system:prepayment", "系统自动支付"),
        source = FundRecordSource.PREPAYMENT_USAGE,
        sourceExpenseId = debt.expenseId,
        sourceExpenseTitle = expense.title,
    )
}
