package com.ffocalors.sharedledger.data.attachment

import org.junit.Assert.assertEquals
import org.junit.Test

class AttachmentSourceTest {
    @Test
    fun remainingSlotsNeverExceedsActivityLimit() {
        assertEquals(10, AttachmentPickerLimits.remainingSlots(0))
        assertEquals(3, AttachmentPickerLimits.remainingSlots(7))
        assertEquals(0, AttachmentPickerLimits.remainingSlots(11))
        assertEquals(0, AttachmentPickerLimits.remainingSlots(-1, maxAttachments = 0))
    }

    @Test
    fun limitSelectionKeepsOnlyAvailableSlots() {
        val selected = (1..4).toList()
        assertEquals(selected.take(2), AttachmentPickerLimits.limitSelection(selected, existingCount = 8))
    }

    @Test
    fun filenamesAreSafeAndCameraNamesAreStable() {
        assertEquals("receipt_2026.jpg", sanitizeAttachmentFilename("../receipt:2026.jpg"))
        assertEquals("attachment", sanitizeAttachmentFilename("...", fallbackBaseName = "attachment"))
        assertEquals(
            "camera_12345_capture_id.jpg",
            cameraCaptureFilename(timestampMillis = 12345, id = "capture_id"),
        )
    }
}
