package com.ffocalors.sharedledger.data.realtime

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ActivityRealtimeCoordinatorTest {
    private val dispatcher = StandardTestDispatcher()

    @Test
    fun switchingActivityClosesOldSubscriptionAndDropsLateSignals() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        val refreshed = mutableListOf<String>()
        val coordinator = ActivityRealtimeCoordinator(this, source, { activityId, domain ->
            refreshed += "$activityId:$domain"
            Result.success(Unit)
        })

        coordinator.start("activity-a")
        val old = source.callbacks.single()
        coordinator.start("activity-b")
        val current = source.callbacks.last()

        old.signal(ActivityRealtimeDomain.ActivityIdentity, "late")
        old.signal(ActivityRealtimeDomain.Expense, "late")
        current.signal(ActivityRealtimeDomain.Expense, "current")
        advanceTimeBy(250)
        runCurrent()

        assertEquals(listOf("activity-b:${ActivityRealtimeDomain.Expense}"), refreshed)
        assertTrue(source.closedCount >= 1)
        coordinator.stop()
    }

    @Test
    fun repeatedSignalsDebounceIntoOneRefreshPerDomain() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        val refreshed = mutableListOf<ActivityRealtimeDomain>()
        val coordinator = ActivityRealtimeCoordinator(this, source, { _, domain ->
            refreshed += domain
            Result.success(Unit)
        })
        coordinator.start("activity-1")
        val callback = source.callbacks.single()

        callback.signal(ActivityRealtimeDomain.Expense, "1")
        callback.signal(ActivityRealtimeDomain.Expense, "2")
        callback.signal(ActivityRealtimeDomain.Expense, "3")
        advanceTimeBy(249)
        runCurrent()
        assertTrue(refreshed.isEmpty())
        advanceTimeBy(1)
        runCurrent()

        assertEquals(listOf(ActivityRealtimeDomain.Expense), refreshed)
        coordinator.stop()
    }

    @Test
    fun signalDuringRefreshRunsOneTrailingRefresh() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        val firstRefresh = CompletableDeferred<Unit>()
        var calls = 0
        val coordinator = ActivityRealtimeCoordinator(this, source, { _, _ ->
            calls += 1
            if (calls == 1) firstRefresh.await()
            Result.success(Unit)
        })
        coordinator.start("activity-1")
        val callback = source.callbacks.single()
        callback.signal(ActivityRealtimeDomain.Financial)
        advanceTimeBy(250)
        runCurrent()
        assertEquals(1, calls)

        callback.signal(ActivityRealtimeDomain.Financial)
        callback.signal(ActivityRealtimeDomain.Financial)
        firstRefresh.complete(Unit)
        runCurrent()
        assertEquals(1, calls)
        advanceTimeBy(250)
        runCurrent()

        assertEquals(2, calls)
        coordinator.stop()
    }

    @Test
    fun foregroundRefreshesEveryDomain() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        val refreshed = mutableSetOf<ActivityRealtimeDomain>()
        val events = mutableListOf<String>()
        val coordinator = ActivityRealtimeCoordinator(this, source, { _, domain ->
            events += "refresh:$domain"
            refreshed += domain
            Result.success(Unit)
        })
        coordinator.start("activity-1")
        source.events = events
        coordinator.onForeground()
        advanceTimeBy(250)
        runCurrent()

        assertEquals(ActivityRealtimeDomain.entries.toSet(), refreshed)
        assertEquals("scope:activity-1", events.first())
        assertEquals(1, source.refreshScopeCalls)
        coordinator.stop()
    }

    @Test
    fun identitySignalRefreshesScopeOnce() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        val coordinator = ActivityRealtimeCoordinator(
            scope = this,
            source = source,
            refresh = { _, _ -> Result.success(Unit) },
        )
        coordinator.start("activity-1")
        source.callbacks.single().signal(ActivityRealtimeDomain.ActivityIdentity)
        advanceTimeBy(250)
        runCurrent()

        assertEquals(1, source.refreshScopeCalls)
        coordinator.stop()
    }

    @Test
    fun reconnectRefreshesScopeButInitialConnectionDoesNotRebuildIt() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        source.emitReconnectOnRefreshScope = true
        val coordinator = ActivityRealtimeCoordinator(
            scope = this,
            source = source,
            refresh = { _, _ -> Result.success(Unit) },
        )
        coordinator.start("activity-1")
        val callback = source.callbacks.single()

        callback.connection(ActivityRealtimeConnectionState.Connected)
        assertEquals(0, source.refreshScopeCalls)

        callback.connection(ActivityRealtimeConnectionState.Reconnecting)
        callback.connection(ActivityRealtimeConnectionState.Connected)
        assertEquals(1, source.refreshScopeCalls)
        advanceTimeBy(250)
        runCurrent()
        assertEquals(1, source.refreshScopeCalls)
        coordinator.stop()
    }

    @Test
    fun failedScopeRefreshStillRunsAllDomainsAndCanRecover() = runTest(dispatcher) {
        val source = FakeRealtimeSource()
        source.failNextRefreshScope = true
        val refreshed = mutableSetOf<ActivityRealtimeDomain>()
        val coordinator = ActivityRealtimeCoordinator(
            scope = this,
            source = source,
            refresh = { _, domain ->
                refreshed += domain
                Result.success(Unit)
            },
        )
        coordinator.start("activity-1")
        coordinator.onForeground()
        assertTrue(coordinator.state.value.lastErrors.containsKey(ActivityRealtimeDomain.ActivityIdentity))

        advanceTimeBy(250)
        runCurrent()

        assertEquals(ActivityRealtimeDomain.entries.toSet(), refreshed)
        assertTrue(coordinator.state.value.lastErrors.isEmpty())
        coordinator.stop()
    }

    private class FakeRealtimeSource : ActivityRealtimeSource {
        data class Callback(
            val activityId: String,
            val onSignal: (ActivityRealtimeSignal) -> Unit,
            val onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
        ) {
            fun signal(domain: ActivityRealtimeDomain, eventId: String? = null) {
                onSignal(ActivityRealtimeSignal(activityId, domain, eventId))
            }

            fun connection(state: ActivityRealtimeConnectionState) {
                onConnectionState(state)
            }
        }

        val callbacks = mutableListOf<Callback>()
        var closedCount = 0
        var refreshScopeCalls = 0
        var failNextRefreshScope = false
        var emitReconnectOnRefreshScope = false
        var events: MutableList<String>? = null

        override fun subscribe(
            activityId: String,
            onSignal: (ActivityRealtimeSignal) -> Unit,
            onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
        ): ActivityRealtimeSubscription {
            val callback = Callback(activityId, onSignal, onConnectionState)
            callbacks += callback
            return object : ActivityRealtimeSubscription {
                override fun close() {
                    closedCount += 1
                }

                override fun refreshScope() {
                    refreshScopeCalls += 1
                    events?.add("scope:$activityId")
                    if (failNextRefreshScope) {
                        failNextRefreshScope = false
                        error("scope refresh failed")
                    }
                    if (emitReconnectOnRefreshScope) {
                        callback.connection(ActivityRealtimeConnectionState.Reconnecting)
                        callback.connection(ActivityRealtimeConnectionState.Connected)
                    }
                }
            }
        }
    }
}
