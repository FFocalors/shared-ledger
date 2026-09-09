package com.ffocalors.sharedledger.data.attachment

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal object AttachmentRpcPayloadBuilder {
    fun create(input: CreateAttachmentInput) = buildJsonObject {
        put("activity_id", input.activityId)
        put("ledger_unit_id", input.ledgerUnitId)
        input.expenseId?.let { put("expense_id", it) }
        input.filename?.let { put("filename", it) }
        put("mime_type", input.mimeType)
        put("size_bytes", input.sizeBytes)
    }

    fun attachmentId(attachmentId: String) = buildJsonObject {
        put("attachment_id", attachmentId)
    }
}
