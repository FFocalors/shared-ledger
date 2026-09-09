package com.ffocalors.sharedledger.data.attachment

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
) : RuntimeException(message, cause)

class AttachmentContractException(message: String) : AttachmentException(message)

class AttachmentOperationException(
    val stage: AttachmentOperationStage,
    message: String,
    cause: Throwable? = null,
) : AttachmentException(message, cause)
