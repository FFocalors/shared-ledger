package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal
import java.io.IOException
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TransferPayloadTest {
    @Test
    fun targetedPayloadCarriesModeTargetsAndVersion() {
        val payload = SettlementRpcPayloadBuilder.createTargeted(
            input().copy(
                allocationMode = SettlementAllocationMode.TARGETED,
                targetExpenseIds = listOf("expense-1", "expense-2"),
                expectedFinancialVersion = 12L,
            ),
        )

        assertEquals("TARGETED", payload["mode"]?.jsonPrimitive?.content)
        assertEquals(
            listOf("expense-1", "expense-2"),
            payload["target_expense_ids"]?.jsonArray?.map { it.jsonPrimitive.content },
        )
        assertEquals("12", payload["expected_financial_version"]?.jsonPrimitive?.content)
    }

    @Test
    fun payloadUsesImmutableDebtEndpointsAndNullOnBehalf() {
        val transfer = SettlementRpcPayloadBuilder.create(input())

        assertEquals("activity-1", transfer["activity_id"]?.jsonPrimitive?.content)
        assertEquals("debtor", transfer["from_participant_id"]?.jsonPrimitive?.content)
        assertEquals("creditor", transfer["to_participant_id"]?.jsonPrimitive?.content)
        assertEquals("10.5", transfer["amount"]?.jsonPrimitive?.content)
        assertEquals("USD", transfer["currency"]?.jsonPrimitive?.content)
        assertEquals("2026-09-06T00:00:00Z", transfer["occurred_at"]?.jsonPrimitive?.content)
        assertEquals(JsonNull, transfer["on_behalf_of_participant_id"])
        assertEquals("request-1", transfer["request_id"]?.jsonPrimitive?.content)
    }

    @Test
    fun payloadPreservesCreatorOnBehalfParticipant() {
        val payload = SettlementRpcPayloadBuilder.create(
            input().copy(onBehalfOfParticipantId = "unclaimed-debtor"),
        )

        assertEquals("unclaimed-debtor", payload["on_behalf_of_participant_id"]?.jsonPrimitive?.content)
    }

    @Test
    fun legacyPayloadOmitsNewCurrencyAndReplayFields() {
        val payload = SettlementRpcPayloadBuilder.createLegacy(input())

        assertEquals(null, payload["currency"])
        assertEquals(null, payload["request_id"])
        assertEquals("10.5", payload["amount"]?.jsonPrimitive?.content)
        assertEquals("2026-09-06T00:00:00Z", payload["occurred_at"]?.jsonPrimitive?.content)
    }

    @Test
    fun onBehalfMetadataCannotRewriteDebtEndpoints() {
        val payload = SettlementRpcPayloadBuilder.create(
            input().copy(onBehalfOfParticipantId = "debtor"),
        )

        assertEquals("debtor", payload["from_participant_id"]?.jsonPrimitive?.content)
        assertEquals("creditor", payload["to_participant_id"]?.jsonPrimitive?.content)
        assertEquals("debtor", payload["on_behalf_of_participant_id"]?.jsonPrimitive?.content)
    }

    @Test
    fun writeOutcomeSeparatesTransportUnknownFromBusinessFailure() {
        val unknown = Result.failure<SettlementTransferResult>(
            TransferOperationException("network", IOException("request timeout")),
        ).toTransferWriteResult()
        val failed = Result.failure<SettlementTransferResult>(RuntimeException("code=40001")).toTransferWriteResult()

        assertEquals(TransferWriteState.UNKNOWN, unknown.state)
        assertTrue(unknown.isUnknown)
        assertEquals(TransferWriteState.FAILED, failed.state)
        assertFalse(failed.isUnknown)
        assertEquals("数据刚刚发生变化，请刷新债务后重试", TransferErrorMapper.toUserMessage(RuntimeException("code=40001")))
    }

    private fun input() = CreateSettlementTransferInput(
        activityId = "activity-1",
        fromParticipantId = "debtor",
        toParticipantId = "creditor",
        amount = BigDecimal("10.5"),
        occurredAt = "2026-09-06T00:00:00Z",
        currency = "USD",
        requestId = "request-1",
    )
}
