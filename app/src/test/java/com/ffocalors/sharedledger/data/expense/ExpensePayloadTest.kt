package com.ffocalors.sharedledger.data.expense

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

class ExpensePayloadTest {
    private val participantA = "00000000-0000-0000-0000-000000000001"
    private val participantB = "00000000-0000-0000-0000-000000000002"

    @Test
    fun createPayloadUsesExactRpcNamesAndDoesNotSendServerProjections() {
        val payload = ExpenseRpcPayloadBuilder.create(
            CreateExpenseInput(
                ledgerUnitId = "00000000-0000-0000-0000-000000000010",
                title = "Dinner",
                originalAmount = BigDecimal("12.3456"),
                originalCurrency = " cny ",
                fxRate = BigDecimal("1.1234567890"),
                splitMethod = ExpenseSplitMethod.Manual,
                payments = listOf(PaymentInput(participantA, BigDecimal("12.3456"))),
                manualSplits = listOf(
                    ManualSplitInput(participantA, BigDecimal("6.0000")),
                    ManualSplitInput(participantB, BigDecimal("6.3456")),
                ),
                occurredAt = "2026-09-05T12:00:00Z",
                note = null,
            ),
        )

        assertEquals(
            setOf(
                "ledger_unit_id", "title", "original_amount", "original_currency", "fx_rate",
                "split_method", "payments", "manual_splits", "aa_participant_ids", "occurred_at",
                "note", "original_expense_id",
            ),
            payload.keys,
        )
        assertEquals("12.3456", payload["original_amount"]!!.jsonPrimitive.content)
        assertEquals("1.1234567890", payload["fx_rate"]!!.jsonPrimitive.content)
        assertEquals("CNY", payload["original_currency"]!!.jsonPrimitive.content)
        assertEquals(JsonNull, payload["note"])
        assertEquals(JsonNull, payload["original_expense_id"])
        assertTrue(payload["aa_participant_ids"]!!.jsonArray.isEmpty())
        assertEquals(setOf("participant_id", "amount"), payload["payments"]!!.jsonArray.single().jsonObject.keys)
        assertFalse(payload.toString().contains("base_amount"))
        assertFalse(payload.toString().contains("expense_debts"))
        assertFalse(payload.toString().contains("bilateral_debts"))
    }

    @Test
    fun aaPayloadHasParticipantIdsAndEmptyManualSplits() {
        val payload = ExpenseRpcPayloadBuilder.create(
            CreateExpenseInput(
                ledgerUnitId = "unit",
                title = "Taxi",
                originalAmount = BigDecimal("10"),
                originalCurrency = "CNY",
                fxRate = BigDecimal.ONE,
                splitMethod = ExpenseSplitMethod.Aa,
                payments = emptyList(),
                aaParticipantIds = listOf(participantA, participantB),
                occurredAt = "2026-09-05T12:00:00Z",
            ),
        )

        assertEquals(listOf(participantA, participantB), payload["aa_participant_ids"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertTrue(payload["manual_splits"]!!.jsonArray.isEmpty())
    }

    @Test
    fun updatePayloadIncludesExpenseId() {
        val expenseId = "00000000-0000-0000-0000-000000000099"
        val payload = ExpenseRpcPayloadBuilder.update(
            UpdateExpenseInput(
                expenseId = expenseId,
                ledgerUnitId = "unit",
                title = "Updated",
                originalAmount = BigDecimal.ONE,
                originalCurrency = "CNY",
                fxRate = BigDecimal.ONE,
                splitMethod = ExpenseSplitMethod.Aa,
                payments = emptyList(),
                aaParticipantIds = listOf(participantA),
                occurredAt = "2026-09-05T12:00:00Z",
            ),
        )

        assertEquals(expenseId, payload["expense_id"]!!.jsonPrimitive.content)
    }
}
