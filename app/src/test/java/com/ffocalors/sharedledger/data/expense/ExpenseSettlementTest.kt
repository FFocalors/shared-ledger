package com.ffocalors.sharedledger.data.expense

import com.ffocalors.sharedledger.ui.expense.toUiState
import java.math.BigDecimal
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ExpenseSettlementTest {
    @Test
    fun settlementProjectionCombinesAllocationAndPrepaymentUsage() {
        val settlements = ExpenseDtoMappers.debtSettlements(
            debts = listOf(
                ExpenseDebtRowDto("debt-1", "debtor-1", JsonPrimitive("50.0")),
                ExpenseDebtRowDto("debt-2", "debtor-2", JsonPrimitive("50.0")),
            ),
            allocations = listOf(TransferAllocationRowDto("debt-2", JsonPrimitive("20.0"))),
            usages = listOf(PrepaymentUsageRowDto("debt-1", JsonPrimitive("50.0"))),
        )

        assertEquals(BigDecimal("0.0"), settlements.first().remainingAmount)
        assertEquals(BigDecimal("30.0"), settlements[1].remainingAmount)
    }

    @Test
    fun detailUiMarksUsageCoveredAndNoDebtParticipantsPaid() {
        val detail = ExpenseDetail(
            expense = Expense(
                id = "expense-1", ledgerUnitId = "ledger-1", title = "午餐",
                originalAmount = BigDecimal("100"), originalCurrency = "CNY", fxRate = BigDecimal.ONE,
                baseAmount = BigDecimal("100"), splitMethod = ExpenseSplitMethod.Manual,
                occurredAt = "2026-09-07T04:00:00Z", note = null, originalExpenseId = null,
                createdBy = "user", updatedBy = "user", createdAt = null, updatedAt = null,
                version = 1, isDeleted = false,
            ),
            ledgerUnit = ExpenseLedgerUnit("ledger-1", "activity-1", "账本", "default"),
            baseCurrency = "CNY",
            payments = listOf(Payment("payment-1", "expense-1", "payer", BigDecimal("100"), null)),
            splits = listOf(
                Split("split-1", "expense-1", "debtor", BigDecimal("50"), null),
                Split("split-2", "expense-1", "payer", BigDecimal("50"), null),
            ),
            participants = listOf(
                ExpenseParticipant("debtor", "activity-1", "欠款人", 0),
                ExpenseParticipant("payer", "activity-1", "付款人", 1),
            ),
            debtSettlements = listOf(
                ExpenseDebtSettlement("debt-1", "debtor", BigDecimal("50"), BigDecimal("50")),
            ),
        )

        val states = detail.toUiState().splits.associateBy { it.participant }
        assertEquals("Paid", states.getValue("欠款人").settlement.name)
        assertEquals("Paid", states.getValue("付款人").settlement.name)
        assertTrue(states.values.all { it.owedAmount == "50" })
    }
}
