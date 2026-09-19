package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.indication
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Backspace
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.onLongClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 数字键盘协调状态：金额输入框聚焦时绑定，键盘输入直接回写到当前聚焦字段。
 * 输入规则与金额语义一致：仅数字与一个小数点，小数位最多两位，总长不超过 12。
 */
@Stable
class NumericKeypadState {
    var active by mutableStateOf(false)
        private set

    private var getValue: (() -> String)? = null
    private var onChange: ((String) -> Unit)? = null

    fun bind(getValue: () -> String, onChange: (String) -> Unit) {
        this.getValue = getValue
        this.onChange = onChange
        active = true
    }

    fun unbind(onChange: (String) -> Unit) {
        if (this.onChange === onChange) {
            this.getValue = null
            this.onChange = null
            active = false
        }
    }

    fun input(digit: String) {
        val current = getValue?.invoke() ?: return
        val next = when {
            digit == "." -> if (current.contains('.')) current else current + "."
            current.contains('.') && current.substringAfter('.').length >= 2 -> current
            current.length >= 12 -> current
            else -> current + digit
        }
        if (next != current) onChange?.invoke(next)
    }

    fun delete() {
        val current = getValue?.invoke() ?: return
        if (current.isNotEmpty()) onChange?.invoke(current.dropLast(1))
    }
}

/** 让输入框在聚焦时接管数字键盘；配合 readOnly 使用以避免拉起系统键盘。 */
fun Modifier.numericKeypadTarget(
    state: NumericKeypadState,
    current: () -> String,
    onChange: (String) -> Unit,
): Modifier = this.onFocusChanged { focusState ->
    if (focusState.isFocused) {
        state.bind(current, onChange)
    } else {
        state.unbind(onChange)
    }
}

private val KeypadRows = listOf(
    listOf("1", "2", "3"),
    listOf("4", "5", "6"),
    listOf("7", "8", "9"),
    listOf(".", "0", "⌫"),
)

private const val BackspaceRepeatIntervalMillis = 72L

/**
 * App 风格的数字键盘：作为屏幕底部覆盖层从底端滑入，遮盖底层内容（含保存按钮），
 * 点击键盘外空白区域通过 [onDismiss]（通常是清除焦点）收起。
 * 只在 [NumericKeypadState.active] 为 true 时显示；文本输入场景继续使用系统键盘。
 */
@Composable
fun SharedLedgerNumericKeypad(
    state: NumericKeypadState,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val haptics = LocalHapticFeedback.current
    AnimatedVisibility(
        visible = state.active,
        modifier = modifier,
        enter = slideInVertically { it / 3 } + fadeIn(),
        exit = slideOutVertically { it / 3 } + fadeOut(),
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = onDismiss,
                    ),
            )
            Surface(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth(),
                shape = RoundedCornerShape(
                    topStart = SharedLedgerRadius.LargeCorner,
                    topEnd = SharedLedgerRadius.LargeCorner,
                ),
                color = MaterialTheme.colorScheme.background,
                tonalElevation = SharedLedgerElevation.Flat,
                shadowElevation = SharedLedgerElevation.Floating,
            ) {
                Column(
                    modifier = Modifier
                        .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(
                            start = SharedLedgerDimens.PageHorizontalPadding,
                            end = SharedLedgerDimens.PageHorizontalPadding,
                            top = SharedLedgerSpacing.MediumSmall,
                            bottom = SharedLedgerSpacing.Medium,
                        ),
                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    KeypadRows.forEach { row ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            row.forEach { key ->
                                val isBackspace = key == "⌫"
                                KeypadKey(
                                    label = key,
                                    onClick = {
                                        haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                        if (isBackspace) state.delete() else state.input(key)
                                    },
                                    onLongPressRepeat = if (isBackspace) state::delete else null,
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun KeypadKey(
    label: String,
    onClick: () -> Unit,
    onLongPressRepeat: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    if (onLongPressRepeat != null) {
        val interactionSource = remember { MutableInteractionSource() }
        val longPressTimeoutMillis = LocalViewConfiguration.current.longPressTimeoutMillis
        val currentOnClick by rememberUpdatedState(onClick)
        val currentRepeatAction by rememberUpdatedState(onLongPressRepeat)
        val shape = SharedLedgerRadius.Medium

        Surface(
            modifier = modifier
                .height(52.dp)
                .clip(shape)
                .indication(interactionSource, ripple())
                .semantics {
                    role = Role.Button
                    onClick(label = "删除一位") {
                        currentOnClick()
                        true
                    }
                    onLongClick(label = "连续删除") {
                        currentOnClick()
                        true
                    }
                }
                .pointerInput(longPressTimeoutMillis) {
                    detectTapGestures(
                        onPress = { position ->
                            val pressScope = this
                            val press = PressInteraction.Press(position)
                            interactionSource.emit(press)
                            var released = false
                            try {
                                coroutineScope {
                                    var repeating = false
                                    val repeatJob = launch {
                                        delay(longPressTimeoutMillis)
                                        repeating = true
                                        currentOnClick()
                                        while (true) {
                                            delay(BackspaceRepeatIntervalMillis)
                                            currentRepeatAction()
                                        }
                                    }
                                    released = pressScope.tryAwaitRelease()
                                    repeatJob.cancel()
                                    if (released && !repeating) currentOnClick()
                                }
                            } finally {
                                interactionSource.tryEmit(
                                    if (released) PressInteraction.Release(press)
                                    else PressInteraction.Cancel(press),
                                )
                            }
                        },
                    )
                },
            shape = shape,
            color = MaterialTheme.colorScheme.surfaceVariant,
            contentColor = MaterialTheme.colorScheme.onSurface,
            tonalElevation = SharedLedgerElevation.Flat,
            shadowElevation = SharedLedgerElevation.Flat,
        ) {
            KeypadKeyContent(label)
        }
        return
    }

    Surface(
        onClick = onClick,
        modifier = modifier.height(52.dp),
        shape = SharedLedgerRadius.Medium,
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurface,
        tonalElevation = SharedLedgerElevation.Flat,
        shadowElevation = SharedLedgerElevation.Flat,
    ) {
        KeypadKeyContent(label)
    }
}

@Composable
private fun KeypadKeyContent(label: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (label == "⌫") {
            Icon(
                imageVector = Icons.AutoMirrored.Rounded.Backspace,
                contentDescription = "删除一位",
                modifier = Modifier.height(SharedLedgerDimens.IconMedium),
            )
        } else {
            Text(label, style = SharedLedgerTextStyles.Body)
        }
    }
}
