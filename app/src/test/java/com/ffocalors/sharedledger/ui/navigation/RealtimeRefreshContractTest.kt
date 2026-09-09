package com.ffocalors.sharedledger.ui.navigation

import com.ffocalors.sharedledger.ui.attachment.AttachmentClientItem
import com.ffocalors.sharedledger.ui.attachment.AttachmentClientStatus
import com.ffocalors.sharedledger.ui.attachment.AttachmentScope
import com.ffocalors.sharedledger.ui.attachment.AttachmentUiState
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RealtimeRefreshContractTest {
    @Test
    fun externalAttachmentRefreshSkipsLocalBytesOrWrites() {
        assertTrue(canReloadExternalAttachments(AttachmentUiState()))
        assertFalse(canReloadExternalAttachments(AttachmentUiState(isWriting = true)))

        val localItem = AttachmentClientItem(
            clientId = "local-1",
            scope = AttachmentScope("activity-1", "ledger-1"),
            fileName = "receipt.jpg",
            mimeType = "image/jpeg",
            sizeBytes = 1L,
            status = AttachmentClientStatus.Pending,
            bytes = byteArrayOf(1),
        )
        assertFalse(canReloadExternalAttachments(AttachmentUiState(items = listOf(localItem))))
    }
}
