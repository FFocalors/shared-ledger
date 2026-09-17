package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * App 风格统一对话框：替代原生 AlertDialog 的紫色强调与标准按钮。
 *
 * 外观：暖白卡片底 + outlineVariant 细边框 + ExtraLarge 圆角，宽度限制在约
 * 320–360dp（页面水平 padding 16dp）。确认/取消按钮横向右对齐，圆角 Full，
 * 最小高 48dp；[destructive] 时确认按钮使用 errorContainer/onErrorContainer。
 *
 * 动效：进入 180ms fade + scale(0.96→1)，退出 120ms fade；返回键与点击外部
 * 均可取消，行为与原生 AlertDialog 一致。
 */
@Composable
fun SharedLedgerDialog(
    onDismiss: () -> Unit,
    title: String,
    modifier: Modifier = Modifier,
    text: String? = null,
    textContent: (@Composable () -> Unit)? = null,
    confirmText: String? = null,
    onConfirm: (() -> Unit)? = null,
    dismissText: String? = "取消",
    onDismissClick: (() -> Unit)? = null,
    dismissEnabled: Boolean = true,
    destructive: Boolean = false,
    confirmEnabled: Boolean = true,
    confirmLoading: Boolean = false,
) {
    var visible by remember { mutableStateOf(false) }
    var dismissRequested by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { visible = true }

    fun requestDismiss() {
        if (dismissRequested) return
        dismissRequested = true
        visible = false
        scope.launch {
            delay(SharedLedgerMotion.Durations.PressReturn.toLong())
            onDismiss()
        }
    }

    Dialog(
        onDismissRequest = ::requestDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = SharedLedgerSpacing.Medium),
            contentAlignment = Alignment.Center,
        ) {
            AnimatedVisibility(
                visible = visible,
                enter = fadeIn(tween(SharedLedgerMotion.Durations.PressReturn + 60)) +
                    scaleIn(
                        tween(SharedLedgerMotion.Durations.PressReturn + 60),
                        initialScale = 0.96f,
                    ),
                exit = fadeOut(tween(SharedLedgerMotion.Durations.PressReturn)),
            ) {
                Surface(
                    modifier = modifier
                        .fillMaxWidth()
                        .widthIn(min = 280.dp, max = 360.dp),
                    shape = SharedLedgerRadius.ExtraLarge,
                    color = MaterialTheme.colorScheme.surface,
                    contentColor = MaterialTheme.colorScheme.onSurface,
                    border = BorderStroke(
                        SharedLedgerDimens.OutlineWidth,
                        MaterialTheme.colorScheme.outlineVariant,
                    ),
                    shadowElevation = SharedLedgerElevation.Floating,
                ) {
                    Column(
                        modifier = Modifier.padding(
                            start = SharedLedgerSpacing.Large,
                            top = SharedLedgerSpacing.Large,
                            end = SharedLedgerSpacing.Large,
                            bottom = SharedLedgerSpacing.MediumLarge,
                        ),
                    ) {
                        Text(
                            text = title,
                            style = SharedLedgerTextStyles.SectionTitle,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Spacer(Modifier.height(SharedLedgerSpacing.Medium))
                        textContent?.invoke()
                            ?: text?.let {
                                Text(
                                    text = it,
                                    style = SharedLedgerTextStyles.BodySecondary,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        Spacer(Modifier.height(SharedLedgerSpacing.Large))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (dismissText != null) {
                                TextButton(
                                    onClick = { onDismissClick?.invoke() ?: requestDismiss() },
                                    enabled = dismissEnabled,
                                    colors = ButtonDefaults.textButtonColors(
                                        contentColor = MaterialTheme.colorScheme.primary,
                                        disabledContentColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
                                    ),
                                ) {
                                    Text(
                                        text = dismissText,
                                        style = SharedLedgerTextStyles.Button,
                                    )
                                }
                                if (confirmText != null && onConfirm != null) {
                                    Spacer(Modifier.width(SharedLedgerSpacing.Small))
                                }
                            }
                            if (confirmText != null && onConfirm != null) {
                                val confirmContainer: Color
                                val confirmContent: Color
                                if (destructive) {
                                    confirmContainer = MaterialTheme.colorScheme.errorContainer
                                    confirmContent = MaterialTheme.colorScheme.onErrorContainer
                                } else {
                                    confirmContainer = MaterialTheme.colorScheme.primary
                                    confirmContent = MaterialTheme.colorScheme.onPrimary
                                }
                                Button(
                                    onClick = onConfirm,
                                    enabled = confirmEnabled && !confirmLoading,
                                    modifier = Modifier.defaultMinSize(minHeight = 48.dp),
                                    shape = SharedLedgerRadius.Full,
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = confirmContainer,
                                        contentColor = confirmContent,
                                        disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                                        disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                    ),
                                ) {
                                    if (confirmLoading) {
                                        CircularProgressIndicator(
                                            modifier = Modifier.width(SharedLedgerDimens.IconSmall).height(SharedLedgerDimens.IconSmall),
                                            color = confirmContent,
                                            strokeWidth = 2.dp,
                                        )
                                        Spacer(Modifier.width(SharedLedgerSpacing.XSmall))
                                    }
                                    Text(
                                        text = confirmText,
                                        style = SharedLedgerTextStyles.Button,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
