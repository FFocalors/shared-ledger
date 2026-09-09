package com.ffocalors.sharedledger.data.attachment

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import io.github.jan.supabase.storage.storage
import io.ktor.http.ContentType
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.buildJsonObject

interface AttachmentRepository {
    suspend fun listByActivity(activityId: String): Result<List<AttachmentMetadata>>
    suspend fun listByExpense(activityId: String, expenseId: String): Result<List<AttachmentMetadata>>
    suspend fun listByLedgerUnit(activityId: String, ledgerUnitId: String): Result<List<AttachmentMetadata>>
    suspend fun download(attachment: AttachmentMetadata): Result<ByteArray>
    suspend fun createAndUpload(input: CreateAttachmentInput, bytes: ByteArray): AttachmentUploadResult
    suspend fun retryPending(pending: PendingAttachmentUpload, bytes: ByteArray): AttachmentUploadResult
    suspend fun cleanupPending(pending: PendingAttachmentUpload): AttachmentDeleteResult
    suspend fun delete(attachment: AttachmentMetadata): AttachmentDeleteResult
}

class SupabaseAttachmentRepository(
    private val client: SupabaseClient,
) : AttachmentRepository {
    override suspend fun listByActivity(activityId: String): Result<List<AttachmentMetadata>> =
        readRows {
            client.from("attachments").select {
                filter { eq("activity_id", activityId) }
            }.decodeList<AttachmentRowDto>()
        }

    override suspend fun listByExpense(
        activityId: String,
        expenseId: String,
    ): Result<List<AttachmentMetadata>> = readRows {
        client.from("attachments").select {
            filter {
                eq("activity_id", activityId)
                eq("expense_id", expenseId)
            }
        }.decodeList<AttachmentRowDto>()
    }

    override suspend fun listByLedgerUnit(
        activityId: String,
        ledgerUnitId: String,
    ): Result<List<AttachmentMetadata>> = readRows {
        client.from("attachments").select {
            filter {
                eq("activity_id", activityId)
                eq("ledger_unit_id", ledgerUnitId)
            }
        }.decodeList<AttachmentRowDto>()
            .filter { it.expenseId == null }
    }

    override suspend fun download(attachment: AttachmentMetadata): Result<ByteArray> = runCatching {
        validateStorageLocation(attachment.storageBucket, attachment.storagePath)
        client.storage.from(attachment.storageBucket)
            .downloadAuthenticated(attachment.storagePath)
    }.mapFailure(AttachmentOperationStage.STORAGE_DOWNLOAD)

    override suspend fun createAndUpload(
        input: CreateAttachmentInput,
        bytes: ByteArray,
    ): AttachmentUploadResult {
        if (input.sizeBytes != bytes.size.toLong()) {
            return AttachmentUploadResult.Failed(
                stage = AttachmentOperationStage.METADATA_CREATE,
                message = "附件大小与元数据不一致",
            )
        }
        val allocation = try {
            client.postgrest.rpc("create_attachment", AttachmentRpcPayloadBuilder.create(input))
                .decodeSingle<CreateAttachmentRpcDto>()
        } catch (cause: Throwable) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.METADATA_CREATE,
                "创建附件元数据失败",
                cause,
            )
        }
        val status = try {
            AttachmentStatus.fromDatabaseValue(allocation.status)
        } catch (cause: Throwable) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.METADATA_CREATE,
                "附件元数据返回了未知状态",
                cause,
            )
        }
        if (status != AttachmentStatus.PENDING || allocation.bucket != ACTIVITY_ATTACHMENTS_BUCKET) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.METADATA_CREATE,
                "附件元数据未返回可上传的 pending 记录",
            )
        }
        if (allocation.path.isBlank()) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.METADATA_CREATE,
                "附件元数据未返回 storage path",
            )
        }
        val metadata = AttachmentMetadata(
            attachmentId = allocation.attachmentId,
            activityId = input.activityId,
            ledgerUnitId = input.ledgerUnitId,
            expenseId = input.expenseId,
            originalFilename = input.filename,
            mimeType = input.mimeType,
            sizeBytes = input.sizeBytes,
            storageBucket = allocation.bucket,
            storagePath = allocation.path,
            status = AttachmentStatus.PENDING,
        )
        return uploadPending(PendingAttachmentUpload(metadata, AttachmentStorageState.NOT_UPLOADED, ""), bytes)
    }

    override suspend fun retryPending(
        pending: PendingAttachmentUpload,
        bytes: ByteArray,
    ): AttachmentUploadResult {
        if (pending.metadata.status != AttachmentStatus.PENDING) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.COMPLETE,
                "只有 pending 附件可以重试",
            )
        }
        if (pending.metadata.sizeBytes != bytes.size.toLong()) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.STORAGE_UPLOAD,
                "附件大小与原始元数据不一致",
            )
        }
        return uploadPending(pending, bytes)
    }

    private suspend fun uploadPending(
        pending: PendingAttachmentUpload,
        bytes: ByteArray,
    ): AttachmentUploadResult {
        val metadata = pending.metadata
        try {
            validateStorageLocation(metadata.storageBucket, metadata.storagePath)
        } catch (cause: Throwable) {
            return AttachmentUploadResult.Failed(
                AttachmentOperationStage.STORAGE_UPLOAD,
                "附件 storage location 无效",
                cause,
            )
        }

        var state = pending.storageState
        if (state == AttachmentStorageState.UNKNOWN) {
            try {
                client.storage.from(metadata.storageBucket).delete(metadata.storagePath)
                state = AttachmentStorageState.NOT_UPLOADED
            } catch (cause: Throwable) {
                return AttachmentUploadResult.Pending(
                    pending.copy(
                        message = "无法确认并清理上次上传结果，请稍后重试或清理",
                    ),
                )
            }
        }
        if (state == AttachmentStorageState.NOT_UPLOADED) {
            try {
                client.storage.from(metadata.storageBucket).upload(metadata.storagePath, bytes) {
                    upsert = false
                    contentType = ContentType.parse(metadata.mimeType)
                }
                state = AttachmentStorageState.UPLOADED
            } catch (cause: Throwable) {
                return AttachmentUploadResult.Pending(
                    pending.copy(
                        storageState = AttachmentStorageState.UNKNOWN,
                        message = "上传结果未知，请先重试或清理 pending 附件",
                    ),
                )
            }
        }
        val completed = try {
            client.postgrest.rpc(
                "complete_attachment",
                AttachmentRpcPayloadBuilder.attachmentId(metadata.attachmentId),
            ).decodeSingle<Boolean>()
        } catch (cause: CancellationException) {
            throw cause
        } catch (_: Throwable) {
            null
        }
        val reread = if (completed == true) {
            null
        } else {
            readCompletionMetadata(metadata)
        }
        return reconcileAttachmentCompletion(
            pending = pending,
            completeResponse = completed,
            reread = reread,
        )
    }

    private suspend fun readCompletionMetadata(metadata: AttachmentMetadata): AttachmentMetadata? =
        runCatching {
            client.from("attachments").select {
                filter {
                    eq("id", metadata.attachmentId)
                    eq("activity_id", metadata.activityId)
                }
            }.decodeList<AttachmentRowDto>()
                .singleOrNull()
                ?.toAttachmentMetadata()
        }.getOrNull()

    override suspend fun cleanupPending(pending: PendingAttachmentUpload): AttachmentDeleteResult =
        deleteParts(pending.metadata)

    override suspend fun delete(attachment: AttachmentMetadata): AttachmentDeleteResult =
        deleteParts(attachment)

    private suspend fun deleteParts(metadata: AttachmentMetadata): AttachmentDeleteResult {
        validateStorageLocation(metadata.storageBucket, metadata.storagePath)
        var storageDeleted = false
        var metadataDeleted = false
        var firstFailure: AttachmentOperationException? = null
        try {
            client.storage.from(metadata.storageBucket).delete(metadata.storagePath)
            storageDeleted = true
        } catch (cause: Throwable) {
            firstFailure = AttachmentOperationException(
                AttachmentOperationStage.STORAGE_DELETE,
                "删除附件对象失败",
                cause,
            )
        }
        try {
            metadataDeleted = client.postgrest.rpc(
                "delete_attachment",
                AttachmentRpcPayloadBuilder.attachmentId(metadata.attachmentId),
            ).decodeSingle<Boolean>()
            if (!metadataDeleted) {
                firstFailure = firstFailure ?: AttachmentOperationException(
                    AttachmentOperationStage.METADATA_DELETE,
                    "附件元数据未被删除",
                )
            }
        } catch (cause: Throwable) {
            firstFailure = firstFailure ?: AttachmentOperationException(
                AttachmentOperationStage.METADATA_DELETE,
                "删除附件元数据失败",
                cause,
            )
        }
        return if (storageDeleted && metadataDeleted) {
            AttachmentDeleteResult.Deleted(metadata.attachmentId)
        } else {
            AttachmentDeleteResult.PartialFailure(
                attachmentId = metadata.attachmentId,
                storageObjectDeleted = storageDeleted,
                metadataDeleted = metadataDeleted,
                bucket = metadata.storageBucket,
                path = metadata.storagePath,
                message = "附件删除部分完成，请按结果重试剩余步骤",
                cause = firstFailure,
            )
        }
    }

    private suspend fun readRows(loader: suspend () -> List<AttachmentRowDto>): Result<List<AttachmentMetadata>> =
        runCatching { loader().map(AttachmentRowDto::toAttachmentMetadata) }

    private fun validateStorageLocation(bucket: String, path: String) {
        require(bucket == ACTIVITY_ATTACHMENTS_BUCKET) { "附件 bucket 不符合冻结契约" }
        require(path.isNotBlank()) { "附件 storage path 为空" }
    }

    private fun <T> Result<T>.mapFailure(stage: AttachmentOperationStage): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = { cause ->
            if (cause is CancellationException) throw cause
            Result.failure(
                if (cause is AttachmentException) cause else AttachmentOperationException(
                    stage,
                    "附件操作失败",
                    cause,
                    AttachmentErrorMapper.failureKind(cause),
                ),
            )
        },
    )
}

/** Resolves an ambiguous complete response using an exact, RLS-protected metadata read. */
internal fun reconcileAttachmentCompletion(
    pending: PendingAttachmentUpload,
    completeResponse: Boolean?,
    reread: AttachmentMetadata?,
): AttachmentUploadResult {
    val original = pending.metadata
    if (reread != null &&
        (reread.attachmentId != original.attachmentId || reread.activityId != original.activityId)
    ) {
        return AttachmentUploadResult.Failed(
            AttachmentOperationStage.COMPLETE,
            "附件完成确认返回了错误作用域",
        )
    }
    if (completeResponse == true) {
        return AttachmentUploadResult.Completed(original.copy(status = AttachmentStatus.READY))
    }
    return when (reread?.status) {
        AttachmentStatus.READY -> AttachmentUploadResult.Completed(reread)
        AttachmentStatus.DELETED -> AttachmentUploadResult.Failed(
            AttachmentOperationStage.COMPLETE,
            "附件已被删除，无法完成上传",
        )
        AttachmentStatus.PENDING, null -> AttachmentUploadResult.Pending(
            pending.copy(
                metadata = reread ?: original,
                storageState = AttachmentStorageState.UPLOADED,
                message = if (reread == null) {
                    "附件完成确认结果未知，请重试完成操作"
                } else {
                    "附件仍处于 pending，请重试完成操作"
                },
            ),
        )
    }
}

object AttachmentRepositoryFactory {
    fun create(): AttachmentRepository =
        SupabaseClientProvider.createOrNull()?.let(::SupabaseAttachmentRepository)
            ?: UnavailableAttachmentRepository
}

private object UnavailableAttachmentRepository : AttachmentRepository {
    private fun unavailable(): Result<Nothing> = Result.failure(AttachmentException("Supabase 未配置"))

    override suspend fun listByActivity(activityId: String) = unavailable()
    override suspend fun listByExpense(activityId: String, expenseId: String) = unavailable()
    override suspend fun listByLedgerUnit(activityId: String, ledgerUnitId: String) = unavailable()
    override suspend fun download(attachment: AttachmentMetadata) = unavailable()
    override suspend fun createAndUpload(input: CreateAttachmentInput, bytes: ByteArray) =
        AttachmentUploadResult.Failed(AttachmentOperationStage.METADATA_CREATE, "Supabase 未配置")
    override suspend fun retryPending(pending: PendingAttachmentUpload, bytes: ByteArray) =
        AttachmentUploadResult.Failed(AttachmentOperationStage.METADATA_CREATE, "Supabase 未配置")
    override suspend fun cleanupPending(pending: PendingAttachmentUpload) =
        AttachmentDeleteResult.PartialFailure(
            pending.metadata.attachmentId,
            false,
            false,
            pending.metadata.storageBucket,
            pending.metadata.storagePath,
            "Supabase 未配置",
        )
    override suspend fun delete(attachment: AttachmentMetadata) =
        AttachmentDeleteResult.PartialFailure(
            attachment.attachmentId,
            false,
            false,
            attachment.storageBucket,
            attachment.storagePath,
            "Supabase 未配置",
        )
}
