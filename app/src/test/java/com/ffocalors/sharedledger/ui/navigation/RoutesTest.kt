package com.ffocalors.sharedledger.ui.navigation

import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.ui.demo.DemoRouteIds
import com.ffocalors.sharedledger.ui.screens.FinalSettlementRequest
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RoutesTest {
    @Test
    fun routeBuildersCoverAllScreensAndStableIds() {
        assertEquals("auth", SharedLedgerRoutes.AUTH)
        assertEquals(SharedLedgerRoutes.AUTH, SharedLedgerRoutes.START_DESTINATION)
        assertEquals("home", SharedLedgerRoutes.HOME)
        assertEquals("join-activity", SharedLedgerRoutes.JOIN_ACTIVITY)
        assertEquals("create-activity", SharedLedgerRoutes.CREATE_ACTIVITY)
        assertEquals("normal-activity/demo-normal", SharedLedgerRoutes.normalActivity(DemoRouteIds.NORMAL_ACTIVITY))
        assertEquals("large-activity/demo-large", SharedLedgerRoutes.largeActivity(DemoRouteIds.LARGE_ACTIVITY))
        assertEquals("create-sub-activity/{activityId}", SharedLedgerRoutes.CREATE_SUB_ACTIVITY_PATTERN)
        assertEquals("ledger-unit/{activityId}/{ledgerUnitId}", SharedLedgerRoutes.LEDGER_UNIT_PATTERN)
        assertEquals("create-sub-activity/demo-large", SharedLedgerRoutes.createSubActivity(DemoRouteIds.LARGE_ACTIVITY))
        assertEquals(
            "ledger-unit/demo-large/demo-ticket",
            SharedLedgerRoutes.ledgerUnit(DemoRouteIds.LARGE_ACTIVITY, DemoRouteIds.TICKET_LEDGER),
        )
        assertEquals(
            "new-expense/demo-large?ledgerUnitId=demo-ticket",
            SharedLedgerRoutes.newExpense(DemoRouteIds.LARGE_ACTIVITY, DemoRouteIds.TICKET_LEDGER),
        )
        assertEquals("fund-records/{activityId}?ledgerUnitId={ledgerUnitId}", SharedLedgerRoutes.FUND_RECORDS_PATTERN)
        assertEquals(SharedLedgerRoutes.FUND_RECORDS_PATTERN, SharedLedgerRoutes.FUND_RECORDS)
        assertEquals("fund-records/demo-large", SharedLedgerRoutes.fundRecords(DemoRouteIds.LARGE_ACTIVITY))
        assertEquals(
            "fund-records/demo-large?ledgerUnitId=demo-ticket",
            SharedLedgerRoutes.fundRecords(DemoRouteIds.LARGE_ACTIVITY, DemoRouteIds.TICKET_LEDGER),
        )
        assertEquals("final-settlement/demo-large", SharedLedgerRoutes.finalSettlement(DemoRouteIds.LARGE_ACTIVITY))
        assertEquals(
            "activity-management/demo-large",
            SharedLedgerRoutes.activityManagement(DemoRouteIds.LARGE_ACTIVITY),
        )
        assertEquals(
            "expense-detail/demo-expense-dinner",
            SharedLedgerRoutes.expenseDetail(DemoRouteIds.DINNER_EXPENSE),
        )
        assertEquals(
            "transfer-detail/demo-normal/demo-transfer-001",
            SharedLedgerRoutes.transferDetail(DemoRouteIds.NORMAL_ACTIVITY, DemoRouteIds.TRANSFER),
        )
        assertEquals(
            "transfer-detail/{activityId}/{transferId}?ledgerUnitId={ledgerUnitId}",
            SharedLedgerRoutes.TRANSFER_DETAIL_PATTERN,
        )
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
        assertEquals(
            "transfer/demo-large?mode=receive&ledgerUnitId=demo-breakfast",
            SharedLedgerRoutes.transfer(
                DemoRouteIds.LARGE_ACTIVITY,
                TransferRouteMode.RECEIVE,
                DemoRouteIds.BREAKFAST_LEDGER,
            ),
        )
    }

    @Test
    fun finalSettlementBuildsConcreteRecordAndOnePathPerComponent() {
        val record = demoFinalSettlementRecord(
            request = FinalSettlementRequest(
                activityId = "activity-1",
                previewItemId = "preview-1",
                fromParticipantId = "fake-alice",
                toParticipantId = "fake-carol",
                amount = BigDecimal("320.00"),
                currency = "EUR",
                ordinaryAmount = BigDecimal("200.00"),
                prepaymentReturnAmount = BigDecimal("120.00"),
                sourceFinancialVersion = 8L,
            ),
            transferId = "final-transfer-1",
            actor = com.ffocalors.sharedledger.domain.financial.RecorderInfo("actor", "Actor"),
        )

        assertEquals(FundRecordType.FINAL_SETTLEMENT, record.type)
        assertEquals("fake-alice", record.from.participantId)
        assertEquals("fake-carol", record.to.participantId)
        assertEquals(BigDecimal("320.00"), record.amount)
        assertEquals("EUR", record.currency)
        assertEquals(
            listOf(FundRecordComponentType.SETTLEMENT, FundRecordComponentType.PREPAYMENT_RETURN),
            record.components.map { it.type },
        )
        assertEquals(2, record.finalSettlementPaths.size)
        assertTrue(record.finalSettlementPaths.all { it.from == record.from && it.to == record.to })
    }

    @Test
    fun transferDetailRetainsActivityScopeAndOptionalLedgerScope() {
        assertEquals(
            "transfer-detail/demo-large/demo-transfer-demo-large-demo-breakfast-receive-demo-participant-lisi?ledgerUnitId=demo-breakfast",
            SharedLedgerRoutes.transferDetail(
                DemoRouteIds.LARGE_ACTIVITY,
                DemoRouteIds.transfer(
                    DemoRouteIds.LARGE_ACTIVITY,
                    DemoRouteIds.BREAKFAST_LEDGER,
                    TransferRouteMode.RECEIVE.value,
                    "demo-participant-lisi",
                ),
                DemoRouteIds.BREAKFAST_LEDGER,
            ),
        )
    }

    @Test
    fun fundRecordsKeepsLedgerUnitAsNavigationContextOnly() {
        val route = SharedLedgerRoutes.fundRecords("activity-a", "ledger-a")
        assertEquals("fund-records/activity-a?ledgerUnitId=ledger-a", route)
        assertEquals(1, route.substringBefore('?').split('/').size - 1)
        assertEquals(false, route.substringAfter('?').contains("transfer"))
    }

    @Test
    fun demoTransferIdsAreStableAndDistinctBySourceScope() {
        val breakfastReceive = DemoRouteIds.transfer(
            DemoRouteIds.LARGE_ACTIVITY,
            DemoRouteIds.BREAKFAST_LEDGER,
            TransferRouteMode.RECEIVE.value,
            "demo-participant-lisi",
        )
        assertEquals(breakfastReceive, DemoRouteIds.transfer(
            DemoRouteIds.LARGE_ACTIVITY,
            DemoRouteIds.BREAKFAST_LEDGER,
            TransferRouteMode.RECEIVE.value,
            "demo-participant-lisi",
        ))
        assertEquals(
            "demo-transfer-demo-large-demo-breakfast-receive-demo-participant-lisi",
            breakfastReceive,
        )
        assertEquals(
            "demo-transfer-demo-large-demo-hotel-receive-demo-participant-lisi",
            DemoRouteIds.transfer(
                DemoRouteIds.LARGE_ACTIVITY,
                DemoRouteIds.HOTEL_LEDGER,
                TransferRouteMode.RECEIVE.value,
                "demo-participant-lisi",
            ),
        )
    }

    @Test
    fun transferModeParsingDefaultsUnknownValuesToTransfer() {
        assertEquals(TransferRouteMode.TRANSFER, SharedLedgerRoutes.parseTransferMode(null))
        assertEquals(TransferRouteMode.TRANSFER, SharedLedgerRoutes.parseTransferMode("other"))
        assertEquals(TransferRouteMode.RECEIVE, SharedLedgerRoutes.parseTransferMode("RECEIVE"))
    }

    @Test
    fun createRouteRejectsBlankIdsAndKeepsOpaqueId() {
        assertEquals("example/opaque-123", SharedLedgerRoutes.createRoute("example", "opaque-123"))
        try {
            SharedLedgerRoutes.createRoute("example", " ")
            throw AssertionError("blank route id should be rejected")
        } catch (_: IllegalArgumentException) {
            // Expected: route helpers must not create an address with a missing identity.
        }
    }

    @Test
    fun authSuccessNavigationClearsAuthReturnStack() {
        assertEquals(
            SharedLedgerRoutes.AuthSuccessNavigation(
                destination = SharedLedgerRoutes.HOME,
                popUpTo = SharedLedgerRoutes.AUTH,
                inclusive = true,
                launchSingleTop = true,
            ),
            SharedLedgerRoutes.authSuccessNavigation(),
        )
    }
}
