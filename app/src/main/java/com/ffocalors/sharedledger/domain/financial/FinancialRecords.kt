package com.ffocalors.sharedledger.domain.financial

import java.math.BigDecimal

/** Transfer values mirror public.transfer_type; projected timeline rows use client-only keys. */
enum class FundRecordType(
    val databaseValue: String,
    val displayName: String,
) {
    SETTLEMENT("settlement", "结算转账"),
    PREPAYMENT("prepayment", "预存"),
    PREPAYMENT_RETURN("prepayment_return", "预存返还"),
    FINAL_SETTLEMENT("final_settlement", "最终结算"),
    AUTO_PREPAYMENT_USAGE("auto_prepayment_usage", "预存自动扣款"),
    REFUND("refund", "退款"),
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
    val claimedUserId: String? = null,
    val avatarStyle: String? = null,
)

data class RecorderInfo(
    val userId: String,
    val displayName: String,
    val avatarStyle: String? = null,
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
    val currency: String? = null,
    val baseAmount: BigDecimal? = null,
    val originalAmount: BigDecimal? = null,
    val mode: String? = null,
    val pathCurrency: String? = null,
)

data class FinalSettlementPathSummary(
    val pathNo: Int,
    val hopCount: Int,
    val from: ParticipantInfo,
    val to: ParticipantInfo,
    /** Every participant in the path, in graph order, including both endpoints. */
    val participants: List<ParticipantInfo>,
    /** The path's actual flow amount; repeated hop amounts must never be summed into it. */
    val endpointAmount: BigDecimal,
    val componentType: FundRecordComponentType,
)

private data class MergedFinalSettlementEdge(
    val from: ParticipantInfo,
    val to: ParticipantInfo,
    val amount: BigDecimal,
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
    val source: FundRecordSource = FundRecordSource.TRANSFER,
    val sourceExpenseId: String? = null,
    val sourceExpenseTitle: String? = null,
) {
    val isVoided: Boolean get() = voidMetadata != null
    val isReadOnly: Boolean get() = source != FundRecordSource.TRANSFER
    val unresolvedDisputes: List<TransferDispute> get() = disputes.filterNot { it.isResolved }
    val hasUnresolvedDispute: Boolean get() = unresolvedDisputes.isNotEmpty()

    /**
     * Groups path allocations into graph edges for explanation without adding repeated hop amounts.
     * Rows for a split source debt are stable-sorted by hop number and merged only while the same
     * edge remains consecutive; the first merged edge carries the path flow amount.
     */
    val finalSettlementPathSummaries: List<FinalSettlementPathSummary>
        get() = finalSettlementPaths
            .groupBy { it.pathNo }
            .toSortedMap()
            .values
            .mapNotNull { hops ->
                val mergedEdges = hops
                    // Kotlin's sortedWith is stable, so rows sharing a hop number retain their
                    // persisted/input order for the consecutive-edge merge below.
                    .sortedWith(compareBy<FinalSettlementPath> { it.hopNo })
                    .fold(mutableListOf<MergedFinalSettlementEdge>()) { edges, hop ->
                        val previous = edges.lastOrNull()
                        if (previous != null &&
                            previous.from.participantId == hop.from.participantId &&
                            previous.to.participantId == hop.to.participantId
                        ) {
                            edges[edges.lastIndex] = previous.copy(amount = previous.amount + hop.amount)
                        } else {
                            edges += MergedFinalSettlementEdge(
                                from = hop.from,
                                to = hop.to,
                                amount = hop.amount,
                                componentType = hop.componentType,
                            )
                        }
                        edges
                    }
                val firstEdge = mergedEdges.firstOrNull() ?: return@mapNotNull null
                val participants = buildList {
                    add(firstEdge.from)
                    mergedEdges.forEach { add(it.to) }
                }
                FinalSettlementPathSummary(
                    pathNo = hops.first().pathNo,
                    hopCount = mergedEdges.size,
                    from = participants.first(),
                    to = participants.last(),
                    participants = participants,
                    endpointAmount = firstEdge.amount,
                    componentType = firstEdge.componentType,
                )
            }
}

enum class FundRecordSource {
    TRANSFER,
    PREPAYMENT_USAGE,
    REFUND_EXPENSE,
}

/** Encodes the component rules enforced by private.assert_component_total and its RPC callers. */
fun isValidComponentSet(recordType: FundRecordType, components: List<FundRecordComponent>): Boolean {
    if (recordType == FundRecordType.AUTO_PREPAYMENT_USAGE || recordType == FundRecordType.REFUND) return components.isEmpty()
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
        FundRecordType.REFUND -> components.isEmpty()
    }
}

fun FundRecord.hasValidComponentSet(): Boolean =
    if (type == FundRecordType.AUTO_PREPAYMENT_USAGE || type == FundRecordType.REFUND) amount > BigDecimal.ZERO && components.isEmpty()
    else components.sumOf { it.amount }.compareTo(amount) == 0 && isValidComponentSet(type, components)

fun FundRecordType.componentTypesAllowed(): Set<FundRecordComponentType> = when (this) {
    FundRecordType.SETTLEMENT -> setOf(FundRecordComponentType.SETTLEMENT)
    FundRecordType.PREPAYMENT -> setOf(FundRecordComponentType.SETTLEMENT, FundRecordComponentType.PREPAYMENT)
    FundRecordType.PREPAYMENT_RETURN -> setOf(FundRecordComponentType.PREPAYMENT_RETURN)
    FundRecordType.FINAL_SETTLEMENT -> setOf(FundRecordComponentType.SETTLEMENT, FundRecordComponentType.PREPAYMENT_RETURN)
    FundRecordType.AUTO_PREPAYMENT_USAGE -> emptySet()
    FundRecordType.REFUND -> emptySet()
}
