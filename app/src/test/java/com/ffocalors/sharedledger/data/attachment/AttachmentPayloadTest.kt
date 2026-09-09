package com.ffocalors.sharedledger.data.attachment

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AttachmentPayloadTest {
    @Test
    fun createPayloadKeepsNullableExpenseOmitted() {
        val payload = AttachmentRpcPayloadBuilder.create(
            CreateAttachmentInput(
                activityId = "activity-1",
                ledgerUnitId = "unit-1",
                expenseId = null,
                filename = "receipt.webp",
                mimeType = "image/webp",
                sizeBytes = 42,
            ),
        )

        assertEquals("activity-1", payload["activity_id"]?.jsonPrimitive?.content)
        assertEquals("unit-1", payload["ledger_unit_id"]?.jsonPrimitive?.content)
        assertEquals("receipt.webp", payload["filename"]?.jsonPrimitive?.content)
        assertEquals("image/webp", payload["mime_type"]?.jsonPrimitive?.content)
        assertEquals("42", payload["size_bytes"]?.jsonPrimitive?.content)
        assertTrue(payload["expense_id"] == null || payload["expense_id"] == JsonNull)
    }

    @Test
    fun rowMapperPreservesServerStorageLocationAndStatus() {
        val metadata = AttachmentRowDto(
            id = "attachment-1",
            activityId = "activity-1",
            ledgerUnitId = "unit-1",
            expenseId = null,
            originalFilename = "receipt.jpg",
            mimeType = "image/jpeg",
            sizeBytes = 128,
            storageBucket = ACTIVITY_ATTACHMENTS_BUCKET,
            storagePath = "server/allocated/path.jpg",
            status = "ready",
            uploadedBy = "user-1",
            createdAt = "2026-09-07T00:00:00Z",
        ).toAttachmentMetadata()

        assertEquals(ACTIVITY_ATTACHMENTS_BUCKET, metadata.storageBucket)
        assertEquals("server/allocated/path.jpg", metadata.storagePath)
        assertEquals(AttachmentStatus.READY, metadata.status)
    }

    @Test
    fun pendingStateRetainsServerPathForSafeRetryAndCleanup() {
        val metadata = AttachmentMetadata(
            attachmentId = "attachment-1",
            activityId = "activity-1",
            ledgerUnitId = "unit-1",
            expenseId = null,
            originalFilename = "receipt.png",
            mimeType = "image/png",
            sizeBytes = 64,
            storageBucket = ACTIVITY_ATTACHMENTS_BUCKET,
            storagePath = "server/allocated/path.png",
            status = AttachmentStatus.PENDING,
        )
        val pending = PendingAttachmentUpload(
            metadata = metadata,
            storageState = AttachmentStorageState.UNKNOWN,
            message = "上传结果未知",
        )

        assertEquals("server/allocated/path.png", pending.metadata.storagePath)
        assertEquals(AttachmentStorageState.UNKNOWN, pending.storageState)
        assertEquals("attachment-1", AttachmentRpcPayloadBuilder.attachmentId("attachment-1")["attachment_id"]?.jsonPrimitive?.content)

        val partial = AttachmentDeleteResult.PartialFailure(
            attachmentId = "attachment-1",
            storageObjectDeleted = true,
            metadataDeleted = false,
            bucket = ACTIVITY_ATTACHMENTS_BUCKET,
            path = pending.metadata.storagePath,
            message = "待恢复",
        )
        assertTrue(partial.storageObjectDeleted)
        assertTrue(!partial.metadataDeleted)
    }

    @Test
    fun completeResponseLossIsRecoveredWhenExactReadIsReady() {
        val pending = PendingAttachmentUpload(
            metadata = metadata(AttachmentStatus.PENDING, "activity-1"),
            storageState = AttachmentStorageState.UPLOADED,
            message = "响应丢失",
        )
        val ready = metadata(AttachmentStatus.READY, "activity-1")

        val result = reconcileAttachmentCompletion(pending, completeResponse = null, reread = ready)

        assertEquals(AttachmentUploadResult.Completed(ready), result)
    }

    @Test
    fun completeReconciliationKeepsPendingAndRejectsWrongScope() {
        val pending = PendingAttachmentUpload(
            metadata = metadata(AttachmentStatus.PENDING, "activity-1"),
            storageState = AttachmentStorageState.UPLOADED,
            message = "响应未知",
        )
        val stillPending = reconcileAttachmentCompletion(
            pending,
            completeResponse = false,
            reread = metadata(AttachmentStatus.PENDING, "activity-1"),
        )
        val wrongScope = reconcileAttachmentCompletion(
            pending,
            completeResponse = false,
            reread = metadata(AttachmentStatus.READY, "activity-other"),
        )

        assertTrue(stillPending is AttachmentUploadResult.Pending)
        assertTrue(wrongScope is AttachmentUploadResult.Failed)
    }

    private fun metadata(status: AttachmentStatus, activityId: String) = AttachmentMetadata(
        attachmentId = "attachment-1",
        activityId = activityId,
        ledgerUnitId = "unit-1",
        expenseId = null,
        originalFilename = "receipt.jpg",
        mimeType = "image/jpeg",
        sizeBytes = 3,
        storageBucket = ACTIVITY_ATTACHMENTS_BUCKET,
        storagePath = "server/path.jpg",
        status = status,
    )
}
