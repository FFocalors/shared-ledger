package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
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

    private fun input(direction: SettlementDirection) = CreateSettlementTransferInput(
        activityId = "activity-1",
        currentParticipantId = "debtor",
        selectedParticipantId = "creditor",
        amount = BigDecimal("10.5"),
        direction = direction,
        occurredAt = "2026-09-06T00:00:00Z",
    )
}
