package com.ffocalors.sharedledger.ui.screens

import java.math.BigDecimal
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FinalSettlementRequestTest {
    @Test
    fun requestCarriesConcreteParticipantsAmountsCurrencyAndSourceVersion() {
        val request = FinalSettlementRequest(
            activityId = "activity-1",
            previewItemId = "preview-1",
            fromParticipantId = "member-a",
            toParticipantId = "member-b",
            amount = BigDecimal("320.00"),
            currency = "CNY",
            ordinaryAmount = BigDecimal("200.00"),
            prepaymentReturnAmount = BigDecimal("120.00"),
            sourceFinancialVersion = 7L,
        )
        assertTrue(request.isValid())
        assertFalse(request.copy(amount = BigDecimal("319.00")).isValid())
        assertFalse(request.copy(sourceFinancialVersion = 0L).isValid())
        assertFalse(request.copy(currency = "cny").isValid())
    }

    @Test
    fun expenseRouteDemoKeepsDeletedAndActiveStatesDistinct() {
        assertTrue(demoExpenseDetailUiState("demo-expense-dinner").status == ExpenseDetailStatus.Deleted)
        assertTrue(demoExpenseDetailUiState("demo-expense-taxi").status == ExpenseDetailStatus.Active)
    }
}
