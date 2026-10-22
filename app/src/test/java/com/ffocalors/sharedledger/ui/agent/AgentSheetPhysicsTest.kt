package com.ffocalors.sharedledger.ui.agent

import androidx.compose.animation.core.DecayAnimationSpec
import androidx.compose.animation.core.exponentialDecay
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentSheetPhysicsTest {
    private val expanded = 100f
    private val half = 450f
    private val hidden = 1000f
    private val anchors = listOf(expanded, half, hidden)
    private val density = 1f

    private val decay: DecayAnimationSpec<Float> = exponentialDecay()

    private fun choose(offset: Float, v: Float) =
        AgentSheetPhysics.chooseAnchor(offset, v, anchors, decay, density)

    @Test
    fun rubberBandIsMonotonicAndBounded() {
        val limit = 64f
        var previous = 0f
        for (x in 1..2000 step 10) {
            val y = AgentSheetPhysics.rubberBand(x.toFloat(), limit)
            assertTrue(y >= previous)
            assertTrue(y < limit)
            previous = y
        }
        assertEquals(0f, AgentSheetPhysics.rubberBand(-5f, limit), 0f)
        assertEquals(0f, AgentSheetPhysics.rubberBand(0f, limit), 0f)
    }

    @Test
    fun rubberBandInverseRoundTrips() {
        val y = AgentSheetPhysics.rubberBand(120f, 64f)
        assertEquals(120f, AgentSheetPhysics.rubberBandInverse(y, 64f), 0.5f)
    }

    @Test
    fun slowReleasePicksNearestAnchor() {
        assertEquals(half, choose(300f, 0f), 0f)
        assertEquals(expanded, choose(250f, 0f), 0f)
        assertEquals(hidden, choose(800f, 50f), 0f)
    }

    @Test
    fun fastUpwardFlingFromHalfGoesToExpanded() {
        assertEquals(expanded, choose(half, -2500f), 0f)
    }

    @Test
    fun fastDownwardFlingFromExpandedGoesAtLeastHalf() {
        // projected = 100 + 1900/4.2 = 552 -> Half; the min-step rule also guarantees at least Half.
        val target = choose(expanded, 1900f)
        assertTrue(target >= half)
    }

    @Test
    fun veryFastDownwardFlingDismisses() {
        assertEquals(hidden, choose(expanded, 6000f), 0f)
    }

    @Test
    fun releaseInRubberZoneReturnsToExpanded() {
        assertEquals(expanded, choose(expanded - 40f, 0f), 0f)
        assertEquals(expanded, choose(expanded - 40f, -3000f), 0f)
    }
}
