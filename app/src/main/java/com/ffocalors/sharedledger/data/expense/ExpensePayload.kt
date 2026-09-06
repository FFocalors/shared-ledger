package com.ffocalors.sharedledger.data.expense

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal

object ExpenseRpcPayloadBuilder {
    fun create(input: CreateExpenseInput) = inputPayload(input)

    fun update(input: UpdateExpenseInput) = inputPayload(
        input = CreateExpenseInput(
            ledgerUnitId = input.ledgerUnitId,
            title = input.title,
            originalAmount = input.originalAmount,
            originalCurrency = input.originalCurrency,
            fxRate = input.fxRate,
            splitMethod = input.splitMethod,
            payments = input.payments,
            manualSplits = input.manualSplits,
            aaParticipantIds = input.aaParticipantIds,
            occurredAt = input.occurredAt,
            note = input.note,
            originalExpenseId = input.originalExpenseId,
        ),
        expenseId = input.expenseId,
    )

    private fun inputPayload(input: CreateExpenseInput, expenseId: String? = null) = buildJsonObject {
        expenseId?.let { put("expense_id", it) }
        put("ledger_unit_id", input.ledgerUnitId)
        put("title", input.title)
        put("original_amount", decimal(input.originalAmount))
        put("original_currency", input.originalCurrency.trim().uppercase())
        put("fx_rate", decimal(input.fxRate))
        put("split_method", input.splitMethod.backendValue)
        put("payments", input.payments.toPaymentJsonArray())
        put("manual_splits", input.manualSplits.toSplitJsonArray())
        put("aa_participant_ids", input.aaParticipantIds.toIdJsonArray())
        put("occurred_at", input.occurredAt)
        input.note?.let { put("note", it) } ?: put("note", JsonNull)
        input.originalExpenseId?.let { put("original_expense_id", it) } ?: put("original_expense_id", JsonNull)
    }

    private fun List<PaymentInput>.toPaymentJsonArray(): JsonArray = buildJsonArray {
        for (item in this@toPaymentJsonArray) add(buildJsonObject {
            put("participant_id", item.participantId)
            put("amount", decimal(item.amount))
        })
    }

    private fun List<ManualSplitInput>.toSplitJsonArray(): JsonArray = buildJsonArray {
        for (item in this@toSplitJsonArray) add(buildJsonObject {
            put("participant_id", item.participantId)
            put("amount", decimal(item.amount))
        })
    }

    private fun List<String>.toIdJsonArray(): JsonArray = buildJsonArray {
        for (item in this@toIdJsonArray) add(JsonPrimitive(item))
    }

    private fun decimal(value: BigDecimal): JsonPrimitive = JsonPrimitive(value.toPlainString())
}
