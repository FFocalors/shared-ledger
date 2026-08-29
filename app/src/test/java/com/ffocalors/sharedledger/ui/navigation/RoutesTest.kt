package com.ffocalors.sharedledger.ui.navigation

import com.ffocalors.sharedledger.ui.demo.DemoRouteIds
import org.junit.Assert.assertEquals
import org.junit.Test

class RoutesTest {
    @Test
    fun routeBuildersCoverAllScreensAndStableIds() {
        assertEquals("home", SharedLedgerRoutes.HOME)
        assertEquals("create-activity", SharedLedgerRoutes.CREATE_ACTIVITY)
        assertEquals("normal-activity/demo-normal", SharedLedgerRoutes.normalActivity(DemoRouteIds.NORMAL_ACTIVITY))
        assertEquals("large-activity/demo-large", SharedLedgerRoutes.largeActivity(DemoRouteIds.LARGE_ACTIVITY))
        assertEquals("ledger-unit/demo-ticket", SharedLedgerRoutes.ledgerUnit(DemoRouteIds.TICKET_LEDGER))
        assertEquals("new-expense/demo-ticket", SharedLedgerRoutes.newExpense(DemoRouteIds.TICKET_LEDGER))
        assertEquals("final-settlement/demo-large", SharedLedgerRoutes.finalSettlement(DemoRouteIds.LARGE_ACTIVITY))
        assertEquals("normal-activity/demo-created-normal", SharedLedgerRoutes.normalActivity(DemoRouteIds.CREATED_NORMAL_ACTIVITY))
        assertEquals("large-activity/demo-created-large", SharedLedgerRoutes.largeActivity(DemoRouteIds.CREATED_LARGE_ACTIVITY))
    }

    @Test
    fun transferRouteCoversTransferAndReceiveModes() {
        assertEquals(
            "transfer/demo-normal?mode=transfer",
            SharedLedgerRoutes.transfer(DemoRouteIds.NORMAL_ACTIVITY, TransferRouteMode.TRANSFER),
        )
        assertEquals(
            "transfer/demo-normal?mode=receive",
            SharedLedgerRoutes.transfer(DemoRouteIds.NORMAL_ACTIVITY, TransferRouteMode.RECEIVE),
        )
    }

    @Test
    fun transferModeParsingDefaultsUnknownValuesToTransfer() {
        assertEquals(TransferRouteMode.TRANSFER, SharedLedgerRoutes.parseTransferMode(null))
        assertEquals(TransferRouteMode.TRANSFER, SharedLedgerRoutes.parseTransferMode("other"))
        assertEquals(TransferRouteMode.RECEIVE, SharedLedgerRoutes.parseTransferMode("RECEIVE"))
    }
}
