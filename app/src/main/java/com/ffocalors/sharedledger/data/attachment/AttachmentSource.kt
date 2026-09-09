package com.ffocalors.sharedledger.data.attachment

import android.content.ContentResolver
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import java.io.File
import java.io.IOException
import java.util.Locale
import java.util.UUID

/** The activity-wide attachment limit enforced by the Android client. */
object AttachmentPickerLimits {
    const val MAX_ATTACHMENTS = 10

    fun remainingSlots(
        existingCount: Int,
        maxAttachments: Int = MAX_ATTACHMENTS,
    ): Int = (maxAttachments - existingCount.coerceAtLeast(0)).coerceAtLeast(0)

    fun <T> limitSelection(
        selectedItems: List<T>,
        existingCount: Int,
        maxAttachments: Int = MAX_ATTACHMENTS,
    ): List<T> = selectedItems.take(remainingSlots(existingCount, maxAttachments))
}

/**
 * Photo Picker contract with a list result for both the one-image and multi-image cases.
 * A caller should create it with the current number of attachments and launch it only when
 * [AttachmentPickerLimits.remainingSlots] is greater than zero.
 */
class AttachmentPhotoPickerContract(
    private val maxItems: Int,
) : ActivityResultContract<Unit, List<Uri>>() {
    init {
        require(maxItems > 0) { "maxItems must be greater than zero" }
    }

    private val request = PickVisualMediaRequest(
        ActivityResultContracts.PickVisualMedia.ImageOnly,
    )
    private val singleContract = ActivityResultContracts.PickVisualMedia()
    private val multipleContract = ActivityResultContracts.PickMultipleVisualMedia(maxItems.coerceAtLeast(2))

    override fun createIntent(context: Context, input: Unit): android.content.Intent =
        if (maxItems == 1) {
            singleContract.createIntent(context, request)
        } else {
            multipleContract.createIntent(context, request)
        }

    override fun parseResult(resultCode: Int, intent: android.content.Intent?): List<Uri> {
        val selected = if (maxItems == 1) {
            singleContract.parseResult(resultCode, intent)?.let(::listOf).orEmpty()
        } else {
            multipleContract.parseResult(resultCode, intent)
        }
        return selected.take(maxItems)
    }
}

fun attachmentPhotoPickerContract(existingCount: Int): AttachmentPhotoPickerContract? =
    AttachmentPickerLimits.remainingSlots(existingCount).takeIf { it > 0 }
        ?.let(::AttachmentPhotoPickerContract)

/** Resolves provider metadata into a safe, stable name for upload metadata and UI. */
fun resolveAttachmentDisplayName(
    contentResolver: ContentResolver,
    uri: Uri,
    fallbackBaseName: String = "attachment",
): String {
    val providerName = runCatching {
        contentResolver.query(
            uri,
            arrayOf(OpenableColumns.DISPLAY_NAME),
            null,
            null,
            null,
        )?.use(::readDisplayName)
    }.getOrNull()
    val uriName = uri.lastPathSegment?.substringAfterLast('/').orEmpty()
    val candidate = providerName?.takeIf(String::isNotBlank) ?: uriName
    val fallbackStem = fallbackBaseName.trim().ifBlank { "attachment" }
    val fallback = if (fallbackStem.substringAfterLast('.', "").isNotBlank()) {
        fallbackStem
    } else {
        val mimeType = runCatching { contentResolver.getType(uri) }.getOrNull()
        "$fallbackStem.${extensionForMimeType(mimeType)}"
    }
    return sanitizeAttachmentFilename(candidate, fallback)
}

private fun readDisplayName(cursor: Cursor): String? {
    val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
    return if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
}

internal fun sanitizeAttachmentFilename(value: String?, fallbackBaseName: String = "attachment"): String {
    val raw = value.orEmpty().trim()
        .substringAfterLast('/')
        .substringAfterLast('\\')
    val sanitized = raw.map { character ->
        if (character.isISOControl() || character in FORBIDDEN_FILENAME_CHARACTERS) '_' else character
    }.joinToString("").trim('.', ' ')
    return sanitized.takeIf(String::isNotBlank)
        ?: fallbackBaseName.map { character ->
            if (character.isISOControl() || character in FORBIDDEN_FILENAME_CHARACTERS) '_' else character
        }.joinToString("").trim('.', ' ').ifBlank { "attachment" }
}

/** A camera output file and its FileProvider URI. Call [cleanup] after cancellation or upload. */
class AttachmentCameraCapture internal constructor(
    val uri: Uri,
    val displayName: String,
    internal val file: File,
) {
    fun cleanup(): Boolean = !file.exists() || file.delete()
}

class AttachmentCameraFileManager(context: Context) {
    private val applicationContext = context.applicationContext
    private val captureDirectory = File(applicationContext.cacheDir, CAMERA_DIRECTORY)
    private val authority = "${applicationContext.packageName}${FILE_PROVIDER_SUFFIX}"

    /** Creates a private cache file and a URI suitable for ActivityResultContracts.TakePicture. */
    fun createCapture(): AttachmentCameraCapture {
        if (!captureDirectory.exists() && !captureDirectory.mkdirs() && !captureDirectory.isDirectory) {
            throw IOException("无法创建相机临时目录")
        }
        val file = File(captureDirectory, cameraCaptureFilename())
        if (!file.createNewFile()) {
            throw IOException("无法创建相机临时文件")
        }
        return try {
            AttachmentCameraCapture(
                uri = FileProvider.getUriForFile(applicationContext, authority, file),
                displayName = file.name,
                file = file,
            )
        } catch (cause: Throwable) {
            file.delete()
            throw cause
        }
    }

    fun cleanup(capture: AttachmentCameraCapture): Boolean = capture.cleanup()

    /** Removes abandoned camera files, for example after process death or a canceled flow. */
    fun cleanupAbandonedCaptures(): Int = captureDirectory.listFiles()
        ?.count { it.isFile && it.delete() }
        ?: 0

    companion object {
        private const val CAMERA_DIRECTORY = "attachment-camera"
        const val FILE_PROVIDER_SUFFIX = ".fileprovider"
    }
}

internal fun cameraCaptureFilename(
    timestampMillis: Long = System.currentTimeMillis(),
    id: String = UUID.randomUUID().toString().replace('-', '_'),
): String = "camera_${timestampMillis}_$id.jpg"

private val FORBIDDEN_FILENAME_CHARACTERS = "<>:\"/\\|?*".toSet()

private fun extensionForMimeType(mimeType: String?): String = when (
    mimeType?.lowercase(Locale.ROOT)
) {
    AttachmentImageProcessor.MIME_PNG -> "png"
    AttachmentImageProcessor.MIME_WEBP -> "webp"
    else -> "jpg"
}
