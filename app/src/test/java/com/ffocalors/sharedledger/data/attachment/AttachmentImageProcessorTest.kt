package com.ffocalors.sharedledger.data.attachment

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AttachmentImageProcessorTest {
    @Test
    fun detectsSupportedImageHeaders() {
        assertEquals(
            AttachmentImageProcessor.MIME_JPEG,
            attachmentImageMimeFromHeader(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte())),
        )
        assertEquals(
            AttachmentImageProcessor.MIME_PNG,
            attachmentImageMimeFromHeader(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)),
        )
        assertEquals(
            AttachmentImageProcessor.MIME_WEBP,
            attachmentImageMimeFromHeader("RIFF0000WEBP".encodeToByteArray()),
        )
        assertNull(attachmentImageMimeFromHeader("GIF89a".encodeToByteArray()))
    }

    @Test
    fun rejectsDeclaredTypeThatDoesNotMatchFileHeader() {
        assertTrue(isDeclaredMimeTypeConsistent("image/jpeg", AttachmentImageProcessor.MIME_JPEG))
        assertTrue(isDeclaredMimeTypeConsistent(null, AttachmentImageProcessor.MIME_PNG))
        assertTrue(isDeclaredMimeTypeConsistent("application/octet-stream", AttachmentImageProcessor.MIME_WEBP))
        assertFalse(isDeclaredMimeTypeConsistent("image/jpeg", AttachmentImageProcessor.MIME_PNG))
        assertFalse(isDeclaredMimeTypeConsistent("image/gif", AttachmentImageProcessor.MIME_PNG))
    }

    @Test
    fun targetSizeKeepsAspectRatioAndDoesNotUpscale() {
        assertEquals(1600 to 1200, targetSize(4000, 3000, 1600))
        assertEquals(800 to 600, targetSize(800, 600, 1600))
    }

    @Test
    fun normalizedFilenameUsesDetectedTypeAndSafeStem() {
        assertEquals(
            "trip_photo.jpg",
            normalizedFilename("trip photo.png", AttachmentImageProcessor.MIME_JPEG),
        )
        assertEquals(
            "attachment.webp",
            normalizedFilename("", AttachmentImageProcessor.MIME_WEBP),
        )
    }
}
