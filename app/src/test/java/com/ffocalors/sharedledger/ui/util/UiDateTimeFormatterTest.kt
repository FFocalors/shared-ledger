package com.ffocalors.sharedledger.ui.util

import org.junit.Assert.assertEquals
import org.junit.Test

class UiDateTimeFormatterTest {
    @Test
    fun formatsUtcAndOffsetTimestampsToUtcPlusEightMinutes() {
        assertEquals("2026-09-07 12:00", UiDateTimeFormatter.format("2026-09-07T04:00:41.179505+00:00"))
        assertEquals("2026-09-07 12:00", UiDateTimeFormatter.format("2026-09-07T12:00:59+08:00"))
    }

    @Test
    fun invalidOrPreviewTimestampFallsBackWithoutCrashing() {
        assertEquals("2026-09-07 04:00", UiDateTimeFormatter.format("2026-09-07 04:00"))
        assertEquals("not-a-time", UiDateTimeFormatter.format("not-a-time"))
    }
}
