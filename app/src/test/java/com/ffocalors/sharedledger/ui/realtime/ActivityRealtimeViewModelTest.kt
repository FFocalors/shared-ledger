package com.ffocalors.sharedledger.ui.realtime

import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeConnectionState
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeDomain
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeSignal
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeSource
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeSubscription
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.ExperimentalCoroutinesApi
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ActivityRealtimeViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun observingSameActivityDoesNotCreateAnotherSubscription() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val source = FakeSource()
        val viewModel = ActivityRealtimeViewModel { source }

        viewModel.observeActivity("activity-1")
        viewModel.observeActivity("activity-1")
        advanceUntilIdle()

        assertEquals(1, source.subscribeCalls)
        assertEquals("activity-1", viewModel.uiState.value.activeActivityId)
    }

    @Test
    fun switchingAndStoppingClosesOldSubscriptionAndDropsLateSignals() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val source = FakeSource()
        val viewModel = ActivityRealtimeViewModel { source }

        viewModel.observeActivity("activity-1")
        advanceUntilIdle()
        val old = source.subscriptions.single()
        viewModel.observeActivity("activity-2")
        advanceUntilIdle()

        old.emit(ActivityRealtimeDomain.Expense)
        advanceTimeBy(300)
        runCurrent()
        assertEquals("activity-2", viewModel.uiState.value.activeActivityId)
        assertEquals(0L, viewModel.uiState.value.revisions.expense)

        viewModel.stop()
        source.subscriptions.last().emit(ActivityRealtimeDomain.Financial)
        advanceTimeBy(300)
        runCurrent()
        assertEquals(2, source.closedCount)
        assertNull(viewModel.uiState.value.activeActivityId)
        assertEquals(ActivityRealtimeConnectionState.Disconnected, viewModel.uiState.value.connectionState)
        assertEquals(0L, viewModel.uiState.value.revisions.financial)
    }

    @Test
    fun eachDomainSignalPublishesItsOwnMonotonicRevision() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val source = FakeSource()
        val viewModel = ActivityRealtimeViewModel { source }
        viewModel.observeActivity("activity-1")
        advanceUntilIdle()
        val subscription = source.subscriptions.single()

        ActivityRealtimeDomain.entries.forEach { domain ->
            subscription.emit(domain)
            advanceTimeBy(300)
            runCurrent()
        }

        assertEquals(1L, viewModel.uiState.value.revisions.activityIdentity)
        assertEquals(1L, viewModel.uiState.value.revisions.expense)
        assertEquals(1L, viewModel.uiState.value.revisions.financial)
        assertEquals(1L, viewModel.uiState.value.revisions.attachment)
        assertEquals(ActivityRealtimeDomain.Attachment, viewModel.uiState.value.lastInvalidation?.domain)
        assertEquals(1L, viewModel.uiState.value.lastInvalidation?.revision)

        subscription.emit(ActivityRealtimeDomain.Expense)
        advanceTimeBy(300)
        runCurrent()
        assertEquals(2L, viewModel.uiState.value.revisions.expense)
    }

    @Test
    fun foregroundRequestsAllFourDomains() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val source = FakeSource()
        val viewModel = ActivityRealtimeViewModel { source }
        viewModel.observeActivity("activity-1")
        advanceUntilIdle()

        viewModel.onForeground()
        advanceTimeBy(300)
        runCurrent()

        assertEquals(1L, viewModel.uiState.value.revisions.activityIdentity)
        assertEquals(1L, viewModel.uiState.value.revisions.expense)
        assertEquals(1L, viewModel.uiState.value.revisions.financial)
        assertEquals(1L, viewModel.uiState.value.revisions.attachment)
    }

    private class FakeSource : ActivityRealtimeSource {
        val subscriptions = mutableListOf<FakeSubscription>()
        var subscribeCalls = 0
            private set
        var closedCount = 0
            private set

        override fun subscribe(
            activityId: String,
            onSignal: (ActivityRealtimeSignal) -> Unit,
            onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
        ): ActivityRealtimeSubscription {
            subscribeCalls += 1
            val subscription = FakeSubscription(activityId, onSignal) { closedCount += 1 }
            subscriptions += subscription
            onConnectionState(ActivityRealtimeConnectionState.Connected)
            return subscription
        }
    }

    private class FakeSubscription(
        private val activityId: String,
        private val onSignal: (ActivityRealtimeSignal) -> Unit,
        private val onClose: () -> Unit,
    ) : ActivityRealtimeSubscription {
        private var closed = false

        override fun close() {
            if (!closed) {
                closed = true
                onClose()
            }
        }

        fun emit(domain: ActivityRealtimeDomain) {
            onSignal(ActivityRealtimeSignal(activityId, domain))
        }
    }
}
