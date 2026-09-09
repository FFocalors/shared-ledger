package com.ffocalors.sharedledger.data.attachment

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.util.Locale
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

data class PreparedAttachmentImage(
    val bytes: ByteArray,
    val mimeType: String,
    val filename: String,
    val sizeBytes: Int = bytes.size,
)

class AttachmentImageProcessingException(
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause)

/** Reads and prepares user-selected raster images for private Activity attachment upload. */
class AttachmentImageProcessor(
    private val maxEdge: Int = DEFAULT_MAX_EDGE,
) {
    init {
        require(maxEdge >= MIN_MAX_EDGE) { "maxEdge must be at least $MIN_MAX_EDGE" }
    }

    suspend fun process(
        contentResolver: ContentResolver,
        uri: Uri,
        filename: String,
    ): Result<PreparedAttachmentImage> = withContext(Dispatchers.IO) {
        try {
            processBlocking(contentResolver, uri, filename)
        } catch (error: kotlinx.coroutines.CancellationException) {
            throw error
        } catch (error: AttachmentImageProcessingException) {
            Result.failure(error)
        } catch (error: Exception) {
            Result.failure(AttachmentImageProcessingException("图片处理失败", error))
        }
    }

    private fun processBlocking(
        contentResolver: ContentResolver,
        uri: Uri,
        filename: String,
    ): Result<PreparedAttachmentImage> {
        val actualMimeType = sniffMimeType(contentResolver, uri)
            ?: return Result.failure(AttachmentImageProcessingException("仅支持 JPEG、PNG 或 WebP 图片"))
        val declaredMimeType = contentResolver.getType(uri)
        if (!isDeclaredMimeTypeConsistent(declaredMimeType, actualMimeType)) {
            return Result.failure(AttachmentImageProcessingException("图片类型与文件内容不一致"))
        }

        val bounds = readBounds(contentResolver, uri)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            return Result.failure(AttachmentImageProcessingException("图片为空或无法读取"))
        }
        val targetSize = targetSize(bounds.outWidth, bounds.outHeight, maxEdge)
        var bitmap = decode(contentResolver, uri, targetSize.first, targetSize.second)
        try {
            var currentMaxEdge = max(bitmap.width, bitmap.height)
            while (true) {
                val encoded = encode(bitmap, actualMimeType)
                if (encoded.size <= MAX_OUTPUT_BYTES) {
                    val output = PreparedAttachmentImage(
                        bytes = encoded,
                        mimeType = actualMimeType,
                        filename = normalizedFilename(filename, actualMimeType),
                    )
                    return Result.success(output)
                }
                if (currentMaxEdge <= MIN_MAX_EDGE) {
                    return Result.failure(AttachmentImageProcessingException("图片压缩后仍超过 10 MiB"))
                }
                val nextMaxEdge = max(MIN_MAX_EDGE, currentMaxEdge / 2)
                val scaled = scaleToMaxEdge(bitmap, nextMaxEdge)
                if (scaled === bitmap) {
                    return Result.failure(AttachmentImageProcessingException("图片压缩失败"))
                }
                bitmap.recycle()
                bitmap = scaled
                currentMaxEdge = max(bitmap.width, bitmap.height)
            }
        } finally {
            if (!bitmap.isRecycled) bitmap.recycle()
        }
    }

    private fun sniffMimeType(contentResolver: ContentResolver, uri: Uri): String? {
        val header = ByteArray(12)
        val count = contentResolver.openInputStream(uri)?.use { input -> readAtMost(input, header) } ?: 0
        if (count == 0) return null
        return attachmentImageMimeFromHeader(header.copyOf(count))
    }

    private fun readBounds(contentResolver: ContentResolver, uri: Uri): BitmapFactory.Options {
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        val decoded = contentResolver.openInputStream(uri)?.use { input ->
            BitmapFactory.decodeStream(input, null, options)
        }
        if (decoded != null) {
            decoded.recycle()
        }
        return options
    }

    private fun decode(
        contentResolver: ContentResolver,
        uri: Uri,
        targetWidth: Int,
        targetHeight: Int,
    ): Bitmap {
        val source = ImageDecoder.createSource(contentResolver, uri)
        return ImageDecoder.decodeBitmap(source) { decoder, _, _ ->
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            decoder.memorySizePolicy = ImageDecoder.MEMORY_POLICY_LOW_RAM
            decoder.setTargetSize(targetWidth, targetHeight)
        }
    }

    private fun encode(bitmap: Bitmap, mimeType: String): ByteArray {
        val format = when (mimeType) {
            MIME_JPEG -> Bitmap.CompressFormat.JPEG
            MIME_PNG -> Bitmap.CompressFormat.PNG
            MIME_WEBP -> Bitmap.CompressFormat.WEBP_LOSSLESS
            else -> error("Unsupported image MIME type: $mimeType")
        }
        val quality = if (mimeType == MIME_JPEG) JPEG_QUALITY else 100
        return ByteArrayOutputStream().use { output ->
            check(bitmap.compress(format, quality, output)) { "图片编码失败" }
            output.toByteArray()
        }
    }

    private fun scaleToMaxEdge(bitmap: Bitmap, targetMaxEdge: Int): Bitmap {
        val currentMaxEdge = max(bitmap.width, bitmap.height)
        if (currentMaxEdge <= targetMaxEdge) return bitmap
        val scale = targetMaxEdge.toFloat() / currentMaxEdge.toFloat()
        val width = max(1, (bitmap.width * scale).roundToInt())
        val height = max(1, (bitmap.height * scale).roundToInt())
        return Bitmap.createScaledBitmap(bitmap, width, height, true)
    }

    companion object {
        const val MIME_JPEG = "image/jpeg"
        const val MIME_PNG = "image/png"
        const val MIME_WEBP = "image/webp"
        const val MAX_OUTPUT_BYTES = 10 * 1024 * 1024
        const val DEFAULT_MAX_EDGE = 2048
        const val MIN_MAX_EDGE = 256
        private const val JPEG_QUALITY = 88
    }
}

internal fun attachmentImageMimeFromHeader(header: ByteArray): String? = when {
    header.size >= 3 &&
        header[0] == 0xFF.toByte() && header[1] == 0xD8.toByte() && header[2] == 0xFF.toByte() ->
        AttachmentImageProcessor.MIME_JPEG
    header.size >= 8 &&
        header.copyOfRange(0, 8).contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)) ->
        AttachmentImageProcessor.MIME_PNG
    header.size >= 12 &&
        header.copyOfRange(0, 4).contentEquals("RIFF".encodeToByteArray()) &&
        header.copyOfRange(8, 12).contentEquals("WEBP".encodeToByteArray()) ->
        AttachmentImageProcessor.MIME_WEBP
    else -> null
}

internal fun canonicalAttachmentImageMimeType(value: String?): String? = when (value?.trim()?.lowercase(Locale.ROOT)) {
    "image/jpg", "image/jpeg", "image/pjpeg" -> AttachmentImageProcessor.MIME_JPEG
    "image/png" -> AttachmentImageProcessor.MIME_PNG
    "image/webp", "image/x-webp" -> AttachmentImageProcessor.MIME_WEBP
    else -> null
}

internal fun isDeclaredMimeTypeConsistent(declared: String?, actual: String): Boolean {
    val raw = declared?.trim()?.lowercase(Locale.ROOT)
    if (raw.isNullOrBlank() || raw == "application/octet-stream") return true
    return canonicalAttachmentImageMimeType(raw) == actual
}

internal fun targetSize(width: Int, height: Int, maxEdge: Int): Pair<Int, Int> {
    require(width > 0 && height > 0 && maxEdge > 0)
    val scale = min(1f, maxEdge.toFloat() / max(width, height).toFloat())
    return max(1, (width * scale).roundToInt()) to max(1, (height * scale).roundToInt())
}

internal fun normalizedFilename(filename: String, mimeType: String): String {
    val fallbackStem = "attachment"
    val rawName = filename.substringAfterLast('/').substringAfterLast('\\').trim()
    val stem = rawName.substringBeforeLast('.', rawName)
        .replace(Regex("[^A-Za-z0-9._-]"), "_")
        .trim('.')
        .ifBlank { fallbackStem }
    val extension = when (mimeType) {
        AttachmentImageProcessor.MIME_JPEG -> "jpg"
        AttachmentImageProcessor.MIME_PNG -> "png"
        AttachmentImageProcessor.MIME_WEBP -> "webp"
        else -> "bin"
    }
    return "$stem.$extension"
}

private fun readAtMost(input: InputStream, buffer: ByteArray): Int {
    var offset = 0
    while (offset < buffer.size) {
        val count = input.read(buffer, offset, buffer.size - offset)
        if (count <= 0) break
        offset += count
    }
    return offset
}
