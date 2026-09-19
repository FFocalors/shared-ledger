package com.ffocalors.sharedledger.data.expense

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

class ExpenseDtoTest {
    @Test
    fun dtoDecodesJsonNumberWithoutGoingThroughDouble() {
        val dto = Json.decodeFromString<ExpenseRowDto>(
            """
            {
              "id":"expense-1","ledger_unit_id":"unit-1","title":"Dinner",
              "original_amount":1234567890123456.1234,"original_currency":"CNY",
              "fx_rate":1.0000000001,"base_amount":1234567890123456.1,
              "split_method":"manual","occurred_at":"2026-09-05T12:00:00Z",
              "note":null,"original_expense_id":null,"created_by":"user-1",
              "updated_by":"user-1","created_at":null,"updated_at":null,
              "version":2,"is_deleted":false
            }
            """.trimIndent(),
        )

        val expense = ExpenseDtoMappers.expense(dto)
        assertEquals(BigDecimal("1234567890123456.1234"), expense.originalAmount)
        assertEquals(BigDecimal("1.0000000001"), expense.fxRate)
        assertEquals(BigDecimal("1234567890123456.1"), expense.baseAmount)
        assertFalse(expense.isDeleted)
        assertTrue(expense.hasExpectedDeletionState(false))
        assertFalse(expense.hasExpectedDeletionState(true))
        assertTrue(expense.hasExpectedDeletionState(null))
        assertEquals(ExpenseIconKey.MONEY, expense.iconKey)
    }

    @Test
    fun mapperKeepsSupportedIconAndFallsBackForUnknownData() {
        val base = ExpenseRowDto(
            id = "expense",
            ledgerUnitId = "unit",
            title = "Dinner",
            originalAmount = JsonPrimitive("10"),
            originalCurrency = "CNY",
            fxRate = JsonPrimitive("1"),
            baseAmount = JsonPrimitive("10.0"),
            splitMethod = "aa",
            occurredAt = "2026-09-05T12:00:00Z",
            createdBy = "user",
            updatedBy = "user",
            version = 1,
            iconKey = ExpenseIconKey.DINING,
        )

        assertEquals(ExpenseIconKey.DINING, ExpenseDtoMappers.expense(base).iconKey)
        assertEquals(ExpenseIconKey.MONEY, ExpenseDtoMappers.expense(base.copy(iconKey = "legacy-resource-id")).iconKey)
    }

    @Test
    fun childDtoSupportsQuotedAndNumericAmounts() {
        val payment = PaymentRowDto("pay", "expense", "participant", JsonPrimitive("0.1000"), JsonPrimitive("0.1"))
        val split = SplitRowDto("split", "expense", "participant", JsonPrimitive(0.2000), null)

        assertEquals(BigDecimal("0.1000"), ExpenseDtoMappers.payment(payment).amount)
        assertEquals(BigDecimal("0.1"), ExpenseDtoMappers.payment(payment).baseAmount)
        assertEquals(BigDecimal("0.2"), ExpenseDtoMappers.split(split).amount)
        assertNull(ExpenseDtoMappers.split(split).baseAmount)
    }

    @Test
    fun mapperPreservesLedgerUnitAndParticipantContext() {
        val unit = ExpenseDtoMappers.ledgerUnit(ExpenseLedgerUnitRowDto("unit", "activity", "Trip", "sub_activity"))
        val participant = ExpenseDtoMappers.participant(
            ExpenseParticipantRowDto("participant", "activity", "Alice", 3),
        )

        assertEquals("activity", unit.activityId)
        assertEquals("sub_activity", unit.type)
        assertEquals(3, participant.order)
        assertEquals("Alice", participant.name)
    }

    @Test
    fun activityCurrencyDtoMapsNormalizedBaseCurrency() {
        val dto = Json.decodeFromString<ExpenseActivityCurrencyRowDto>("""{"base_currency":"eur"}""")

        assertEquals("EUR", ExpenseDtoMappers.baseCurrency(dto))
    }
}
