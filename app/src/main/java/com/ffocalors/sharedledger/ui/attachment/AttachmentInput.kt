package com.ffocalors.sharedledger.ui.attachment

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.ffocalors.sharedledger.data.attachment.AttachmentCameraCapture
import com.ffocalors.sharedledger.data.attachment.AttachmentCameraFileManager
import com.ffocalors.sharedledger.data.attachment.AttachmentPickerLimits
import com.ffocalors.sharedledger.data.attachment.AttachmentPhotoPickerContract
import com.ffocalors.sharedledger.data.attachment.resolveAttachmentDisplayName
import kotlinx.coroutines.launch

data class AttachmentInputSelection(
    val uri: Uri,
    val displayName: String,
    val isTemporaryCameraFile: Boolean = false,
)

@Stable
class AttachmentInputController internal constructor(
    val remainingSlots: Int,
    val isSourceChooserVisible: Boolean,
    val requestSourceChooser: () -> Unit,
    val dismissSourceChooser: () -> Unit,
    val launchGallery: () -> Unit,
    val launchCamera: () -> Unit,
)

/**
 * Registers the gallery and camera launchers and keeps their lifecycle local to the caller.
 * The callback is suspendable so a camera URI can be read before its private temp file is deleted.
 */
@Composable
fun rememberAttachmentInputController(
    currentCount: Int,
    onUrisSelected: suspend (List<AttachmentInputSelection>) -> Unit,
    onError: (Throwable) -> Unit = {},
): AttachmentInputController {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val remainingSlots = AttachmentPickerLimits.remainingSlots(currentCount)
    val cameraFileManager = remember(context) { AttachmentCameraFileManager(context) }
    val latestOnUrisSelected by rememberUpdatedState(onUrisSelected)
    val latestOnError by rememberUpdatedState(onError)
    var isSourceChooserVisible by remember { mutableStateOf(false) }
    val cameraCaptureState = remember { mutableStateOf<AttachmentCameraCapture?>(null) }
    var cameraCapture by cameraCaptureState

    val galleryLauncher = rememberLauncherForActivityResult(
        contract = remember(remainingSlots) {
            AttachmentPhotoPickerContract(remainingSlots.coerceAtLeast(1))
        },
    ) { uris ->
        isSourceChooserVisible = false
        val selected = AttachmentPickerLimits.limitSelection(uris, currentCount)
            .map { uri ->
                AttachmentInputSelection(
                    uri = uri,
                    displayName = resolveAttachmentDisplayName(context.contentResolver, uri),
                )
            }
        if (selected.isNotEmpty()) {
            scope.launch {
                runCatching { latestOnUrisSelected(selected) }
                    .onFailure(latestOnError)
            }
        }
    }

    val cameraLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture(),
    ) { success ->
        val capture = cameraCapture ?: return@rememberLauncherForActivityResult
        scope.launch {
            try {
                if (success) {
                    runCatching {
                        latestOnUrisSelected(
                            listOf(
                                AttachmentInputSelection(
                                    uri = capture.uri,
                                    displayName = capture.displayName,
                                    isTemporaryCameraFile = true,
                                ),
                            ),
                        )
                    }.onFailure(latestOnError)
                }
            } finally {
                cameraFileManager.cleanup(capture)
                cameraCapture = null
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            cameraCaptureState.value?.cleanup()
        }
    }

    fun requestSourceChooser() {
        if (remainingSlots > 0) {
            isSourceChooserVisible = true
        } else {
            latestOnError(IllegalStateException("附件最多保留 ${AttachmentPickerLimits.MAX_ATTACHMENTS} 个"))
        }
    }

    fun launchGallery() {
        isSourceChooserVisible = false
        if (remainingSlots > 0) {
            runCatching { galleryLauncher.launch(Unit) }
                .onFailure(latestOnError)
        } else {
            latestOnError(IllegalStateException("附件最多保留 ${AttachmentPickerLimits.MAX_ATTACHMENTS} 个"))
        }
    }

    fun launchCamera() {
        isSourceChooserVisible = false
        if (remainingSlots <= 0) {
            latestOnError(IllegalStateException("附件最多保留 ${AttachmentPickerLimits.MAX_ATTACHMENTS} 个"))
            return
        }
        runCatching { cameraFileManager.createCapture() }
            .onSuccess { capture ->
                cameraCapture = capture
                runCatching { cameraLauncher.launch(capture.uri) }
                    .onFailure {
                        cameraCapture = null
                        cameraFileManager.cleanup(capture)
                        latestOnError(it)
                    }
            }
            .onFailure(latestOnError)
    }

    return AttachmentInputController(
        remainingSlots = remainingSlots,
        isSourceChooserVisible = isSourceChooserVisible,
        requestSourceChooser = ::requestSourceChooser,
        dismissSourceChooser = { isSourceChooserVisible = false },
        launchGallery = ::launchGallery,
        launchCamera = ::launchCamera,
    )
}

@Composable
fun AttachmentInputSourceDialog(
    controller: AttachmentInputController,
    title: String = "添加附件",
) {
    if (!controller.isSourceChooserVisible) return
    AlertDialog(
        onDismissRequest = controller.dismissSourceChooser,
        title = { Text(title) },
        text = { Text("请选择图片来源") },
        confirmButton = {
            TextButton(onClick = controller.launchGallery) { Text("相册") }
        },
        dismissButton = {
            TextButton(onClick = controller.launchCamera) { Text("拍照") }
        },
    )
}
