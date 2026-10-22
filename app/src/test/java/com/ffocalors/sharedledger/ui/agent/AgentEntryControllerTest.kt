package com.ffocalors.sharedledger.ui.agent

import com.ffocalors.sharedledger.data.agent.TurnState
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AgentEntryControllerTest {
    private fun TestScope.controller(autoRetractMs: Long? = 4_000L) =
        AgentEntryController(backgroundScope, autoRetractMs)

    @Test
    fun tapTuckedReveals() = runTest {
        val c = controller()
        var opened = 0
        c.onTap { opened++ }
        assertTrue(c.revealed)
        assertEquals(0, opened)
    }

    @Test
    fun tapRevealedOpensAndStaysRevealedUntilSheetCloses() = runTest {
        val c = controller()
        var opened = 0
        c.onTap { opened++ }
        c.onTap { opened++ }
        c.onSheetOpenChanged(true)
        assertEquals(1, opened)
        advanceTimeBy(10_000)
        assertTrue(c.revealed)
        c.onSheetOpenChanged(false)
        assertFalse(c.revealed)
    }

    @Test
    fun retractsAfterFourSeconds() = runTest {
        val c = controller()
        c.reveal()
        advanceTimeBy(3_999)
        assertTrue(c.revealed)
        advanceTimeBy(2)
        assertFalse(c.revealed)
    }

    @Test
    fun interactionResetsTimeout() = runTest {
        val c = controller()
        c.reveal()
        advanceTimeBy(3_000)
        c.onInteraction()
        advanceTimeBy(3_000)
        assertTrue(c.revealed)
        advanceTimeBy(1_100)
        assertFalse(c.revealed)
    }

    @Test
    fun routeChangeRetracts() = runTest {
        val c = controller()
        c.onRouteChanged("home")
        c.reveal()
        c.onRouteChanged("home")
        assertTrue(c.revealed)
        c.onRouteChanged("activity/{activityId}")
        assertFalse(c.revealed)
    }

    @Test
    fun nullTimeoutNeverRetracts() = runTest {
        val c = controller(autoRetractMs = null)
        c.reveal()
        advanceTimeBy(60_000)
        assertTrue(c.revealed)
    }

    @Test
    fun accessibilityOpenDoesNotRevealAndTucksOnClose() = runTest {
        val c = controller()
        var opened = 0
        c.open { opened++ }
        assertEquals(1, opened)
        assertFalse(c.revealed)
        c.onSheetOpenChanged(false)
        assertFalse(c.revealed)
    }

    @Test
    fun attentionOnlyForLiveTurns() {
        assertFalse(agentEntryNeedsAttention(null))
        assertFalse(agentEntryNeedsAttention(TurnState.COMPLETED))
        assertFalse(agentEntryNeedsAttention(TurnState.FAILED))
        assertTrue(agentEntryNeedsAttention(TurnState.RUNNING))
        assertTrue(agentEntryNeedsAttention(TurnState.WAIT_CONFIRM))
        assertTrue(agentEntryNeedsAttention(TurnState.WAIT_INPUT))
    }
}
