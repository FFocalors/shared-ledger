package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.domain.financial.FinalSettlementPath
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponent
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.OnBehalfInfo
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.domain.financial.TransferDispute
import com.ffocalors.sharedledger.domain.financial.VoidMetadata
import com.ffocalors.sharedledger.domain.financial.hasValidComponentSet
import java.math.BigDecimal

enum class FakeActorRole {
    MEMBER,
    ADMIN,
}

/** Explicit local permission context; production authorization stays in auth/RLS/RPC. */
data class FakeActorContext(
    val actor: RecorderInfo = RecorderInfo("fake-app-user", "Fake Demo 管理员"),
    val role: FakeActorRole = FakeActorRole.ADMIN,
    /** The demo user's activity-member identities. The matching side is resolved per record. */
    val participantIds: Set<String> = setOf("fake-current-user", "fake-carol"),
) {
    fun currentParticipant(record: FundRecord): ParticipantInfo? =
        record.to.takeIf { it.participantId in participantIds }
            ?: record.from.takeIf { it.participantId in participantIds }
}

/** In-memory preview/test data only. This class deliberately does not imitate a network client. */
class FakeFinancialRecordRepository(
    initialRecords: List<FundRecord> = fakeFinancialRecordSamples() + fakeActivityFinancialRecordSamples(),
    private val actorContext: FakeActorContext = FakeActorContext(),
) : FinancialRecordRepository {
    private val records = initialRecords.toMutableList()

    override fun create(record: FundRecord): FinancialWriteResult<FundRecord> {
        if (record.activityId.isBlank() || record.transferId.isBlank()) {
            return FinancialWriteResult.failure("资金记录缺少 activityId 或 transferId")
        }
        if (record.amount <= BigDecimal.ZERO) return FinancialWriteResult.failure("金额必须大于 0")
        if (record.from.participantId.isBlank() || record.to.participantId.isBlank() ||
            record.from.participantId == record.to.participantId
        ) {
            return FinancialWriteResult.failure("资金记录必须有不同的付款方和收款方")
        }
        if (record.currency.length != 3 || record.currency != record.currency.uppercase()) {
            return FinancialWriteResult.failure("币种必须是 3 位大写代码")
        }
        if (!record.hasValidComponentSet()) return FinancialWriteResult.failure("资金构成必须为正数且合计等于总额")
        val existing = find(record.activityId, record.transferId)
        if (existing != null) return FinancialWriteResult.success(existing)
        records += record
        return FinancialWriteResult.success(record)
    }

    override fun list(activityId: String, type: FundRecordType?): FinancialReadResult<List<FundRecord>> =
        FinancialReadResult.Success(
            records.filter { it.activityId == activityId && (type == null || it.type == type) }
                .sortedByDescending { it.occurredAt },
        )

    override fun get(activityId: String, transferId: String): FinancialReadResult<FundRecord> =
        records.firstOrNull { it.activityId == activityId && it.transferId == transferId }
            ?.let { FinancialReadResult.Success(it) }
            ?: FinancialReadResult.Failure("未找到资金记录")

    override fun void(
        activityId: String,
        transferId: String,
        reason: String,
    ): FinancialWriteResult<FundRecord> {
        if (reason.isBlank()) return FinancialWriteResult.failure("作废必须填写原因")
        val record = find(activityId, transferId) ?: return FinancialWriteResult.failure("未找到资金记录")
        if (record.isVoided) return FinancialWriteResult.failure("记录已经作废")
        if (!canManage(record)) return FinancialWriteResult.failure("当前演示用户没有作废权限")
        val updated = record.copy(
            voidMetadata = VoidMetadata("2026-09-02 10:00", actorContext.actor, reason.trim()),
        )
        replace(updated)
        return FinancialWriteResult.success(updated)
    }

    override fun addDispute(
        activityId: String,
        transferId: String,
        participantId: String,
        note: String,
    ): FinancialWriteResult<TransferDispute> {
        if (note.isBlank()) return FinancialWriteResult.failure("争议必须填写说明")
        val record = find(activityId, transferId) ?: return FinancialWriteResult.failure("未找到资金记录")
        if (record.isVoided) return FinancialWriteResult.failure("已作废记录不能新增争议")
        if (record.hasUnresolvedDispute) return FinancialWriteResult.failure("已有未解决争议")
        val participant = listOf(record.from, record.to).firstOrNull { it.participantId == participantId }
            ?: return FinancialWriteResult.failure("参与者不是该记录的交易双方")
        if (participantId !in actorContext.participantIds) return FinancialWriteResult.failure("当前演示用户不是争议参与方")
        val dispute = TransferDispute(
            disputeId = "fake-dispute-${record.transferId}-${participantId}",
            transferId = record.transferId,
            participant = participant,
            note = note.trim(),
            createdAt = "2026-09-02 10:01",
            disputedBy = actorContext.actor,
        )
        replace(record.copy(disputes = record.disputes.filterNot { it.disputeId == dispute.disputeId } + dispute))
        return FinancialWriteResult.success(dispute)
    }

    override fun resolveDispute(
        activityId: String,
        disputeId: String,
    ): FinancialWriteResult<TransferDispute> {
        val record = records.firstOrNull { it.activityId == activityId && it.disputes.any { d -> d.disputeId == disputeId } }
            ?: return FinancialWriteResult.failure("未找到争议")
        val dispute = record.disputes.first { it.disputeId == disputeId }
        if (dispute.isResolved) return FinancialWriteResult.failure("争议已经解决")
        if (!canManage(record)) return FinancialWriteResult.failure("当前演示用户没有解决争议权限")
        val resolved = dispute.copy(resolvedAt = "2026-09-02 10:02", resolvedBy = actorContext.actor)
        replace(record.copy(disputes = record.disputes.map { if (it.disputeId == disputeId) resolved else it }))
        return FinancialWriteResult.success(resolved)
    }

    private fun find(activityId: String, transferId: String): FundRecord? =
        records.firstOrNull { it.activityId == activityId && it.transferId == transferId }

    private fun replace(updated: FundRecord) {
        val index = records.indexOfFirst { it.activityId == updated.activityId && it.transferId == updated.transferId }
        if (index >= 0) records[index] = updated
    }

    private fun canManage(record: FundRecord): Boolean =
        actorContext.role == FakeActorRole.ADMIN || record.recordedBy.userId == actorContext.actor.userId
}

fun fakeFinancialRecordSamples(): List<FundRecord> {
    val alice = ParticipantInfo("fake-alice", "Alice")
    val bob = ParticipantInfo("fake-bob", "Bob")
    val carol = ParticipantInfo("fake-carol", "Carol")
    val recorder = RecorderInfo("fake-user", "Fake 预览记录人")
    return listOf(
        FundRecord(
            transferId = "fake-settlement-001", activityId = "fake-preview-activity",
            from = alice, to = bob, type = FundRecordType.SETTLEMENT,
            amount = BigDecimal("120.00"), currency = "CNY", occurredAt = "2026-09-02 09:00",
            recordedAt = "2026-09-02 09:01", recordedBy = recorder,
            components = listOf(FundRecordComponent("fake-component-1", FundRecordComponentType.SETTLEMENT, BigDecimal("120.00"))),
        ),
        FundRecord(
            transferId = "fake-prepayment-001", activityId = "fake-preview-activity",
            from = bob, to = carol, type = FundRecordType.PREPAYMENT,
            amount = BigDecimal("500.00"), currency = "CNY", occurredAt = "2026-09-01 15:10",
            recordedAt = "2026-09-01 15:11", recordedBy = recorder,
            onBehalfOf = OnBehalfInfo(bob.participantId, bob.displayName),
            components = listOf(
                FundRecordComponent("fake-component-2", FundRecordComponentType.SETTLEMENT, BigDecimal("80.00")),
                FundRecordComponent("fake-component-3", FundRecordComponentType.PREPAYMENT, BigDecimal("420.00")),
            ),
        ),
        FundRecord(
            transferId = "fake-return-001", activityId = "fake-preview-activity",
            from = carol, to = bob, type = FundRecordType.PREPAYMENT_RETURN,
            amount = BigDecimal("100.00"), currency = "CNY", occurredAt = "2026-08-30 12:00",
            recordedAt = "2026-08-30 12:01", recordedBy = recorder,
            components = listOf(FundRecordComponent("fake-component-4", FundRecordComponentType.PREPAYMENT_RETURN, BigDecimal("100.00"))),
        ),
        FundRecord(
            transferId = "fake-final-001", activityId = "fake-preview-activity",
            from = alice, to = carol, type = FundRecordType.FINAL_SETTLEMENT,
            amount = BigDecimal("320.00"), currency = "CNY", occurredAt = "2026-08-29 18:30",
            recordedAt = "2026-08-29 18:31", recordedBy = recorder,
            components = listOf(FundRecordComponent("fake-component-5", FundRecordComponentType.SETTLEMENT, BigDecimal("200.00")), FundRecordComponent("fake-component-6", FundRecordComponentType.PREPAYMENT_RETURN, BigDecimal("120.00"))),
            finalSettlementPaths = listOf(
                FinalSettlementPath(1, 1, alice, bob, BigDecimal("320.00"), FundRecordComponentType.SETTLEMENT),
                FinalSettlementPath(1, 2, bob, carol, BigDecimal("320.00"), FundRecordComponentType.SETTLEMENT),
            ),
        ),
    )
}

/** Demo activities use the same explicit fake repository, but keep activity scope real in reads. */
fun fakeActivityFinancialRecordSamples(): List<FundRecord> = listOf(
    "demo-normal" to "demo-normal",
    "demo-large" to "demo-large",
).flatMap { (activityId, prefix) ->
    fakeFinancialRecordSamples().map { record ->
        record.copy(
            activityId = activityId,
            transferId = "$prefix-${record.transferId}",
        )
    }
}
