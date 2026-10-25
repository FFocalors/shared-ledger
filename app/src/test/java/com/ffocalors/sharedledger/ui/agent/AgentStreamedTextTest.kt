package com.ffocalors.sharedledger.ui.agent

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentStreamedTextTest {
    private val ink = Color(0xFF1B1C1C)
    private val text = "债务记录：zhy → whr，1.3833 CNY"

    private fun alphaAt(revealed: Float, index: Int): Float {
        val result = streamedText(text, revealed, ink)
        val span = result.spanStyles.firstOrNull { index >= it.start && index < it.end }
        return span?.item?.color?.alpha ?: 1f
    }

    @Test
    fun finishedStreamIsPlainAndFullyOpaque() {
        // Regression: the last characters used to stay semi-transparent forever.
        val done = streamedText(text, (text.length + StreamFadeTail).toFloat(), ink)
        assertEquals(text, done.text)
        assertTrue("a finished stream carries no per-character alpha", done.spanStyles.isEmpty())
    }

    @Test
    fun tailKeepsFadingPastTheLastCharacter() {
        // At exactly text.length the final character is still only 1/6 visible ...
        assertTrue(alphaAt(text.length.toFloat(), text.length - 1) < 0.2f)
        // ... and it reaches full opacity before the animation ends.
        val almost = (text.length + StreamFadeTail - 0.5f)
        assertTrue(alphaAt(almost, text.length - 1) > 0.9f)
    }

    @Test
    fun unrevealedCharactersStayLaidOutButTransparent() {
        val start = streamedText(text, 0f, ink)
        assertEquals(text, start.text)
        assertEquals(0f, alphaAt(0f, 0), 0f)
        assertEquals(0f, alphaAt(3f, 10), 0f)
    }

    @Test
    fun charactersBehindTheTailAreOpaque() {
        // 10 characters revealed, tail of 6: characters 0..3 are done fading.
        assertEquals(1f, alphaAt(10f, 0), 0f)
        assertEquals(1f, alphaAt(10f, 3), 0f)
        assertTrue(alphaAt(10f, 9) < 0.3f)
    }

    @Test
    fun durationIsCapped() {
        assertEquals(StreamCapMs, streamDurationMs(5_000))
        assertTrue(streamDurationMs(10) < StreamCapMs)
    }
}
