package com.ffocalors.sharedledger.data.transfer

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.add

internal object SettlementRpcPayloadBuilder {
    fun create(input: CreateSettlementTransferInput) = buildJsonObject {
        put("activity_id", input.activityId)
        put("from_participant_id", input.fromParticipantId)
        put("to_participant_id", input.toParticipantId)
        put("amount", input.amount.toPlainString())
        put("currency", input.currency.trim().uppercase())
        put("occurred_at", input.occurredAt)
        if (input.onBehalfOfParticipantId == null) {
            put("on_behalf_of_participant_id", JsonNull)
        } else {
            put("on_behalf_of_participant_id", input.onBehalfOfParticipantId)
        }
        if (input.requestId == null) {
            put("request_id", JsonNull)
        } else {
            put("request_id", input.requestId)
        }
        put("allocation_mode", input.allocationMode.name)
        put("target_expense_ids", buildJsonArray {
            input.targetExpenseIds.forEach { add(JsonPrimitive(it)) }
        })
        if (input.expectedFinancialVersion == null) {
            put("expected_financial_version", JsonNull)
        } else {
            put("expected_financial_version", input.expectedFinancialVersion)
        }
    }

    /** Payload accepted by the pre-multi-currency six-argument RPC. */
    fun createLegacy(input: CreateSettlementTransferInput) = buildJsonObject {
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

    fun listExpenseCandidates(
        activityId: String,
        fromParticipantId: String,
        toParticipantId: String,
        currency: String,
    ) = buildJsonObject {
        put("activity_id", activityId)
        put("from_participant_id", fromParticipantId)
        put("to_participant_id", toParticipantId)
        put("currency", currency.trim().uppercase())
    }

    fun preview(input: PreviewSettlementInput) = buildJsonObject {
        put("activity_id", input.activityId)
        put("from_participant_id", input.fromParticipantId)
        put("to_participant_id", input.toParticipantId)
        put("amount", input.amount.toPlainString())
        put("currency", input.currency.trim().uppercase())
        put("mode", input.allocationMode.name)
        put("target_expense_ids", buildJsonArray { input.targetExpenseIds.forEach { add(JsonPrimitive(it)) } })
        if (input.expectedFinancialVersion == null) put("expected_financial_version", JsonNull)
        else put("expected_financial_version", input.expectedFinancialVersion)
    }

    fun createTargeted(input: CreateSettlementTransferInput) = buildJsonObject {
        put("activity_id", input.activityId)
        put("from_participant_id", input.fromParticipantId)
        put("to_participant_id", input.toParticipantId)
        put("amount", input.amount.toPlainString())
        put("currency", input.currency.trim().uppercase())
        put("mode", input.allocationMode.name)
        put("target_expense_ids", buildJsonArray { input.targetExpenseIds.forEach { add(JsonPrimitive(it)) } })
        put("occurred_at", input.occurredAt)
        if (input.onBehalfOfParticipantId == null) put("on_behalf_of_participant_id", JsonNull)
        else put("on_behalf_of_participant_id", input.onBehalfOfParticipantId)
        if (input.expectedFinancialVersion == null) put("expected_financial_version", JsonNull)
        else put("expected_financial_version", input.expectedFinancialVersion)
        if (input.requestId == null) put("request_id", JsonNull)
        else put("request_id", input.requestId)
    }
}
