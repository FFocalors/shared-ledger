package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FinancialMappersTest {
    @Test
    fun aggregatesCurrentUsageByAccountWithoutChangingRawTransferAmount() {
        val usage = aggregatePrepaymentUsageAmounts(
            listOf(
                FinancialPrepaymentUsageRowDto("u1", "account-1", JsonPrimitive("60")),
                FinancialPrepaymentUsageRowDto("u2", "account-1", JsonPrimitive("40")),
                FinancialPrepaymentUsageRowDto("u3", "account-2", JsonPrimitive("5")),
            ),
        )

        assertEquals(BigDecimal("100"), usage["account-1"])
        assertEquals(BigDecimal("5"), usage["account-2"])
    }

    @Test
    fun mapsTransferComponentsVoidAndDisputeMetadataFromFrozenRows() {
        val transfer = Json.decodeFromString<FinancialTransferRowDto>("""
            {"id":"t1","activity_id":"a1","from_participant_id":"p1","to_participant_id":"p2","type":"prepayment","amount":"100.0","currency":"CNY","occurred_at":"2026-09-06T10:00:00Z","recorded_by":"u1","on_behalf_of_participant_id":"p1","created_at":"2026-09-06T10:01:00Z","is_voided":true,"voided_at":"2026-09-06T10:02:00Z","voided_by":"u2","void_reason":"重复记录"}
        """.trimIndent())
        val record = mapFinancialRecord(
            transfer = transfer,
            participants = mapOf("p1" to FinancialParticipantRowDto("p1", "张三").toParticipant(), "p2" to FinancialParticipantRowDto("p2", "李四").toParticipant()),
            profiles = mapOf("u1" to FinancialProfileRowDto("u1", "记录人").toRecorder(), "u2" to FinancialProfileRowDto("u2", "作废人").toRecorder()),
            components = listOf(
                FinancialComponentRowDto("c1", "t1", "settlement", JsonPrimitive("40")),
                FinancialComponentRowDto("c2", "t1", "prepayment", JsonPrimitive("60")),
            ),
            disputes = emptyList(),
            paths = emptyList(),
        )

        assertEquals(FundRecordType.PREPAYMENT, record.type)
        assertEquals(listOf(FundRecordComponentType.SETTLEMENT, FundRecordComponentType.PREPAYMENT), record.components.map { it.type })
        assertTrue(record.isVoided)
        assertEquals("重复记录", record.voidMetadata?.reason)
        assertEquals("记录人", record.recordedBy.displayName)
        assertEquals("张三", record.onBehalfOf?.displayName)
    }

    @Test
    fun mapsPrepaymentUsageToReadOnlyTimelineRecordAtExpenseTime() {
        val record = mapPrepaymentUsageRecord(
            usage = FinancialPrepaymentUsageRowDto("usage-1", "account-1", JsonPrimitive("50.0"), "debt-1", "2026-09-07T04:01:00Z"),
            account = FinancialAccountRowDto("account-1", "activity-1", "owner", "custodian", JsonPrimitive("50.0")),
            debt = FinancialExpenseDebtRowDto("debt-1", "expense-1"),
            expense = FinancialExpenseTimelineRowDto("expense-1", "午餐", "2026-09-07T04:00:41Z"),
            participants = mapOf("owner" to ParticipantInfo("owner", "Owner"), "custodian" to ParticipantInfo("custodian", "Custodian")),
            currency = "CNY",
        )!!

        assertEquals("usage:owner:custodian:debt-1", record.transferId)
        assertEquals(FundRecordType.AUTO_PREPAYMENT_USAGE, record.type)
        assertEquals("2026-09-07T04:00:41Z", record.occurredAt)
        assertEquals("午餐", record.sourceExpenseTitle)
        assertTrue(record.isReadOnly)
    }
}
