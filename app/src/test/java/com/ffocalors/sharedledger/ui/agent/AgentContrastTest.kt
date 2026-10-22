package com.ffocalors.sharedledger.ui.agent

import androidx.compose.ui.graphics.Color
import com.ffocalors.sharedledger.ui.theme.AgentSimulationContainer
import com.ffocalors.sharedledger.ui.theme.AgentSimulationContent
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.Inverted
import com.ffocalors.sharedledger.ui.theme.InvertedContent
import com.ffocalors.sharedledger.ui.theme.SoftCharcoal
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.sharedLedgerContrastRatio
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentContrastTest {
    private fun assertAccessible(name: String, foreground: Color, background: Color) {
        val ratio = sharedLedgerContrastRatio(foreground, background)
        assertTrue("$name contrast $ratio < 4.5", ratio >= 4.5)
    }

    @Test
    fun inkOnPaper() = assertAccessible("Ink/Paper", DeepCharcoal, AppBackground)

    @Test
    fun graphiteTextOnDraftAmber() =
        assertAccessible("Graphite/Amber", Color(0xFF4A4A4A), WarmOrangeContainer)

    @Test
    fun simulationContentOnMist() =
        assertAccessible("Mist", AgentSimulationContent, AgentSimulationContainer)

    @Test
    fun creamOnGraphite() = assertAccessible("Cream/Graphite", InvertedContent, Inverted)

    @Test
    fun secondaryTextOnPaper() = assertAccessible("SoftCharcoal/Paper", SoftCharcoal, AppBackground)

    @Test
    fun shimmerAmberOnPaper() = assertAccessible("ShimmerAmber/Paper", ShimmerAmber, AppBackground)
}
