package com.ffocalors.sharedledger.data.realtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import io.github.jan.supabase.realtime.RealtimeChannel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

class SupabaseActivityRealtimeSourceTest {
    @Test
    fun frozenTablesMapToFourInvalidationDomainsAndScopedColumns() {
        assertEquals(16, ACTIVITY_REALTIME_TABLE_SPECS.size)
        assertEquals(16, ACTIVITY_REALTIME_TABLE_SPECS.map { it.table }.toSet().size)
        assertEquals(
            15,
            ACTIVITY_REALTIME_TABLE_SPECS.count { !it.requiresLedgerUnitScope },
        )
        val expenseSpec = ACTIVITY_REALTIME_TABLE_SPECS.first { it.table == "expenses" }
        assertEquals("ledger_unit_id", expenseSpec.filterColumn)
        assertTrue(expenseSpec.requiresLedgerUnitScope)
        assertEquals("ledger_unit_id=eq.unit-1", ledgerUnitRealtimeFilterExpression(expenseSpec, "unit-1"))
        assertTrue(
            ACTIVITY_REALTIME_TABLE_SPECS
                .filterNot { it.requiresLedgerUnitScope }
                .all { it.filterColumn == "id" || it.filterColumn == "activity_id" },
        )
        assertEquals("id=eq.activity-1", activityRealtimeFilterExpression(
            ACTIVITY_REALTIME_TABLE_SPECS.first { it.table == "activities" },
            "activity-1",
        ))
        assertEquals("activity_id=eq.activity-1", activityRealtimeFilterExpression(
            ACTIVITY_REALTIME_TABLE_SPECS.first { it.table == "transfers" },
            "activity-1",
        ))
        assertEquals(
            setOf(ActivityRealtimeDomain.ActivityIdentity, ActivityRealtimeDomain.Expense, ActivityRealtimeDomain.Financial, ActivityRealtimeDomain.Attachment),
            ACTIVITY_REALTIME_TABLE_SPECS.map { it.domain }.toSet(),
        )
        assertEquals(
            setOf("activities", "activity_members", "ledger_units", "participants", "participant_claims"),
            ACTIVITY_REALTIME_TABLE_SPECS.filter { it.domain == ActivityRealtimeDomain.ActivityIdentity }.map { it.table }.toSet(),
        )
    }

    @Test
    fun channelStatusDistinguishesInitialConnectionReconnectAndClose() {
        assertEquals(
            ActivityRealtimeConnectionState.Connecting,
            mapRealtimeChannelStatus(RealtimeChannel.Status.SUBSCRIBING, wasConnected = false, closing = false),
        )
        assertEquals(
            ActivityRealtimeConnectionState.Reconnecting,
            mapRealtimeChannelStatus(RealtimeChannel.Status.SUBSCRIBING, wasConnected = true, closing = false),
        )
        assertEquals(
            ActivityRealtimeConnectionState.Connected,
            mapRealtimeChannelStatus(RealtimeChannel.Status.SUBSCRIBED, wasConnected = true, closing = false),
        )
        assertEquals(
            ActivityRealtimeConnectionState.Disconnected,
            mapRealtimeChannelStatus(RealtimeChannel.Status.UNSUBSCRIBED, wasConnected = true, closing = true),
        )
    }

    @Test
    fun closeGateRunsCleanupOnlyOnce() {
        var cleanupCount = 0
        val gate = RealtimeCloseGate { cleanupCount++ }

        gate.close()
        gate.close()

        assertTrue(gate.isClosed)
        assertEquals(1, cleanupCount)
    }

    @Test
    fun collectorFailureIsTerminalAndDistinctFromCancellation() {
        val cause = IllegalStateException("flow failed")
        val failure = RealtimeCollectorFailure(cause)

        assertSame(cause, failure.cause)
        assertFalse(failure.cause is CancellationException)
    }

    @Test
    fun refreshCancellationTerminatesInfiniteCollectorsBeforeSessionContinues() = runBlocking {
        val collector = launch { awaitCancellation() }

        cancelAndJoinRealtimeCollectors(listOf(collector))

        assertTrue(collector.isCompleted)
    }

    @Test
    fun unavailableSourceReportsFailureWithoutPretendingToSubscribe() {
        var state: ActivityRealtimeConnectionState? = null
        val subscription = UnavailableActivityRealtimeSource().subscribe(
            activityId = "activity-1",
            onSignal = {},
            onConnectionState = { state = it },
        )

        subscription.close()
        subscription.close()

        assertEquals(ActivityRealtimeConnectionState.Failed, state)
        assertFalse(state == ActivityRealtimeConnectionState.Connected)
    }
}
