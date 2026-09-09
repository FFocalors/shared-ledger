package com.ffocalors.sharedledger.ui.attachment

import com.ffocalors.sharedledger.data.attachment.AttachmentDeleteResult
import com.ffocalors.sharedledger.data.attachment.AttachmentMetadata
import com.ffocalors.sharedledger.data.attachment.AttachmentRepository
import com.ffocalors.sharedledger.data.attachment.AttachmentStatus
import com.ffocalors.sharedledger.data.attachment.AttachmentStorageState
import com.ffocalors.sharedledger.data.attachment.AttachmentUploadResult
import com.ffocalors.sharedledger.data.attachment.CreateAttachmentInput
import com.ffocalors.sharedledger.data.attachment.PendingAttachmentUpload
import com.ffocalors.sharedledger.data.attachment.PreparedAttachmentImage
import com.ffocalors.sharedledger.ui.screens.ExpenseAttachmentUploadStatus
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AttachmentViewModelTest {
    @Test
    fun archivedScopeRejectsAddUploadAndDeleteWithoutCallingRepository() = runBlocking {
        val repository = FakeAttachmentRepository()
        val viewModel = AttachmentViewModel(repository)
        viewModel.writesEnabled = false
        val scope = viewModel.beginExpenseDraft("activity-1", "unit-1").scope!!

        val add = viewModel.addPreparedImage(scope, prepared())
        val upload = viewModel.uploadExpenseAttachments("expense-1")

        assertTrue(add is AttachmentWriteResult.RejectedArchived)
        assertTrue(upload is AttachmentBatchResult.RejectedArchived)
        assertEquals(0, repository.createCalls)
    }

    @Test
    fun pendingUploadKeepsBytesForRetryAndMapsToTypedUiStates() = runBlocking {
        val repository = FakeAttachmentRepository()
        val viewModel = AttachmentViewModel(repository)
        val scope = viewModel.beginExpenseDraft("activity-1", "unit-1").scope!!
        val added = viewModel.addPreparedImage(scope, prepared()) as AttachmentWriteResult.Accepted
        val serverMetadata = metadata("attachment-1", "expense-1", AttachmentStatus.READY)
        repository.createResult = AttachmentUploadResult.Pending(
            PendingAttachmentUpload(
                metadata = serverMetadata.copy(status = AttachmentStatus.PENDING),
                storageState = AttachmentStorageState.UPLOADED,
                message = "完成确认结果未知",
            ),
        )

        val batch = viewModel.uploadExpenseAttachments("expense-1")
        val pendingItem = viewModel.uiState.value.items.single()
        assertTrue(batch is AttachmentBatchResult.Partial)
        assertEquals(AttachmentClientStatus.Pending, pendingItem.status)
        assertArrayEquals(byteArrayOf(1, 2, 3), pendingItem.bytes)
        assertEquals(ExpenseAttachmentUploadStatus.Pending, pendingItem.toNewExpenseUiState().status)
        assertEquals(com.ffocalors.sharedledger.ui.screens.ExpenseAttachmentStatus.Failed, pendingItem.toExpenseDetailUiState().status)
        assertEquals(com.ffocalors.sharedledger.ui.screens.LedgerAttachmentStatus.Failed, pendingItem.toLedgerUnitUiState().status)
        assertEquals(false, pendingItem.toNewExpenseUiState(canDelete = false).canRemove)
        assertEquals(false, pendingItem.toExpenseDetailUiState(canDelete = false).canDelete)
        assertEquals(false, pendingItem.toLedgerUnitUiState(canDelete = false).canDelete)

        repository.retryResult = AttachmentUploadResult.Completed(serverMetadata)
        val retry = viewModel.retryAttachment(added.clientId)

        assertTrue(retry is AttachmentWriteResult.Accepted)
        assertEquals(AttachmentClientStatus.Ready, viewModel.uiState.value.items.single().status)
        assertEquals(null, viewModel.uiState.value.items.single().bytes)
        assertEquals(1, repository.retryCalls)
    }

    @Test
    fun clientLimitCountsPendingAndReadyItems() = runBlocking {
        val viewModel = AttachmentViewModel(FakeAttachmentRepository())
        val scope = viewModel.beginExpenseDraft("activity-1", "unit-1").scope!!

        repeat(MAX_CLIENT_ATTACHMENTS) {
            assertTrue(viewModel.addPreparedImage(scope, prepared()).isAccepted())
        }
        val rejected = viewModel.addPreparedImage(scope, prepared())

        assertTrue(rejected is AttachmentWriteResult.RejectedLimit)
        assertEquals(MAX_CLIENT_ATTACHMENTS, viewModel.uiState.value.items.size)
    }

    @Test
    fun partialDeleteKeepsItemForRecovery() = runBlocking {
        val repository = FakeAttachmentRepository()
        val viewModel = AttachmentViewModel(repository)
        val scope = AttachmentScope("activity-1", "unit-1", "expense-1")
        viewModel.loadExpenseNow("activity-1", "unit-1", "expense-1")
        repository.listResult = Result.success(listOf(metadata("attachment-1", "expense-1", AttachmentStatus.READY)))
        viewModel.loadExpenseNow("activity-1", "unit-1", "expense-1")
        repository.deleteResult = AttachmentDeleteResult.PartialFailure(
            attachmentId = "attachment-1",
            storageObjectDeleted = true,
            metadataDeleted = false,
            bucket = "activity-attachments",
            path = "server/path.jpg",
            message = "metadata 待恢复",
        )

        val result = viewModel.deleteAttachment("attachment-1")

        assertTrue(result is AttachmentWriteResult.Failed)
        assertEquals(1, viewModel.uiState.value.items.size)
        assertEquals(AttachmentClientStatus.Failed, viewModel.uiState.value.items.single().status)
        assertEquals("metadata 待恢复", viewModel.uiState.value.items.single().errorMessage)
        assertEquals(false, viewModel.uiState.value.items.single().deleteRecovery?.metadataDeleted)
        assertEquals(scope.expenseId, viewModel.uiState.value.scope?.expenseId)
    }

    @Test
    fun readyAttachmentCanLoadPrivateBytesAndLedgerScopeStaysExpenseNull() = runBlocking {
        val repository = FakeAttachmentRepository()
        repository.listResult = Result.success(listOf(metadata("attachment-1", null, AttachmentStatus.READY)))
        val viewModel = AttachmentViewModel(repository)

        viewModel.loadLedgerUnitNow("activity-1", "unit-1")
        val bytes = viewModel.downloadReady("attachment-1")

        assertArrayEquals(byteArrayOf(4, 5), bytes.getOrThrow())
        assertEquals(null, viewModel.uiState.value.scope?.expenseId)
        assertTrue(viewModel.uiState.value.scope?.isLedgerUnitAttachment == true)
        assertEquals(AttachmentClientStatus.Ready, viewModel.uiState.value.items.single().status)
    }

    @Test
    fun ledgerUnitUploadsWithNullExpenseIdAndCanRetryPendingBytes() = runBlocking {
        val repository = FakeAttachmentRepository()
        val viewModel = AttachmentViewModel(repository)
        viewModel.loadLedgerUnitNow("activity-1", "unit-1")
        val scope = viewModel.uiState.value.scope!!
        val added = viewModel.addPreparedImage(scope, prepared()) as AttachmentWriteResult.Accepted
        repository.createResult = AttachmentUploadResult.Pending(
            PendingAttachmentUpload(
                metadata = metadata("attachment-1", null, AttachmentStatus.PENDING),
                storageState = AttachmentStorageState.UPLOADED,
                message = "完成确认结果未知",
            ),
        )

        val pending = viewModel.uploadLedgerUnitAttachments()

        assertTrue(pending is AttachmentBatchResult.Partial)
        assertEquals(null, repository.lastCreateInput?.expenseId)
        assertEquals(AttachmentClientStatus.Pending, viewModel.uiState.value.items.single().status)
        assertArrayEquals(byteArrayOf(1, 2, 3), viewModel.uiState.value.items.single().bytes)

        repository.retryResult = AttachmentUploadResult.Completed(metadata("attachment-1", null, AttachmentStatus.READY))
        assertTrue(viewModel.retryAttachment(added.clientId) is AttachmentWriteResult.Accepted)
        assertEquals(1, repository.retryCalls)
        assertEquals(AttachmentClientStatus.Ready, viewModel.uiState.value.items.single().status)
    }

    @Test
    fun deletedRowsAreFilteredAndScopeSwitchDoesNotReuseOldLimit() = runBlocking {
        val repository = FakeAttachmentRepository()
        repository.listResult = Result.success(
            listOf(
                metadata("ready", "expense-1", AttachmentStatus.READY),
                metadata("deleted", "expense-1", AttachmentStatus.DELETED),
            ),
        )
        val viewModel = AttachmentViewModel(repository)
        viewModel.loadExpenseNow("activity-1", "unit-1", "expense-1")
        assertEquals(listOf("ready"), viewModel.uiState.value.items.map { it.clientId })

        val fullScope = viewModel.beginExpenseDraft("activity-1", "unit-1").scope!!
        repeat(MAX_CLIENT_ATTACHMENTS) { viewModel.addPreparedImage(fullScope, prepared()) }
        val otherScope = AttachmentScope("activity-2", "unit-2", null, AttachmentScopeKind.LedgerUnit)
        assertTrue(viewModel.addPreparedImage(otherScope, prepared()) is AttachmentWriteResult.Accepted)
        assertEquals(1, viewModel.uiState.value.items.size)
        assertEquals("activity-2", viewModel.uiState.value.scope?.activityId)
    }

    private fun prepared() = PreparedAttachmentImage(
        bytes = byteArrayOf(1, 2, 3),
        mimeType = "image/jpeg",
        filename = "receipt.jpg",
    )

    private fun metadata(id: String, expenseId: String?, status: AttachmentStatus) = AttachmentMetadata(
        attachmentId = id,
        activityId = "activity-1",
        ledgerUnitId = "unit-1",
        expenseId = expenseId,
        originalFilename = "receipt.jpg",
        mimeType = "image/jpeg",
        sizeBytes = 3,
        storageBucket = "activity-attachments",
        storagePath = "server/path.jpg",
        status = status,
    )

    private fun AttachmentWriteResult.isAccepted() = this is AttachmentWriteResult.Accepted
}

private class FakeAttachmentRepository : AttachmentRepository {
    var createResult: AttachmentUploadResult = AttachmentUploadResult.Failed(
        com.ffocalors.sharedledger.data.attachment.AttachmentOperationStage.METADATA_CREATE,
        "未配置测试结果",
    )
    var retryResult: AttachmentUploadResult = createResult
    var deleteResult: AttachmentDeleteResult = AttachmentDeleteResult.Deleted("attachment-1")
    var listResult: Result<List<AttachmentMetadata>> = Result.success(emptyList())
    var createCalls = 0
    var retryCalls = 0
    var lastCreateInput: CreateAttachmentInput? = null

    override suspend fun listByActivity(activityId: String) = listResult
    override suspend fun listByExpense(activityId: String, expenseId: String) = listResult
    override suspend fun listByLedgerUnit(activityId: String, ledgerUnitId: String) = listResult
    override suspend fun download(attachment: AttachmentMetadata) = Result.success(byteArrayOf(4, 5))
    override suspend fun createAndUpload(input: CreateAttachmentInput, bytes: ByteArray): AttachmentUploadResult {
        createCalls++
        lastCreateInput = input
        return createResult
    }
    override suspend fun retryPending(pending: PendingAttachmentUpload, bytes: ByteArray): AttachmentUploadResult {
        retryCalls++
        return retryResult
    }
    override suspend fun cleanupPending(pending: PendingAttachmentUpload) = deleteResult
    override suspend fun delete(attachment: AttachmentMetadata) = deleteResult
}
