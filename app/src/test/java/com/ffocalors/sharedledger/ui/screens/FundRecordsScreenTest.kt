package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Test

class FundRecordsScreenTest {
    private val participant = ParticipantInfo("participant", "参与人")
    private val recorder = RecorderInfo("recorder", "记录人")

    @Test
    fun sortFundRecordsSupportsBothTimeDirections() {
        val records = listOf(
            record("older", "2026-09-01T10:00:00Z"),
            record("newer", "2026-09-03T10:00:00Z"),
            record("middle", "2026-09-02T10:00:00Z"),
        )

        assertEquals(
            listOf("newer", "middle", "older"),
            sortFundRecords(records, FundRecordSortOrder.NEWEST_FIRST).map { it.transferId },
        )
        assertEquals(
            listOf("older", "middle", "newer"),
            sortFundRecords(records, FundRecordSortOrder.OLDEST_FIRST).map { it.transferId },
        )
    }

    @Test
    fun sortToggleLabelsMatchTheNextAction() {
        assertEquals(FundRecordSortOrder.OLDEST_FIRST, FundRecordSortOrder.NEWEST_FIRST.toggled())
        assertEquals("切换为时间从旧到新", FundRecordSortOrder.NEWEST_FIRST.nextActionLabel)
        assertEquals(FundRecordSortOrder.NEWEST_FIRST, FundRecordSortOrder.OLDEST_FIRST.toggled())
        assertEquals("切换为时间从新到旧", FundRecordSortOrder.OLDEST_FIRST.nextActionLabel)
    }

    private fun record(id: String, occurredAt: String) = FundRecord(
        transferId = id,
        activityId = "activity",
        from = participant,
        to = participant,
        type = FundRecordType.SETTLEMENT,
        amount = BigDecimal.ONE,
        currency = "CNY",
        occurredAt = occurredAt,
        recordedAt = occurredAt,
        recordedBy = recorder,
    )
}
