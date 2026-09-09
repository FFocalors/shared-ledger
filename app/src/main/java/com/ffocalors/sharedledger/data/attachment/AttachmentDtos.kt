package com.ffocalors.sharedledger.data.attachment

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
internal data class AttachmentRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("ledger_unit_id") val ledgerUnitId: String,
    @SerialName("expense_id") val expenseId: String? = null,
    @SerialName("original_filename") val originalFilename: String? = null,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    @SerialName("storage_bucket") val storageBucket: String,
    @SerialName("storage_path") val storagePath: String,
    val status: String,
    @SerialName("uploaded_by") val uploadedBy: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("completed_at") val completedAt: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
internal data class CreateAttachmentRpcDto(
    @SerialName("attachment_id") val attachmentId: String,
    val bucket: String,
    val path: String,
    val status: String,
)

internal fun AttachmentRowDto.toAttachmentMetadata(): AttachmentMetadata = AttachmentMetadata(
    attachmentId = id,
    activityId = activityId,
    ledgerUnitId = ledgerUnitId,
    expenseId = expenseId,
    originalFilename = originalFilename,
    mimeType = mimeType,
    sizeBytes = sizeBytes,
    storageBucket = storageBucket,
    storagePath = storagePath,
    status = AttachmentStatus.fromDatabaseValue(status),
    uploadedBy = uploadedBy,
    createdAt = createdAt,
    completedAt = completedAt,
    deletedAt = deletedAt,
)
