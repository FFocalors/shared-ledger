package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal
import java.io.IOException
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TransferPayloadTest {
    @Test
    fun payloadUsesDirectionAndNullOnBehalf() {
        val transfer = SettlementRpcPayloadBuilder.create(input(SettlementDirection.TRANSFER))
        val receive = SettlementRpcPayloadBuilder.create(input(SettlementDirection.RECEIVE))

        assertEquals("activity-1", transfer["activity_id"]?.jsonPrimitive?.content)
        assertEquals("debtor", transfer["from_participant_id"]?.jsonPrimitive?.content)
        assertEquals("creditor", transfer["to_participant_id"]?.jsonPrimitive?.content)
        assertEquals("creditor", receive["from_participant_id"]?.jsonPrimitive?.content)
        assertEquals("debtor", receive["to_participant_id"]?.jsonPrimitive?.content)
        assertEquals("10.5", transfer["amount"]?.jsonPrimitive?.content)
        assertEquals("2026-09-06T00:00:00Z", transfer["occurred_at"]?.jsonPrimitive?.content)
        assertEquals(JsonNull, transfer["on_behalf_of_participant_id"])
    }

    @Test
    fun payloadPreservesCreatorOnBehalfParticipant() {
        val payload = SettlementRpcPayloadBuilder.create(
            input(SettlementDirection.TRANSFER).copy(onBehalfOfParticipantId = "unclaimed-debtor"),
        )

        assertEquals("unclaimed-debtor", payload["on_behalf_of_participant_id"]?.jsonPrimitive?.content)
    }

    @Test
    fun receivePayloadKeepsDebtorToCreditorEndpointsForUnboundCreator() {
        val payload = SettlementRpcPayloadBuilder.create(
            input(SettlementDirection.RECEIVE).copy(
                currentParticipantId = "creditor",
                selectedParticipantId = "debtor",
            ),
        )

        assertEquals("debtor", payload["from_participant_id"]?.jsonPrimitive?.content)
        assertEquals("creditor", payload["to_participant_id"]?.jsonPrimitive?.content)
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

    private fun input(direction: SettlementDirection) = CreateSettlementTransferInput(
        activityId = "activity-1",
        currentParticipantId = "debtor",
        selectedParticipantId = "creditor",
        amount = BigDecimal("10.5"),
        direction = direction,
        occurredAt = "2026-09-06T00:00:00Z",
    )
}
