package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.domain.financial.FundRecordType
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FinancialRecordRepositoryTest {
    @Test
    fun listAllExposesOneSnapshotThatCanBeFilteredLocally() = runTest {
        val result = FakeFinancialRecordRepository().listAll("fake-preview-activity")

        assertTrue(result is FinancialReadResult.Success)
        val records = (result as FinancialReadResult.Success).value
        assertEquals(4, records.size)
        assertEquals(1, records.count { it.type == FundRecordType.FINAL_SETTLEMENT })
        assertEquals(
            1,
            records.filter { it.type == FundRecordType.PREPAYMENT_RETURN }.size,
        )
    }
}
