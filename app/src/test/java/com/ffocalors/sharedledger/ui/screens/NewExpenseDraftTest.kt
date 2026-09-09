package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.ui.expense.ExpenseFormParticipant
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Test

class NewExpenseDraftTest {
    @Test
    fun defaultDraftUsesCurrentBoundParticipantAsPayer() {
        val participants = listOf(
            ExpenseFormParticipant("other", "其他人"),
            ExpenseFormParticipant("current", "当前账号"),
        )

        val draft = createDefaultExpenseDraft(
            ledgerUnitId = "unit",
            participants = participants,
            baseCurrency = "CNY",
            defaultPayerParticipantId = "current",
        )

        assertEquals(listOf("current"), draft.payerIds)
        assertEquals("300.0", draft.payerAmounts["current"])
    }

    @Test
    fun integerTotalNormalizesAutomaticPayerAmountToOneDecimal() {
        assertEquals("300.0", normalizedAutoPayerAmount("300"))
        assertEquals("300.25", normalizedAutoPayerAmount("300.25"))
    }

    @Test
    fun linkedRefundKeepsOriginalPayerRatioAndExactTotal() {
        val allocated = allocateRefundPayerAmounts(
            totalValue = "50",
            payerIds = listOf("payer-a", "payer-b"),
            payerWeights = mapOf("payer-a" to "200", "payer-b" to "100"),
        )

        assertEquals(BigDecimal("50.0000"), allocated.values.sumOf { it.toBigDecimal() })
        assertEquals("33.3333", allocated["payer-a"])
        assertEquals("16.6667", allocated["payer-b"])
    }
}
