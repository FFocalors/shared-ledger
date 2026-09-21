package com.ffocalors.sharedledger.data.financial

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FinancialRequestStoreTest {
    @Test
    fun pendingFinancialRequestsReuseOnlyAnIdenticalPayload() = runBlocking {
        val store = InMemoryFinancialRequestStore()
        val firstPayload = "activity|pair|100.00|USD|v7"
        val first = PendingFinancialRequest(
            requestId = "request-1",
            activityId = "activity-1",
            operationKey = "prepayment:create",
            payloadFingerprint = financialPayloadFingerprint(firstPayload),
            payload = firstPayload,
        )
        store.upsert("user-1", first)

        val same = store.read("user-1", "activity-1", "prepayment:create")
            .single()
        assertEquals(first.requestId, same.requestId)
        assertEquals(first.payloadFingerprint, same.payloadFingerprint)

        val changedPayload = "activity|pair|101.00|USD|v7"
        assertNotEquals(first.payloadFingerprint, financialPayloadFingerprint(changedPayload))
        assertTrue(store.read("user-1", "activity-1", "prepayment:return").isEmpty())
    }
}
