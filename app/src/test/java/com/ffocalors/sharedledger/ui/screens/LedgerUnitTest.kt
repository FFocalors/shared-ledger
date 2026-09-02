package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.ui.demo.DemoRouteIds
import org.junit.Assert.assertEquals
import org.junit.Test

class LedgerUnitTest {
    @Test
    fun demoLedgerUnitIdSelectsTheMatchingSubActivity() {
        assertEquals("早餐", ledgerUnitDemoTitle(DemoRouteIds.BREAKFAST_LEDGER))
        assertEquals("酒店", ledgerUnitDemoTitle(DemoRouteIds.HOTEL_LEDGER))
        assertEquals("门票", ledgerUnitDemoTitle(DemoRouteIds.TICKET_LEDGER))
    }

    @Test
    fun demoTransferResultKeepsActivityAndOptionalLedgerUnitScopes() {
        val result = demoCreateTransfer(
            TransferDraft(
                activityId = "activity-a",
                ledgerUnitId = "ledger-a",
                mode = TransferMode.RECEIVE,
                participantId = "member-a",
                amount = "10.0",
            ),
        )

        assertEquals("activity-a", result.activityId)
        assertEquals("ledger-a", result.ledgerUnitId)
        assertEquals(
            "demo-transfer-activity-a-ledger-a-receive-member-a",
            result.transferId,
        )
    }

    @Test
    fun expenseRouteDemoLoaderExposesBothActiveAndDeletedStatesById() {
        assertEquals(ExpenseDetailStatus.Deleted, demoExpenseDetailUiState(DemoRouteIds.DINNER_EXPENSE).status)
        assertEquals(ExpenseDetailStatus.Active, demoExpenseDetailUiState(DemoRouteIds.TAXI_EXPENSE).status)
    }
}
