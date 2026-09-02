package com.ffocalors.sharedledger.domain.financial

import com.ffocalors.sharedledger.data.financial.FakeFinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FakeActorContext
import com.ffocalors.sharedledger.data.financial.FakeActorRole
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FinancialRecordsTest {
    @Test
    fun databaseTypeMappingCoversExactlyTheFourTransferTypes() {
        assertEquals(FundRecordType.SETTLEMENT, FundRecordType.fromDatabaseValue("settlement"))
        assertEquals(FundRecordType.PREPAYMENT, FundRecordType.fromDatabaseValue("prepayment"))
        assertEquals(FundRecordType.PREPAYMENT_RETURN, FundRecordType.fromDatabaseValue("prepayment_return"))
        assertEquals(FundRecordType.FINAL_SETTLEMENT, FundRecordType.fromDatabaseValue("final_settlement"))
        assertEquals(4, FundRecordType.entries.size)
    }

    @Test
    fun componentRulesMatchSettlementPrepaymentReturnAndFinalSettlementContracts() {
        fun component(type: FundRecordComponentType, amount: String) =
            FundRecordComponent(type.databaseValue, type, BigDecimal(amount))

        assertTrue(isValidComponentSet(FundRecordType.SETTLEMENT, listOf(component(FundRecordComponentType.SETTLEMENT, "10"))))
        assertTrue(isValidComponentSet(FundRecordType.PREPAYMENT, listOf(
            component(FundRecordComponentType.SETTLEMENT, "3"),
            component(FundRecordComponentType.PREPAYMENT, "7"),
        )))
        assertTrue(isValidComponentSet(FundRecordType.PREPAYMENT_RETURN, listOf(component(FundRecordComponentType.PREPAYMENT_RETURN, "10"))))
        assertTrue(isValidComponentSet(FundRecordType.FINAL_SETTLEMENT, listOf(
            component(FundRecordComponentType.SETTLEMENT, "3"),
            component(FundRecordComponentType.PREPAYMENT_RETURN, "7"),
        )))
        assertFalse(isValidComponentSet(FundRecordType.SETTLEMENT, listOf(component(FundRecordComponentType.PREPAYMENT, "10"))))
        assertFalse(isValidComponentSet(FundRecordType.PREPAYMENT_RETURN, listOf(component(FundRecordComponentType.SETTLEMENT, "10"))))
    }

    @Test
    fun pathSummaryUsesTransferEndpointAmountInsteadOfSummingRepeatedHops() {
        val alice = ParticipantInfo("a", "Alice")
        val bob = ParticipantInfo("b", "Bob")
        val carol = ParticipantInfo("c", "Carol")
        val record = FundRecord(
            transferId = "t", activityId = "activity", from = alice, to = carol,
            type = FundRecordType.FINAL_SETTLEMENT, amount = BigDecimal("20"), currency = "CNY",
            occurredAt = "now", recordedAt = "now", recordedBy = RecorderInfo("u", "User"),
            components = listOf(FundRecordComponent("c", FundRecordComponentType.SETTLEMENT, BigDecimal("20"))),
            finalSettlementPaths = listOf(
                FinalSettlementPath(1, 1, alice, bob, BigDecimal("20"), FundRecordComponentType.SETTLEMENT),
                FinalSettlementPath(1, 2, bob, carol, BigDecimal("20"), FundRecordComponentType.SETTLEMENT),
            ),
        )
        assertEquals(BigDecimal("20"), record.finalSettlementPathSummaries.single().endpointAmount)
        assertEquals(2, record.finalSettlementPathSummaries.single().hopCount)
    }

    @Test
    fun voidRequiresReasonAndStoresVoidMetadataWithoutRestoreApi() {
        val actor = RecorderInfo("u", "测试记录人")
        val repository = FakeFinancialRecordRepository(actorContext = FakeActorContext(actor = actor, participantIds = setOf("fake-alice")))
        val blank = repository.void("fake-preview-activity", "fake-settlement-001", " ")
        assertFalse(blank.isSuccess)
        val result = repository.void("fake-preview-activity", "fake-settlement-001", "重复录入")
        assertTrue(result.isSuccess)
        assertTrue(result.requiresRefresh)
        assertEquals("重复录入", result.value!!.voidMetadata!!.reason)
        val read = repository.get("fake-preview-activity", "fake-settlement-001")
        assertTrue(read is FinancialReadResult.Success && read.value.isVoided)
    }

    @Test
    fun disputesAreDerivedFromUnresolvedRowsAndResolveByDisputeId() {
        val actor = RecorderInfo("u", "测试记录人")
        val repository = FakeFinancialRecordRepository(actorContext = FakeActorContext(actor = actor, participantIds = setOf("fake-alice")))
        val added = repository.addDispute("fake-preview-activity", "fake-settlement-001", "fake-alice", "金额需要核对")
        assertTrue(added.isSuccess)
        assertTrue(added.requiresRefresh)
        val disputeId = added.value!!.disputeId
        val before = repository.get("fake-preview-activity", "fake-settlement-001") as FinancialReadResult.Success
        assertEquals(1, before.value.unresolvedDisputes.size)
        val resolved = repository.resolveDispute("fake-preview-activity", disputeId)
        assertTrue(resolved.isSuccess)
        val after = repository.get("fake-preview-activity", "fake-settlement-001") as FinancialReadResult.Success
        assertTrue(after.value.disputes.single().isResolved)
        assertTrue(after.value.unresolvedDisputes.isEmpty())
    }

    @Test
    fun fakeRepositoryListsAndGetsFourClearlyFakeSamples() {
        val repository = FakeFinancialRecordRepository()
        val all = repository.list("fake-preview-activity") as FinancialReadResult.Success
        assertEquals(4, all.value.size)
        assertEquals(setOf(FundRecordType.SETTLEMENT, FundRecordType.PREPAYMENT, FundRecordType.PREPAYMENT_RETURN, FundRecordType.FINAL_SETTLEMENT), all.value.map { it.type }.toSet())
        val filtered = repository.list("fake-preview-activity", FundRecordType.PREPAYMENT) as FinancialReadResult.Success
        assertEquals(listOf("fake-prepayment-001"), filtered.value.map { it.transferId })
        assertNotNull((repository.get("fake-preview-activity", "fake-final-001") as FinancialReadResult.Success).value)
    }

    @Test
    fun createStoresReturnedTransferWithoutLedgerUnitBackendField() {
        val repository = FakeFinancialRecordRepository()
        val record = FundRecord(
            transferId = "created-transfer",
            activityId = "created-activity",
            from = ParticipantInfo("from", "From"),
            to = ParticipantInfo("to", "To"),
            type = FundRecordType.SETTLEMENT,
            amount = BigDecimal("10.00"),
            currency = "CNY",
            occurredAt = "now",
            recordedAt = "now",
            recordedBy = RecorderInfo("actor", "Actor"),
            components = listOf(
                FundRecordComponent("component", FundRecordComponentType.SETTLEMENT, BigDecimal("10.00")),
            ),
        )
        val created = repository.create(record)
        assertTrue(created.isSuccess)
        assertEquals(record, (repository.get("created-activity", "created-transfer") as FinancialReadResult.Success).value)
        assertEquals(1, (repository.list("created-activity") as FinancialReadResult.Success).value.size)
    }

    @Test
    fun fakeCreateRejectsNonPositiveAmountAndInvalidComponents() {
        val repository = FakeFinancialRecordRepository(initialRecords = emptyList())
        val base = FundRecord(
            transferId = "boundary-transfer",
            activityId = "boundary-activity",
            from = ParticipantInfo("from", "From"),
            to = ParticipantInfo("to", "To"),
            type = FundRecordType.SETTLEMENT,
            amount = BigDecimal("10"),
            currency = "CNY",
            occurredAt = "now",
            recordedAt = "now",
            recordedBy = RecorderInfo("actor", "Actor"),
            components = listOf(FundRecordComponent("component", FundRecordComponentType.SETTLEMENT, BigDecimal("10"))),
        )
        assertFalse(repository.create(base.copy(amount = BigDecimal.ZERO)).isSuccess)
        assertFalse(repository.create(base.copy(components = listOf(FundRecordComponent("component", FundRecordComponentType.SETTLEMENT, BigDecimal("9"))))).isSuccess)
        assertTrue(repository.create(base).isSuccess)
    }

    @Test
    fun fakePermissionsComeFromInjectedActorContextAndDisputesKeepAuditActor() {
        val actor = RecorderInfo("member", "普通成员")
        val memberRepository = FakeFinancialRecordRepository(
            actorContext = FakeActorContext(actor = actor, role = FakeActorRole.MEMBER, participantIds = setOf("fake-alice")),
        )
        assertFalse(memberRepository.void("fake-preview-activity", "fake-settlement-001", "需要更正").isSuccess)

        val admin = RecorderInfo("admin", "管理员")
        val repository = FakeFinancialRecordRepository(
            actorContext = FakeActorContext(actor = admin, role = FakeActorRole.ADMIN, participantIds = setOf("fake-alice")),
        )
        val added = repository.addDispute("fake-preview-activity", "fake-settlement-001", "fake-alice", "请核对")
        assertTrue(added.isSuccess)
        assertEquals("管理员", added.value!!.disputedBy.displayName)
        assertFalse(repository.addDispute("fake-preview-activity", "fake-settlement-001", "stranger", "请核对").isSuccess)
        assertTrue(repository.void("fake-preview-activity", "fake-settlement-001", "已确认错误").isSuccess)
        assertFalse(repository.addDispute("fake-preview-activity", "fake-settlement-001", "fake-alice", "不能新增").isSuccess)
    }

    @Test
    fun recipientCanOpenDisputeAndAuditParticipantIsNotForcedToFromSide() {
        val actor = RecorderInfo("recipient", "收款方成员")
        val repository = FakeFinancialRecordRepository(
            actorContext = FakeActorContext(
                actor = actor,
                role = FakeActorRole.MEMBER,
                participantIds = setOf("fake-bob"),
            ),
        )

        val result = repository.addDispute(
            activityId = "fake-preview-activity",
            transferId = "fake-settlement-001",
            participantId = "fake-bob",
            note = "收款金额需要核对",
        )

        assertTrue(result.isSuccess)
        assertEquals("fake-bob", result.value!!.participant.participantId)
        assertEquals(actor, result.value!!.disputedBy)
    }

    @Test
    fun memberMayVoidOnlyWhenInjectedActorIsTheRecorder() {
        val actor = RecorderInfo("fake-user", "原记录人")
        val repository = FakeFinancialRecordRepository(
            actorContext = FakeActorContext(
                actor = actor,
                role = FakeActorRole.MEMBER,
                participantIds = setOf("fake-alice"),
            ),
        )

        assertTrue(repository.void("fake-preview-activity", "fake-settlement-001", "重复录入").isSuccess)
    }
}
