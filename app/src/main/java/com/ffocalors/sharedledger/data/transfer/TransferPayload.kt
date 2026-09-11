package com.ffocalors.sharedledger.data.transfer

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal object SettlementRpcPayloadBuilder {
    fun create(input: CreateSettlementTransferInput) = buildJsonObject {
        put("activity_id", input.activityId)
        put("from_participant_id", input.fromParticipantId)
        put("to_participant_id", input.toParticipantId)
        put("amount", input.amount.toPlainString())
        put("occurred_at", input.occurredAt)
        if (input.onBehalfOfParticipantId == null) {
            put("on_behalf_of_participant_id", JsonNull)
        } else {
            put("on_behalf_of_participant_id", input.onBehalfOfParticipantId)
        }
    }
}
