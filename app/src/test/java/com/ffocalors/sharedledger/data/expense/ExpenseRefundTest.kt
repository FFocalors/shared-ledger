package com.ffocalors.sharedledger.data.expense

import org.junit.Assert.assertEquals
import org.junit.Test
import java.math.BigDecimal

class ExpenseRefundTest {
    @Test
    fun refundInputNormalizesExpensePaymentsAndSplitsToNegative() {
        val refund = RefundExpenseInput(
            ledgerUnitId = "unit",
            title = "Refund",
            amount = BigDecimal("100.00"),
            originalCurrency = "CNY",
            fxRate = BigDecimal.ONE,
            splitMethod = ExpenseSplitMethod.Manual,
            payments = listOf(PaymentInput("payer", BigDecimal("100.00"))),
            manualSplits = listOf(ManualSplitInput("owner", BigDecimal("100.00"))),
            occurredAt = "2026-09-05T12:00:00Z",
        )

        val input = refund.toCreateInput("original-expense")
        assertEquals(BigDecimal("-100.00"), input.originalAmount)
        assertEquals(BigDecimal("-100.00"), input.payments.single().amount)
        assertEquals(BigDecimal("-100.00"), input.manualSplits.single().amount)
        assertEquals("original-expense", input.originalExpenseId)
    }

    @Test
    fun alreadyNegativeRefundRemainsNegative() {
        val input = RefundExpenseInput(
            ledgerUnitId = "unit", title = "Refund", amount = BigDecimal("-12.50"),
            originalCurrency = "CNY", fxRate = BigDecimal.ONE, splitMethod = ExpenseSplitMethod.Aa,
            payments = listOf(PaymentInput("payer", BigDecimal("12.50"))),
            aaParticipantIds = listOf("owner"), occurredAt = "2026-09-05T12:00:00Z",
        ).toCreateInput("original")

        assertEquals(BigDecimal("-12.50"), input.originalAmount)
        assertEquals(BigDecimal("-12.50"), input.payments.single().amount)
    }
}
