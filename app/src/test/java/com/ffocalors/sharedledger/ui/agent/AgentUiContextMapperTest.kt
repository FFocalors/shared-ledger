package com.ffocalors.sharedledger.ui.agent

import com.ffocalors.sharedledger.data.agent.UiEntityType
import com.ffocalors.sharedledger.data.agent.UiPageType
import com.ffocalors.sharedledger.ui.navigation.SharedLedgerRoutes
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentUiContextMapperTest {
    private fun map(route: String, vararg args: Pair<String, String>, name: String? = null) =
        AgentUiContextMapper.map(route, args.toMap(), "2026-10-22T08:00:00Z", "1.2.3") { name }

    @Test
    fun homeMapsToHomeWithoutActivity() {
        val c = map(SharedLedgerRoutes.HOME)
        assertEquals(UiPageType.HOME, c.uiContext.pageType)
        assertNull(c.uiContext.activityId)
        assertEquals("1.2.3", c.uiContext.clientVersion)
        assertEquals("2026-10-22T08:00:00Z", c.uiContext.capturedAt)
    }

    @Test
    fun activityScreensMapToOverviewWithNameOrGenericLabel() {
        for (route in listOf(SharedLedgerRoutes.NORMAL_ACTIVITY_PATTERN, SharedLedgerRoutes.LARGE_ACTIVITY_PATTERN)) {
            val c = map(route, "activityId" to "a1", name = "周末露营")
            assertEquals(UiPageType.ACTIVITY_OVERVIEW, c.uiContext.pageType)
            assertEquals("a1", c.uiContext.activityId)
            assertEquals("周末露营的账目", c.label)
        }
        assertEquals("当前活动", map(SharedLedgerRoutes.NORMAL_ACTIVITY_PATTERN, "activityId" to "a1").label)
    }

    @Test
    fun ledgerUnitCarriesLedgerUnitId() {
        val c = map(SharedLedgerRoutes.LEDGER_UNIT_PATTERN, "activityId" to "a1", "ledgerUnitId" to "l1")
        assertEquals(UiPageType.ACTIVITY_OVERVIEW, c.uiContext.pageType)
        assertEquals("l1", c.uiContext.ledgerUnitId)
    }

    @Test
    fun expenseDetailSelectsTheExpense() {
        val c = map(SharedLedgerRoutes.EXPENSE_DETAIL_PATTERN, "expenseId" to "e1", "activityId" to "a1")
        assertEquals(UiPageType.EXPENSE_DETAIL, c.uiContext.pageType)
        assertEquals("e1", c.uiContext.selectedEntity?.entityId)
        assertEquals(UiEntityType.EXPENSE, c.uiContext.selectedEntity?.entityType)
        assertEquals("a1", c.uiContext.activityId)
    }

    @Test
    fun otherPagesMapByRoute() {
        assertEquals(UiPageType.EXPENSE_LIST, map(SharedLedgerRoutes.FUND_RECORDS_PATTERN, "activityId" to "a1").uiContext.pageType)
        assertEquals(UiPageType.SETTLEMENT, map(SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN, "activityId" to "a1").uiContext.pageType)
        assertEquals(UiPageType.PREPAYMENT, map(SharedLedgerRoutes.PREPAYMENT_PATTERN, "activityId" to "a1").uiContext.pageType)
        assertEquals(UiPageType.SETTINGS, map(SharedLedgerRoutes.PERSONAL_INFO).uiContext.pageType)
    }

    @Test
    fun unknownRouteFallsBackToHomeKeepingActivityId() {
        val c = map(SharedLedgerRoutes.ACTIVITY_MANAGEMENT_PATTERN, "activityId" to "a9")
        assertEquals(UiPageType.HOME, c.uiContext.pageType)
        assertEquals("a9", c.uiContext.activityId)
        assertEquals(UiPageType.HOME, map("something-else").uiContext.pageType)
        assertEquals(UiPageType.HOME, AgentUiContextMapper.map(null, emptyMap(), "t", "v").uiContext.pageType)
    }

    @Test
    fun entryIsHiddenOnKeypadRoutes() {
        listOf(
            SharedLedgerRoutes.NEW_EXPENSE_PATTERN,
            SharedLedgerRoutes.TRANSFER_PATTERN,
            SharedLedgerRoutes.CREATE_ACTIVITY,
            SharedLedgerRoutes.CREATE_SUB_ACTIVITY_PATTERN,
            SharedLedgerRoutes.JOIN_ACTIVITY,
        ).forEach { assertTrue(it, AgentUiContextMapper.isEntryHidden(it)) }
        listOf(SharedLedgerRoutes.HOME, SharedLedgerRoutes.NORMAL_ACTIVITY_PATTERN, SharedLedgerRoutes.TRANSFER_DETAIL_PATTERN)
            .forEach { assertFalse(it, AgentUiContextMapper.isEntryHidden(it)) }
    }

    @Test
    fun nameResolverNeverLeaksIds() {
        val names = AgentNameResolver(participants = mapOf("p1" to "小王"))
        assertEquals("小王", names.participant("p1"))
        assertEquals("1 位参与人", names.participant("9f3c-uuid"))
        assertEquals("2 位参与人", names.participantGroup(listOf("p1", "unknown")))
        assertEquals("另一个账本", names.ledgerUnit("lu-uuid"))
        assertEquals("小王 750.00", names.participantAmounts(listOf("p1" to "750.00")))
        assertEquals("2 位参与人 共 770.00", names.participantAmounts(listOf("p1" to "750.00", "x" to "20.00")))
    }
}
