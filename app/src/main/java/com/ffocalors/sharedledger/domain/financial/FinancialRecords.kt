package com.ffocalors.sharedledger.domain.financial

import java.math.BigDecimal

/** The values are the public.transfer_type enum values in the database. */
enum class FundRecordType(
    val databaseValue: String,
    val displayName: String,
) {
    SETTLEMENT("settlement", "结算转账"),
    PREPAYMENT("prepayment", "预存"),
    PREPAYMENT_RETURN("prepayment_return", "预存返还"),
    FINAL_SETTLEMENT("final_settlement", "最终结算"),
    ;

    companion object {
        fun fromDatabaseValue(value: String): FundRecordType =
            entries.firstOrNull { it.databaseValue == value }
                ?: error("Unknown transfers.type: $value")

        fun fromDatabaseValueOrNull(value: String?): FundRecordType? =
            value?.let { raw -> entries.firstOrNull { it.databaseValue == raw } }
    }
}

/** The only component_type values allowed by public.transfer_components. */
enum class FundRecordComponentType(
    val databaseValue: String,
    val displayName: String,
) {
    SETTLEMENT("settlement", "偿还欠款"),
    PREPAYMENT("prepayment", "新增预存"),
    PREPAYMENT_RETURN("prepayment_return", "预存返还"),
    ;

    companion object {
        fun fromDatabaseValue(value: String): FundRecordComponentType =
            entries.firstOrNull { it.databaseValue == value }
                ?: error("Unknown transfer_components.component_type: $value")
    }
}

data class ParticipantInfo(
    val participantId: String,
    val displayName: String,
)

data class RecorderInfo(
    val userId: String,
    val displayName: String,
)

data class OnBehalfInfo(
    val participantId: String,
    val displayName: String,
)

data class FundRecordComponent(
    val componentId: String,
    val type: FundRecordComponentType,
    val amount: BigDecimal,
)

data class VoidMetadata(
    val voidedAt: String,
    val voidedBy: RecorderInfo,
    val reason: String,
)

data class TransferDispute(
    val disputeId: String,
    val transferId: String,
    val participant: ParticipantInfo,
    val note: String,
    val createdAt: String,
    /** Audit snapshot of the member who opened the dispute. Backed by reported_by_member_id. */
    val disputedBy: RecorderInfo = RecorderInfo("unknown", "未知用户"),
    val resolvedAt: String? = null,
    val resolvedBy: RecorderInfo? = null,
) {
    val isResolved: Boolean get() = resolvedAt != null
}

/** A persisted path row. It is explanatory metadata, not another financial fact. */
data class FinalSettlementPath(
    val pathNo: Int,
    val hopNo: Int,
    val from: ParticipantInfo,
    val to: ParticipantInfo,
    val amount: BigDecimal,
    val componentType: FundRecordComponentType,
)

data class FinalSettlementPathSummary(
    val pathNo: Int,
    val hopCount: Int,
    val from: ParticipantInfo,
    val to: ParticipantInfo,
    /** The transfer endpoint amount; hop amounts must never be summed into it. */
    val endpointAmount: BigDecimal,
    val componentType: FundRecordComponentType,
)

data class FundRecord(
    val transferId: String,
    val activityId: String,
    val from: ParticipantInfo,
    val to: ParticipantInfo,
    val type: FundRecordType,
    val amount: BigDecimal,
    val currency: String,
    val occurredAt: String,
    val recordedAt: String,
    val recordedBy: RecorderInfo,
    val onBehalfOf: OnBehalfInfo? = null,
    val components: List<FundRecordComponent> = emptyList(),
    val voidMetadata: VoidMetadata? = null,
    val disputes: List<TransferDispute> = emptyList(),
    val finalSettlementPaths: List<FinalSettlementPath> = emptyList(),
) {
    val isVoided: Boolean get() = voidMetadata != null
    val unresolvedDisputes: List<TransferDispute> get() = disputes.filterNot { it.isResolved }
    val hasUnresolvedDispute: Boolean get() = unresolvedDisputes.isNotEmpty()

    /** Groups path hops for explanation without adding the repeated hop amounts. */
    val finalSettlementPathSummaries: List<FinalSettlementPathSummary>
        get() = finalSettlementPaths
            .groupBy { it.pathNo }
            .toSortedMap()
            .values
            .map { hops ->
                val first = hops.minBy { it.hopNo }
                val last = hops.maxBy { it.hopNo }
                FinalSettlementPathSummary(
                    pathNo = first.pathNo,
                    hopCount = hops.size,
                    from = first.from,
                    to = last.to,
                    endpointAmount = amount,
                    componentType = first.componentType,
                )
            }
}

/** Encodes the component rules enforced by private.assert_component_total and its RPC callers. */
fun isValidComponentSet(recordType: FundRecordType, components: List<FundRecordComponent>): Boolean {
    if (components.isEmpty() || components.map { it.type }.distinct().size != components.size) return false
    if (components.any { it.amount <= BigDecimal.ZERO }) return false
    if (components.sumOf { it.amount } <= BigDecimal.ZERO) return false
    val types = components.map { it.type }.toSet()
    return when (recordType) {
        FundRecordType.SETTLEMENT -> types == setOf(FundRecordComponentType.SETTLEMENT)
        FundRecordType.PREPAYMENT ->
            types.isNotEmpty() && types.all {
                it == FundRecordComponentType.SETTLEMENT || it == FundRecordComponentType.PREPAYMENT
            }
        FundRecordType.PREPAYMENT_RETURN -> types == setOf(FundRecordComponentType.PREPAYMENT_RETURN)
        FundRecordType.FINAL_SETTLEMENT ->
            types.isNotEmpty() && types.all {
                it == FundRecordComponentType.SETTLEMENT || it == FundRecordComponentType.PREPAYMENT_RETURN
            }
    }
}

fun FundRecord.hasValidComponentSet(): Boolean =
    components.sumOf { it.amount }.compareTo(amount) == 0 && isValidComponentSet(type, components)

fun FundRecordType.componentTypesAllowed(): Set<FundRecordComponentType> = when (this) {
    FundRecordType.SETTLEMENT -> setOf(FundRecordComponentType.SETTLEMENT)
    FundRecordType.PREPAYMENT -> setOf(FundRecordComponentType.SETTLEMENT, FundRecordComponentType.PREPAYMENT)
    FundRecordType.PREPAYMENT_RETURN -> setOf(FundRecordComponentType.PREPAYMENT_RETURN)
    FundRecordType.FINAL_SETTLEMENT -> setOf(FundRecordComponentType.SETTLEMENT, FundRecordComponentType.PREPAYMENT_RETURN)
}
