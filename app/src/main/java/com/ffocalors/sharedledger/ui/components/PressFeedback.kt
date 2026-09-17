package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion

/**
 * 卡片按下反馈：scale 0.98，按下 80ms / 回弹 120ms。
 *
 * 通过 interactionSource 读取 Material3 Card/Surface 的内置按压状态，
 * 不重写点击处理，因此点击语义与 TalkBack 无障碍行为完全不变。
 * 系统动画关闭时 animateFloatAsState 直接跳到终值，视觉无变化。
 */
class PressScaleState internal constructor(
    val interactionSource: MutableInteractionSource,
    val modifier: Modifier,
)

@Composable
fun rememberPressScaleState(): PressScaleState {
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) SharedLedgerMotion.PressScale else 1f,
        animationSpec = tween(
            durationMillis = if (pressed) {
                SharedLedgerMotion.Durations.PressScale
            } else {
                SharedLedgerMotion.Durations.PressReturn
            },
        ),
        label = "pressScale",
    )
    val modifier = Modifier.graphicsLayer {
        scaleX = scale
        scaleY = scale
        transformOrigin = TransformOrigin.Center
    }
    return PressScaleState(interactionSource, modifier)
}
