package com.ffocalors.sharedledger.data.attachment

import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.data.common.StructuredReadFailure
import java.io.IOException
enum class AttachmentOperationStage {
    METADATA_CREATE,
    STORAGE_UPLOAD,
    STORAGE_DOWNLOAD,
    COMPLETE,
    STORAGE_DELETE,
    METADATA_DELETE,
}

open class AttachmentException(
    message: String,
    cause: Throwable? = null,
) : RuntimeException(message, cause), StructuredReadFailure {
    open override val failureKind: ReadFailureKind = ReadFailureKind.Other
}

class AttachmentContractException(message: String) : AttachmentException(message)

class AttachmentOperationException(
    val stage: AttachmentOperationStage,
    message: String,
    cause: Throwable? = null,
    override val failureKind: ReadFailureKind = ReadFailureKind.Other,
) : AttachmentException(message, cause)

object AttachmentErrorMapper {
    fun failureKind(error: Throwable): ReadFailureKind {
        if (error is StructuredReadFailure) return error.failureKind
        val text = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }
        return when {
            Regex("(?i)(?:sqlstate|errcode|\\\"code\\\"|\\bcode)\\s*[=: ]+\\\"?(28000|42501)").containsMatchIn(text) ->
                ReadFailureKind.PermissionDenied
            Regex("(?i)(?:sqlstate|errcode|\\\"code\\\"|\\bcode)\\s*[=: ]+\\\"?(P0002|PGRST116)").containsMatchIn(text) ->
                ReadFailureKind.NotFound
            error is IOException || text.contains("timeout", true) || text.contains("network", true) || text.contains("connect", true) ->
                ReadFailureKind.Transient
            else -> ReadFailureKind.Other
        }
    }
}
