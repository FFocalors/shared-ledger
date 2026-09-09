package com.ffocalors.sharedledger.data.common

/** Stable categories for read failures; UI must not infer these from translated messages. */
enum class ReadFailureKind {
    PermissionDenied,
    NotFound,
    Transient,
    Other,
}

/** Implemented by repository/read-layer failures that can safely drive cache policy. */
interface StructuredReadFailure {
    val failureKind: ReadFailureKind
}

fun Throwable.readFailureKind(): ReadFailureKind = generateSequence(this) { it.cause }
    .mapNotNull { (it as? StructuredReadFailure)?.failureKind }
    .firstOrNull()
    ?: ReadFailureKind.Other

fun ReadFailureKind.shouldRemoveCachedRead(): Boolean = when (this) {
    ReadFailureKind.PermissionDenied, ReadFailureKind.NotFound -> true
    ReadFailureKind.Transient, ReadFailureKind.Other -> false
}
