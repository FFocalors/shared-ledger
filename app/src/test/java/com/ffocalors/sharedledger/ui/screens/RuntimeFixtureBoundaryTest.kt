package com.ffocalors.sharedledger.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RuntimeFixtureBoundaryTest {
    @Test
    fun runtimeFacingStateDefaultsDoNotCarryPreviewIdentityOrData() {
        val expense = ExpenseDetailUiState()
        val transfer = TransferDetailUiState()
        val management = ActivityManagementUiState()

        assertEquals("", expense.expenseId)
        assertTrue(expense.splits.isEmpty())
        assertEquals("", transfer.activityId)
        assertEquals("", transfer.transferId)
        assertTrue(management.participants.isEmpty())
        assertTrue(management.members.isEmpty())
    }
}
