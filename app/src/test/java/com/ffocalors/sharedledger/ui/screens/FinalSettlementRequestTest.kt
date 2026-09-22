package com.ffocalors.sharedledger.ui.screens

import java.math.BigDecimal
import com.ffocalors.sharedledger.data.financial.FinalSettlementMode
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import org.junit.Assert.assertEquals
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
        assertFalse(request.copy(amount = BigDecimal.ZERO).isValid())
        assertFalse(request.copy(sourceFinancialVersion = -1L).isValid())
        assertFalse(request.copy(currency = "cny").isValid())
    }

    @Test
    fun requestDoesNotRejectDisplayOnlyComponentAmounts() {
        val request = FinalSettlementRequest(
            activityId = "activity-1",
            previewItemId = "preview-1",
            fromParticipantId = "member-a",
            toParticipantId = "member-b",
            amount = BigDecimal("47.2000"),
            currency = "EUR",
            ordinaryAmount = BigDecimal.ZERO,
            prepaymentReturnAmount = BigDecimal.ZERO,
            sourceFinancialVersion = 7L,
        )

        assertTrue(request.isValid())
    }

    @Test
    fun requestKeepsClickSnapshotForScopeAndModeValidation() {
        val request = FinalSettlementRequest(
            activityId = "activity-1",
            previewItemId = "preview-1",
            fromParticipantId = "member-a",
            toParticipantId = "member-b",
            fromParticipantName = "Alice",
            toParticipantName = "Bob",
            amount = BigDecimal("10.00"),
            currency = "CNY",
            ordinaryAmount = BigDecimal("10.00"),
            prepaymentReturnAmount = BigDecimal.ZERO,
            sourceFinancialVersion = 7L,
        )

        assertEquals("Alice", request.fromParticipantName)
        assertEquals("Bob", request.toParticipantName)
        assertTrue(request.matchesSettlementScope("activity-1", FinalSettlementMode.BASE_UNIFIED))
        assertFalse(request.matchesSettlementScope("activity-1", FinalSettlementMode.ORIGINAL_CURRENCY))
    }

    @Test
    fun finalSettlementPresentationNamesBothTransferPartiesAndExplainsNetting() {
        val suggestion = FinalSettlementSuggestionUi(
            id = "whr-to-zhy",
            fromParticipantId = "whr-id",
            toParticipantId = "zhy-id",
            from = ParticipantUiModel("whr"),
            to = ParticipantUiModel("zhy"),
            amount = BigDecimal("95.9"),
            currency = "CNY",
            ordinaryAmount = BigDecimal("95.9"),
            prepaymentReturnAmount = BigDecimal.ZERO,
            sourceFinancialVersion = 6L,
        )

        assertEquals("whr → zhy", suggestion.directionLabel())
        assertEquals("whr 向 zhy 转账", suggestion.paymentInstruction())
        assertTrue(FinalSettlementPlanExplanation.contains("净应收、净应付"))
    }

    @Test
    fun expenseRouteDemoKeepsDeletedAndActiveStatesDistinct() {
        assertTrue(demoExpenseDetailUiState("demo-expense-dinner").status == ExpenseDetailStatus.Deleted)
        assertTrue(demoExpenseDetailUiState("demo-expense-taxi").status == ExpenseDetailStatus.Active)
    }
}
