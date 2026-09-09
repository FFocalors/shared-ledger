package com.ffocalors.sharedledger.ui.attachment

import android.content.ContentResolver
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.attachment.AttachmentImageProcessor
import com.ffocalors.sharedledger.data.attachment.AttachmentDeleteResult
import com.ffocalors.sharedledger.data.attachment.AttachmentMetadata
import com.ffocalors.sharedledger.data.attachment.AttachmentOperationStage
import com.ffocalors.sharedledger.data.attachment.AttachmentRepository
import com.ffocalors.sharedledger.data.attachment.AttachmentRepositoryFactory
import com.ffocalors.sharedledger.data.attachment.AttachmentUploadResult
import com.ffocalors.sharedledger.data.attachment.CreateAttachmentInput
import com.ffocalors.sharedledger.data.attachment.PendingAttachmentUpload
import com.ffocalors.sharedledger.data.attachment.PreparedAttachmentImage
import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.data.common.readFailureKind
import com.ffocalors.sharedledger.data.common.shouldRemoveCachedRead
import com.ffocalors.sharedledger.ui.cache.QueryCacheKey
import com.ffocalors.sharedledger.ui.cache.QueryCacheState
import com.ffocalors.sharedledger.ui.cache.SessionQueryCache
import com.ffocalors.sharedledger.ui.screens.ExpenseAttachmentDraftUiState
import com.ffocalors.sharedledger.ui.screens.ExpenseAttachmentStatus
import com.ffocalors.sharedledger.ui.screens.ExpenseAttachmentUiState
import com.ffocalors.sharedledger.ui.screens.ExpenseAttachmentUploadStatus
import com.ffocalors.sharedledger.ui.screens.LedgerAttachmentStatus
import com.ffocalors.sharedledger.ui.screens.LedgerAttachmentUiState
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

const val MAX_CLIENT_ATTACHMENTS = 10

enum class AttachmentScopeKind {
    Expense,
    LedgerUnit,
}

data class AttachmentScope(
    val activityId: String,
    val ledgerUnitId: String,
    val expenseId: String? = null,
    val kind: AttachmentScopeKind = AttachmentScopeKind.Expense,
) {
    val isLedgerUnitAttachment: Boolean
        get() = kind == AttachmentScopeKind.LedgerUnit
}

enum class AttachmentClientStatus {
    Pending,
    Uploading,
    Ready,
    Failed,
}

data class AttachmentClientItem(
    val clientId: String,
    val scope: AttachmentScope,
    val fileName: String,
    val mimeType: String,
    val sizeBytes: Long,
    val status: AttachmentClientStatus,
    val metadata: AttachmentMetadata? = null,
    val bytes: ByteArray? = null,
    val pendingUpload: PendingAttachmentUpload? = null,
    val deleteRecovery: AttachmentDeleteResult.PartialFailure? = null,
    val errorMessage: String? = null,
)

data class AttachmentUiState(
    val scope: AttachmentScope? = null,
    val isLoading: Boolean = false,
    val isWriting: Boolean = false,
    val items: List<AttachmentClientItem> = emptyList(),
    val errorMessage: String? = null,
    val failureKind: ReadFailureKind? = null,
)

sealed interface AttachmentWriteResult {
    data class Accepted(val clientId: String) : AttachmentWriteResult
    data class RejectedArchived(val message: String = "活动已归档，附件不可修改") : AttachmentWriteResult
    data class RejectedLimit(val message: String = "附件最多保留 10 个") : AttachmentWriteResult
    data class RejectedInvalid(val message: String) : AttachmentWriteResult
    data class Failed(val clientId: String?, val message: String) : AttachmentWriteResult
}

sealed interface AttachmentBatchResult {
    data class Completed(val uploadedIds: List<String>) : AttachmentBatchResult
    data class Partial(val uploadedIds: List<String>, val pendingIds: List<String>, val failedIds: List<String>) : AttachmentBatchResult
    data class RejectedArchived(val message: String = "活动已归档，附件不可修改") : AttachmentBatchResult
    data class Failed(val message: String) : AttachmentBatchResult
}

class AttachmentViewModel(
    private val repository: AttachmentRepository = AttachmentRepositoryFactory.create(),
    private val imageProcessor: AttachmentImageProcessor = AttachmentImageProcessor(),
    private val queryCache: SessionQueryCache = SessionQueryCache(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(AttachmentUiState())
    val uiState: StateFlow<AttachmentUiState> = _uiState.asStateFlow()
    private val locallyManagedIds = mutableSetOf<String>()
    private val locallyDeletedIds = mutableSetOf<String>()

    /** The host sets this from the authoritative activity state before exposing write actions. */
    var writesEnabled: Boolean = true

    fun loadExpense(activityId: String, ledgerUnitId: String, expenseId: String): Job =
        viewModelScope.launch { loadExpenseNow(activityId, ledgerUnitId, expenseId) }

    suspend fun loadExpenseNow(activityId: String, ledgerUnitId: String, expenseId: String): Result<Unit> {
        val scope = AttachmentScope(activityId, ledgerUnitId, expenseId, AttachmentScopeKind.Expense)
        return loadScope(
            scope = scope,
            key = expenseCacheKey(activityId, expenseId),
            loader = { repository.listByExpense(activityId, expenseId) },
        )
    }

    fun loadLedgerUnit(activityId: String, ledgerUnitId: String): Job =
        viewModelScope.launch { loadLedgerUnitNow(activityId, ledgerUnitId) }

    suspend fun loadLedgerUnitNow(activityId: String, ledgerUnitId: String): Result<Unit> {
        val scope = AttachmentScope(activityId, ledgerUnitId, null, AttachmentScopeKind.LedgerUnit)
        return loadScope(
            scope = scope,
            key = ledgerUnitCacheKey(activityId, ledgerUnitId),
            loader = { repository.listByLedgerUnit(activityId, ledgerUnitId) },
        )
    }

    private suspend fun loadScope(
        scope: AttachmentScope,
        key: QueryCacheKey<List<AttachmentMetadata>>,
        loader: suspend () -> Result<List<AttachmentMetadata>>,
    ): Result<Unit> {
        val cached = queryCache.read(key)
        cached.value?.let { metadata ->
            if (_uiState.value.scope != scope) {
                _uiState.value = AttachmentUiState(scope = scope)
            }
            showRemote(scope, metadata)
        }
        when {
            cached.state == QueryCacheState.Fresh && cached.value != null -> return Result.success(Unit)
            cached.state == QueryCacheState.Stale && cached.value != null -> {
                refreshInBackground(scope, key, loader)
                return Result.success(Unit)
            }
        }

        // A miss is the only state that presents initial loading. Keep local write items
        // when reloading the same scope so a cache miss cannot erase a pending upload.
        if (_uiState.value.scope != scope) {
            _uiState.value = AttachmentUiState(scope = scope, isLoading = true)
        } else {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
        }
        return queryCache.getOrLoad(key, loader = loader).fold(
            onSuccess = { metadata ->
                showRemote(scope, metadata, authoritative = true)
                Result.success(Unit)
            },
            onFailure = { error ->
                handleReadFailure(scope, key, error)
                Result.failure(error)
            },
        )
    }

    private fun refreshInBackground(
        scope: AttachmentScope,
        key: QueryCacheKey<List<AttachmentMetadata>>,
        loader: suspend () -> Result<List<AttachmentMetadata>>,
    ) {
        viewModelScope.launch {
            queryCache.getOrLoad(key, forceRefresh = true, loader = loader).fold(
                onSuccess = { metadata -> showRemote(scope, metadata, authoritative = true) },
                onFailure = { error ->
                    handleReadFailure(scope, key, error)
                },
            )
        }
    }

    private fun showRemote(
        scope: AttachmentScope,
        metadata: List<AttachmentMetadata>,
        authoritative: Boolean = false,
    ) {
        if (_uiState.value.scope != scope) return
        if (authoritative) {
            val returnedIds = metadata.map { it.attachmentId }.toSet()
            locallyDeletedIds.removeAll { it !in returnedIds }
        }
        _uiState.value = _uiState.value.copy(
            isLoading = false,
            items = mergeRemote(scope, metadata),
            errorMessage = null,
        )
    }

    private fun handleReadFailure(
        scope: AttachmentScope,
        key: QueryCacheKey<List<AttachmentMetadata>>,
        error: Throwable,
    ) {
        if (_uiState.value.scope != scope) return
        val kind = error.readFailureKind()
        val message = error.message ?: "加载附件失败"
        if (kind.shouldRemoveCachedRead()) {
            queryCache.remove(key)
            _uiState.value = AttachmentUiState(
                scope = scope,
                isLoading = false,
                errorMessage = message,
                failureKind = kind,
            )
        } else {
            _uiState.value = _uiState.value.copy(
                isLoading = false,
                errorMessage = message,
                failureKind = kind,
            )
        }
    }

    private fun mergeRemote(scope: AttachmentScope, metadata: List<AttachmentMetadata>): List<AttachmentClientItem> {
        val visibleMetadata = metadata.filterNot {
            it.status == com.ffocalors.sharedledger.data.attachment.AttachmentStatus.DELETED ||
                it.attachmentId in locallyDeletedIds
        }
        val remoteIds = visibleMetadata.map { it.attachmentId }.toSet()
        val existing = _uiState.value.items.filter { it.scope == scope }
        val existingByServerId = existing.mapNotNull { item ->
            item.serverAttachmentId()?.let { it to item }
        }.toMap()
        val remoteItems = visibleMetadata.map { item ->
            val remoteItem = item.toClientItem(scope)
            existingByServerId[item.attachmentId]
                ?.takeIf { it.hasLocalWriteState() }
                ?.copy(scope = scope)
                ?: remoteItem
        }
        val localOnlyItems = existing.filter { item ->
            val serverId = item.serverAttachmentId()
            val isLocal = locallyManagedIds.contains(item.clientId) ||
                serverId?.let(locallyManagedIds::contains) == true ||
                item.hasLocalWriteState()
            isLocal && (serverId == null || serverId !in remoteIds) &&
                (serverId == null || serverId !in locallyDeletedIds)
        }
        locallyManagedIds.removeAll { id ->
            id in remoteIds && existingByServerId[id]?.hasLocalWriteState() != true
        }
        return (remoteItems + localOnlyItems).distinctBy { it.clientId }
    }

    private fun AttachmentClientItem.serverAttachmentId(): String? =
        metadata?.attachmentId ?: pendingUpload?.metadata?.attachmentId

    private fun AttachmentClientItem.hasLocalWriteState(): Boolean =
        bytes != null || pendingUpload != null || deleteRecovery != null ||
            status == AttachmentClientStatus.Uploading || status == AttachmentClientStatus.Failed ||
            errorMessage != null

    private fun expenseCacheKey(activityId: String, expenseId: String) =
        QueryCacheKey<List<AttachmentMetadata>>("attachment-query:$activityId:expense:$expenseId")

    private fun ledgerUnitCacheKey(activityId: String, ledgerUnitId: String) =
        QueryCacheKey<List<AttachmentMetadata>>("attachment-query:$activityId:ledger:$ledgerUnitId")

    private fun invalidateScope(scope: AttachmentScope) {
        if (scope.isLedgerUnitAttachment) {
            queryCache.invalidate(ledgerUnitCacheKey(scope.activityId, scope.ledgerUnitId))
        } else {
            scope.expenseId?.let { queryCache.invalidate(expenseCacheKey(scope.activityId, it)) }
        }
    }

    /** Invalidates all expense and LedgerUnit attachment reads for an activity. */
    fun invalidateActivityAttachments(activityId: String) {
        queryCache.invalidatePrefix("attachment-query:$activityId:")
    }

    /** Invalidates one expense attachment domain without touching LedgerUnit attachments. */
    fun invalidateExpenseAttachments(activityId: String, expenseId: String) {
        queryCache.invalidate(expenseCacheKey(activityId, expenseId))
    }

    /** Invalidates one standalone LedgerUnit attachment domain. */
    fun invalidateLedgerUnitAttachments(activityId: String, ledgerUnitId: String) {
        queryCache.invalidate(ledgerUnitCacheKey(activityId, ledgerUnitId))
    }

    fun clearSessionCache() = queryCache.clear()

    fun beginExpenseDraft(activityId: String, ledgerUnitId: String): AttachmentUiState {
        val scope = AttachmentScope(activityId, ledgerUnitId, null, AttachmentScopeKind.Expense)
        _uiState.value = AttachmentUiState(scope = scope)
        return _uiState.value
    }

    suspend fun addImage(
        contentResolver: ContentResolver,
        uri: Uri,
        filename: String,
    ): AttachmentWriteResult {
        if (!writesEnabled) return AttachmentWriteResult.RejectedArchived()
        if (_uiState.value.items.size >= MAX_CLIENT_ATTACHMENTS) return AttachmentWriteResult.RejectedLimit()
        val scope = _uiState.value.scope ?: return AttachmentWriteResult.RejectedInvalid("附件作用域尚未建立")
        val prepared = imageProcessor.process(contentResolver, uri, filename)
            .getOrElse { return AttachmentWriteResult.RejectedInvalid(it.message ?: "图片处理失败") }
        return addPreparedImage(scope, prepared)
    }

    suspend fun addPreparedImage(
        scope: AttachmentScope,
        prepared: PreparedAttachmentImage,
    ): AttachmentWriteResult {
        if (!writesEnabled) return AttachmentWriteResult.RejectedArchived()
        if (_uiState.value.scope != scope) {
            _uiState.value = AttachmentUiState(scope = scope)
        }
        if (_uiState.value.items.size >= MAX_CLIENT_ATTACHMENTS) return AttachmentWriteResult.RejectedLimit()
        val clientId = "local-${UUID.randomUUID()}"
        val item = AttachmentClientItem(
            clientId = clientId,
            scope = scope,
            fileName = prepared.filename,
            mimeType = prepared.mimeType,
            sizeBytes = prepared.sizeBytes.toLong(),
            status = AttachmentClientStatus.Pending,
            bytes = prepared.bytes,
        )
        _uiState.value = _uiState.value.copy(items = _uiState.value.items + item, errorMessage = null)
        locallyManagedIds += clientId
        return AttachmentWriteResult.Accepted(clientId)
    }

    suspend fun uploadExpenseAttachments(expenseId: String): AttachmentBatchResult {
        if (!writesEnabled) return AttachmentBatchResult.RejectedArchived()
        val current = _uiState.value
        val scope = current.scope ?: return AttachmentBatchResult.Failed("附件作用域尚未建立")
        if (scope.isLedgerUnitAttachment) return AttachmentBatchResult.Failed("独立 Ledger 附件不能绑定到账单")
        if (scope.expenseId != null && scope.expenseId != expenseId) return AttachmentBatchResult.Failed("附件不属于该账单")
        return uploadPendingAttachments(scope.copy(expenseId = expenseId), expenseId)
    }

    suspend fun uploadLedgerUnitAttachments(): AttachmentBatchResult {
        if (!writesEnabled) return AttachmentBatchResult.RejectedArchived()
        val scope = _uiState.value.scope ?: return AttachmentBatchResult.Failed("附件作用域尚未建立")
        if (!scope.isLedgerUnitAttachment) return AttachmentBatchResult.Failed("账单附件不能作为独立 Ledger 附件")
        return uploadPendingAttachments(scope.copy(expenseId = null), null)
    }

    private suspend fun uploadPendingAttachments(
        targetScope: AttachmentScope,
        expenseId: String?,
    ): AttachmentBatchResult {
        val current = _uiState.value
        val candidates = current.items.filter { it.metadata == null || it.pendingUpload != null }
        if (candidates.isEmpty()) {
            _uiState.value = current.copy(scope = targetScope)
            return AttachmentBatchResult.Completed(emptyList())
        }
        _uiState.value = current.copy(scope = targetScope, isWriting = true, errorMessage = null)
        val uploaded = mutableListOf<String>()
        val pending = mutableListOf<String>()
        val failed = mutableListOf<String>()
        candidates.forEach { item ->
            if (item.metadata != null && item.status == AttachmentClientStatus.Ready) return@forEach
            updateItem(item.clientId) { it.copy(scope = targetScope, status = AttachmentClientStatus.Uploading, errorMessage = null) }
            val bytes = item.bytes ?: run {
                failed += item.clientId
                updateItem(item.clientId) {
                    it.copy(status = AttachmentClientStatus.Failed, errorMessage = "本地附件字节已丢失，请重新选择图片")
                }
                return@forEach
            }
            val result = try {
                item.pendingUpload?.let { pendingUpload ->
                    repository.retryPending(pendingUpload, bytes)
                } ?: repository.createAndUpload(
                    CreateAttachmentInput(
                        activityId = targetScope.activityId,
                        ledgerUnitId = targetScope.ledgerUnitId,
                        expenseId = expenseId,
                        filename = item.fileName,
                        mimeType = item.mimeType,
                        sizeBytes = item.sizeBytes,
                    ),
                    bytes,
                )
            } catch (cause: CancellationException) {
                throw cause
            } catch (cause: Throwable) {
                AttachmentUploadResult.Failed(
                    AttachmentOperationStage.METADATA_CREATE,
                    cause.message ?: "附件上传失败",
                    cause,
                )
            }
            when (result) {
                is AttachmentUploadResult.Completed -> {
                    uploaded += item.clientId
                    locallyManagedIds += item.clientId
                    locallyManagedIds += result.metadata.attachmentId
                    updateItem(item.clientId) {
                        it.copy(
                            scope = targetScope,
                            metadata = result.metadata,
                            status = AttachmentClientStatus.Ready,
                            bytes = null,
                            pendingUpload = null,
                        )
                    }
                }
                is AttachmentUploadResult.Pending -> {
                    pending += item.clientId
                    locallyManagedIds += item.clientId
                    locallyManagedIds += result.upload.metadata.attachmentId
                    updateItem(item.clientId) {
                        it.copy(
                            scope = targetScope,
                            status = AttachmentClientStatus.Pending,
                            pendingUpload = result.upload,
                            errorMessage = result.upload.message,
                        )
                    }
                }
                is AttachmentUploadResult.Failed -> {
                    failed += item.clientId
                    locallyManagedIds += item.clientId
                    updateItem(item.clientId) {
                        it.copy(
                            scope = targetScope,
                            status = AttachmentClientStatus.Failed,
                            errorMessage = result.message,
                        )
                    }
                }
            }
        }
        _uiState.value = _uiState.value.copy(isWriting = false)
        invalidateScope(targetScope)
        return if (pending.isEmpty() && failed.isEmpty()) {
            AttachmentBatchResult.Completed(uploaded)
        } else {
            AttachmentBatchResult.Partial(uploaded, pending, failed)
        }
    }

    suspend fun deleteAttachment(clientId: String): AttachmentWriteResult {
        if (!writesEnabled) return AttachmentWriteResult.RejectedArchived()
        val item = _uiState.value.items.firstOrNull { it.clientId == clientId }
            ?: return AttachmentWriteResult.Failed(clientId, "未找到附件")
        if (item.metadata == null && item.pendingUpload == null) {
            removeItem(clientId)
            return AttachmentWriteResult.Accepted(clientId)
        }
        val metadata = item.metadata ?: item.pendingUpload?.metadata
            ?: return AttachmentWriteResult.Failed(clientId, "附件状态不可恢复")
        locallyDeletedIds += metadata.attachmentId
        val result = try {
            if (item.pendingUpload != null) {
                repository.cleanupPending(item.pendingUpload)
            } else {
                repository.delete(metadata)
            }
        } catch (cause: Throwable) {
            locallyDeletedIds -= metadata.attachmentId
            throw cause
        }
        return when (result) {
            is com.ffocalors.sharedledger.data.attachment.AttachmentDeleteResult.Deleted -> {
                removeItem(clientId)
                invalidateScope(item.scope)
                AttachmentWriteResult.Accepted(clientId)
            }
            is com.ffocalors.sharedledger.data.attachment.AttachmentDeleteResult.PartialFailure -> {
                locallyDeletedIds -= metadata.attachmentId
                updateItem(clientId) {
                    it.copy(
                        status = AttachmentClientStatus.Failed,
                        deleteRecovery = result,
                        errorMessage = result.message,
                    )
                }
                AttachmentWriteResult.Failed(clientId, result.message)
            }
        }
    }

    suspend fun retryAttachment(clientId: String): AttachmentWriteResult {
        if (!writesEnabled) return AttachmentWriteResult.RejectedArchived()
        val item = _uiState.value.items.firstOrNull { it.clientId == clientId }
            ?: return AttachmentWriteResult.Failed(clientId, "未找到附件")
        val bytes = item.bytes ?: return AttachmentWriteResult.Failed(clientId, "附件字节已丢失，请重新选择图片")
        val pending = item.pendingUpload
        val result = if (pending != null) {
            updateItem(clientId) { it.copy(status = AttachmentClientStatus.Uploading, errorMessage = null) }
            repository.retryPending(pending, bytes)
        } else {
            val scope = _uiState.value.scope
                ?: return AttachmentWriteResult.Failed(clientId, "附件作用域尚未建立")
            val expenseId = if (scope.isLedgerUnitAttachment) null else scope.expenseId
                ?: return AttachmentWriteResult.Failed(clientId, "账单尚未创建，无法上传附件")
            updateItem(clientId) { it.copy(status = AttachmentClientStatus.Uploading, errorMessage = null) }
            repository.createAndUpload(
                CreateAttachmentInput(
                    activityId = item.scope.activityId,
                    ledgerUnitId = item.scope.ledgerUnitId,
                    expenseId = expenseId,
                    filename = item.fileName,
                    mimeType = item.mimeType,
                    sizeBytes = item.sizeBytes,
                ),
                bytes,
            )
        }
        return applyUploadResult(item, result)
    }

    suspend fun cleanupPending(clientId: String): AttachmentWriteResult {
        if (!writesEnabled) return AttachmentWriteResult.RejectedArchived()
        val item = _uiState.value.items.firstOrNull { it.clientId == clientId }
            ?: return AttachmentWriteResult.Failed(clientId, "未找到附件")
        val pending = item.pendingUpload
            ?: return AttachmentWriteResult.Failed(clientId, "附件没有待清理上传")
        locallyDeletedIds += pending.metadata.attachmentId
        val result = try {
            repository.cleanupPending(pending)
        } catch (cause: Throwable) {
            locallyDeletedIds -= pending.metadata.attachmentId
            throw cause
        }
        return when (result) {
            is com.ffocalors.sharedledger.data.attachment.AttachmentDeleteResult.Deleted -> {
                removeItem(clientId)
                invalidateScope(item.scope)
                AttachmentWriteResult.Accepted(clientId)
            }
            is com.ffocalors.sharedledger.data.attachment.AttachmentDeleteResult.PartialFailure -> {
                locallyDeletedIds -= pending.metadata.attachmentId
                updateItem(clientId) {
                    it.copy(status = AttachmentClientStatus.Failed, deleteRecovery = result, errorMessage = result.message)
                }
                AttachmentWriteResult.Failed(clientId, result.message)
            }
        }
    }

    suspend fun downloadReady(clientId: String): Result<ByteArray> {
        val item = _uiState.value.items.firstOrNull { it.clientId == clientId }
            ?: return Result.failure(IllegalArgumentException("未找到附件"))
        if (item.status != AttachmentClientStatus.Ready) {
            return Result.failure(IllegalStateException("附件尚未完成上传"))
        }
        item.bytes?.let { return Result.success(it) }
        val metadata = item.metadata
            ?: return Result.failure(IllegalStateException("附件尚未完成上传"))
        return repository.download(metadata).onSuccess { bytes ->
            updateItem(clientId) { it.copy(bytes = bytes) }
        }
    }

    private fun applyUploadResult(item: AttachmentClientItem, result: AttachmentUploadResult): AttachmentWriteResult =
        when (result) {
            is AttachmentUploadResult.Completed -> {
                locallyManagedIds += item.clientId
                locallyManagedIds += result.metadata.attachmentId
                updateItem(item.clientId) {
                    it.copy(
                        metadata = result.metadata,
                        status = AttachmentClientStatus.Ready,
                        bytes = null,
                        pendingUpload = null,
                        errorMessage = null,
                    )
                }
                invalidateScope(item.scope)
                AttachmentWriteResult.Accepted(item.clientId)
            }
            is AttachmentUploadResult.Pending -> {
                locallyManagedIds += item.clientId
                locallyManagedIds += result.upload.metadata.attachmentId
                updateItem(item.clientId) {
                    it.copy(status = AttachmentClientStatus.Pending, pendingUpload = result.upload, errorMessage = result.upload.message)
                }
                AttachmentWriteResult.Failed(item.clientId, result.upload.message)
            }
            is AttachmentUploadResult.Failed -> {
                locallyManagedIds += item.clientId
                updateItem(item.clientId) { it.copy(status = AttachmentClientStatus.Failed, errorMessage = result.message) }
                AttachmentWriteResult.Failed(item.clientId, result.message)
            }
        }

    private fun updateItem(clientId: String, transform: (AttachmentClientItem) -> AttachmentClientItem) {
        _uiState.value = _uiState.value.copy(items = _uiState.value.items.map { item ->
            if (item.clientId == clientId) transform(item) else item
        })
    }

    private fun removeItem(clientId: String) {
        _uiState.value = _uiState.value.copy(items = _uiState.value.items.filterNot { it.clientId == clientId })
    }

    class Factory(
        private val repository: AttachmentRepository = AttachmentRepositoryFactory.create(),
        private val queryCache: SessionQueryCache = SessionQueryCache(),
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(AttachmentViewModel::class.java))
            return AttachmentViewModel(repository, queryCache = queryCache) as T
        }
    }
}

private fun AttachmentMetadata.toClientItem(scope: AttachmentScope) = AttachmentClientItem(
    clientId = attachmentId,
    scope = scope,
    fileName = originalFilename ?: "附件",
    mimeType = mimeType,
    sizeBytes = sizeBytes,
    status = when (status) {
        com.ffocalors.sharedledger.data.attachment.AttachmentStatus.READY -> AttachmentClientStatus.Ready
        com.ffocalors.sharedledger.data.attachment.AttachmentStatus.PENDING -> AttachmentClientStatus.Pending
        com.ffocalors.sharedledger.data.attachment.AttachmentStatus.DELETED -> AttachmentClientStatus.Failed
    },
    metadata = this,
)

fun AttachmentClientItem.toNewExpenseUiState(canDelete: Boolean = true): ExpenseAttachmentDraftUiState = ExpenseAttachmentDraftUiState(
    attachmentId = clientId,
    fileName = fileName,
    sizeLabel = formatAttachmentSize(sizeBytes),
    status = when (status) {
        AttachmentClientStatus.Pending -> ExpenseAttachmentUploadStatus.Pending
        AttachmentClientStatus.Uploading -> ExpenseAttachmentUploadStatus.Uploading
        AttachmentClientStatus.Ready -> ExpenseAttachmentUploadStatus.Uploaded
        AttachmentClientStatus.Failed -> ExpenseAttachmentUploadStatus.Failed
    },
    errorMessage = errorMessage,
    canRemove = canDelete,
)

fun AttachmentClientItem.toExpenseDetailUiState(canDelete: Boolean = true): ExpenseAttachmentUiState = ExpenseAttachmentUiState(
    attachmentId = clientId,
    fileName = fileName,
    sizeLabel = formatAttachmentSize(sizeBytes),
    status = when (status) {
        AttachmentClientStatus.Uploading -> ExpenseAttachmentStatus.Uploading
        AttachmentClientStatus.Ready -> ExpenseAttachmentStatus.Ready
        AttachmentClientStatus.Pending, AttachmentClientStatus.Failed -> ExpenseAttachmentStatus.Failed
    },
    errorMessage = errorMessage,
    canDelete = canDelete,
)

fun AttachmentClientItem.toLedgerUnitUiState(canDelete: Boolean = true): LedgerAttachmentUiState = LedgerAttachmentUiState(
    attachmentId = clientId,
    fileName = fileName,
    sizeLabel = formatAttachmentSize(sizeBytes),
    status = when (status) {
        AttachmentClientStatus.Uploading -> LedgerAttachmentStatus.Uploading
        AttachmentClientStatus.Ready -> LedgerAttachmentStatus.Ready
        AttachmentClientStatus.Pending, AttachmentClientStatus.Failed -> LedgerAttachmentStatus.Failed
    },
    errorMessage = errorMessage,
    canDelete = canDelete,
)

fun AttachmentUiState.toNewExpenseUiState(canDelete: (AttachmentClientItem) -> Boolean = { true }): List<ExpenseAttachmentDraftUiState> = items.map { it.toNewExpenseUiState(canDelete(it)) }

fun AttachmentUiState.toExpenseDetailUiState(canDelete: (AttachmentClientItem) -> Boolean = { true }): List<ExpenseAttachmentUiState> = items.map { it.toExpenseDetailUiState(canDelete(it)) }

fun AttachmentUiState.toLedgerUnitUiState(canDelete: (AttachmentClientItem) -> Boolean = { true }): List<LedgerAttachmentUiState> = items.map { it.toLedgerUnitUiState(canDelete(it)) }

private fun formatAttachmentSize(sizeBytes: Long): String = when {
    sizeBytes < 1024L -> "$sizeBytes B"
    sizeBytes < 1024L * 1024L -> "${sizeBytes / 1024L} KB"
    else -> "${sizeBytes / (1024L * 1024L)} MB"
}
