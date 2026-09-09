package com.ffocalors.sharedledger.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AttachmentUiContractTest {
    @Test
    fun expenseDetailDoesNotInventAnAttachment() {
        assertTrue(ExpenseDetailUiState().attachments.isEmpty())
    }

    @Test
    fun newExpenseAttachmentLimitIsTen() {
        assertTrue(canAddExpenseAttachment(0))
        assertTrue(canAddExpenseAttachment(9))
        assertEquals(false, canAddExpenseAttachment(10))
    }

    @Test
    fun attachmentModelsExposeUploadFailureForHostFeedback() {
        val attachment = ExpenseAttachmentDraftUiState(
            attachmentId = "a1",
            fileName = "receipt.jpg",
            status = ExpenseAttachmentUploadStatus.Failed,
            errorMessage = "网络连接失败",
        )

        assertEquals("receipt.jpg", attachment.fileName)
        assertEquals("网络连接失败", attachment.errorMessage)
    }
}
