package com.ffocalors.sharedledger.data.attachment

const val ACTIVITY_ATTACHMENTS_BUCKET = "activity-attachments"

enum class AttachmentStatus(val databaseValue: String) {
    PENDING("pending"),
    READY("ready"),
    DELETED("deleted"),
    ;

    companion object {
        fun fromDatabaseValue(value: String): AttachmentStatus =
            entries.firstOrNull { it.databaseValue == value }
                ?: throw AttachmentContractException("未知附件状态：$value")
    }
}

data class AttachmentMetadata(
    val attachmentId: String,
    val activityId: String,
    val ledgerUnitId: String,
    val expenseId: String?,
    val originalFilename: String?,
    val mimeType: String,
    val sizeBytes: Long,
    val storageBucket: String,
    val storagePath: String,
    val status: AttachmentStatus,
    val uploadedBy: String? = null,
    val createdAt: String? = null,
    val completedAt: String? = null,
    val deletedAt: String? = null,
)

data class CreateAttachmentInput(
    val activityId: String,
    val ledgerUnitId: String,
    val expenseId: String?,
    val filename: String?,
    val mimeType: String,
    val sizeBytes: Long,
)

enum class AttachmentStorageState {
    NOT_UPLOADED,
    UPLOADED,
    UNKNOWN,
}

data class PendingAttachmentUpload(
    val metadata: AttachmentMetadata,
    val storageState: AttachmentStorageState,
    val message: String,
)

sealed interface AttachmentUploadResult {
    data class Completed(val metadata: AttachmentMetadata) : AttachmentUploadResult
    data class Pending(val upload: PendingAttachmentUpload) : AttachmentUploadResult
    data class Failed(
        val stage: AttachmentOperationStage,
        val message: String,
        val cause: Throwable? = null,
    ) : AttachmentUploadResult
}

sealed interface AttachmentDeleteResult {
    data class Deleted(val attachmentId: String) : AttachmentDeleteResult
    data class PartialFailure(
        val attachmentId: String,
        val storageObjectDeleted: Boolean,
        val metadataDeleted: Boolean,
        val bucket: String,
        val path: String,
        val message: String,
        val cause: Throwable? = null,
    ) : AttachmentDeleteResult
}
