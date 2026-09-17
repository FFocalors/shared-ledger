package com.ffocalors.sharedledger.ui.attachment

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.SharedLedgerDialog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private sealed interface AttachmentPreviewState {
    data object Loading : AttachmentPreviewState
    data class Ready(val bitmap: Bitmap) : AttachmentPreviewState
    data class Failed(val message: String) : AttachmentPreviewState
}

@Composable
fun AttachmentImagePreviewDialog(
    bytes: ByteArray,
    filename: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    maxEdge: Int = DEFAULT_PREVIEW_MAX_EDGE,
) {
    val state by produceState<AttachmentPreviewState>(
        initialValue = AttachmentPreviewState.Loading,
        key1 = bytes,
        key2 = maxEdge,
    ) {
        value = withContext(Dispatchers.Default) {
            decodeAttachmentPreview(bytes, maxEdge)
                .fold(
                    onSuccess = { AttachmentPreviewState.Ready(it) },
                    onFailure = { AttachmentPreviewState.Failed("无法预览该图片") },
                )
        }
    }
    val bitmap = (state as? AttachmentPreviewState.Ready)?.bitmap
    DisposableEffect(bitmap) {
        onDispose {
            bitmap?.takeUnless(Bitmap::isRecycled)?.recycle()
        }
    }

    SharedLedgerDialog(
        onDismiss = onDismiss,
        title = filename,
        textContent = {
            Column(modifier = modifier) {
                when (val current = state) {
                    AttachmentPreviewState.Loading -> CircularProgressIndicator()
                    is AttachmentPreviewState.Ready -> Image(
                        bitmap = current.bitmap.asImageBitmap(),
                        contentDescription = filename,
                        modifier = Modifier.fillMaxWidth().heightIn(max = 480.dp),
                    )
                    is AttachmentPreviewState.Failed -> Text(
                        text = current.message,
                        modifier = Modifier.padding(8.dp),
                    )
                }
            }
        },
        dismissText = null,
        confirmText = "关闭",
        onConfirm = onDismiss,
    )
}

internal fun decodeAttachmentPreview(
    bytes: ByteArray,
    maxEdge: Int = DEFAULT_PREVIEW_MAX_EDGE,
): Result<Bitmap> = runCatching {
    require(bytes.isNotEmpty()) { "图片内容为空" }
    require(maxEdge > 0) { "maxEdge must be positive" }
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    require(bounds.outWidth > 0 && bounds.outHeight > 0) { "无法读取图片尺寸" }
    val options = BitmapFactory.Options().apply {
        inSampleSize = previewSampleSize(bounds.outWidth, bounds.outHeight, maxEdge)
        inPreferredConfig = Bitmap.Config.ARGB_8888
    }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
        ?: error("图片解码失败")
}

internal fun previewSampleSize(width: Int, height: Int, maxEdge: Int): Int {
    require(width > 0 && height > 0 && maxEdge > 0)
    var sample = 1
    val sourceEdge = maxOf(width, height)
    while (sourceEdge / sample > maxEdge && sample <= Int.MAX_VALUE / 2) {
        sample *= 2
    }
    return sample
}

private const val DEFAULT_PREVIEW_MAX_EDGE = 1600
