package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.graphicsLayer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion

/**
 * 卡片按下反馈：
 * - 按下：scale 0.96（临界阻尼 spring 快速下压，无弹跳）+ 顶部深度内阴影
 *   （内容上层绘制从上边缘向下渐隐的深色渐变 overlay，见 [SharedLedgerMotion.PressInnerShadowAlpha]）。
 * - 释放：轻微超调 spring（damping 0.7）回弹后稳定。
 *
 * 通过 interactionSource 读取 Material3 Card/Surface 的内置按压状态，
 * 不重写点击处理，因此点击语义与 TalkBack 无障碍行为完全不变。
 * 系统动画关闭时 animateFloatAsState 直接跳到终值，视觉无变化。
 */
class PressScaleState internal constructor(
    val interactionSource: MutableInteractionSource,
    val modifier: Modifier,
    val shadowAlpha: Float,
)

@Composable
fun rememberPressScaleState(): PressScaleState {
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) SharedLedgerMotion.PressScale else 1f,
        animationSpec = if (pressed) {
            SharedLedgerMotion.Springs.PressDown
        } else {
            SharedLedgerMotion.Springs.PressUp
        },
        label = "pressScale",
    )
    val shadowAlpha by animateFloatAsState(
        targetValue = if (pressed) SharedLedgerMotion.PressInnerShadowAlpha else 0f,
        animationSpec = if (pressed) {
            SharedLedgerMotion.Springs.PressDown
        } else {
            SharedLedgerMotion.Springs.PressUp
        },
        label = "pressShadow",
    )
    val modifier = Modifier.graphicsLayer {
        scaleX = scale
        scaleY = scale
        transformOrigin = TransformOrigin.Center
    }
    return PressScaleState(interactionSource, modifier, shadowAlpha)
}

/**
 * 按压深度内阴影 modifier：先裁剪到 [shape]，再在内容上层绘制顶部渐隐深色
 * 渐变（宽度全、高度约为卡片 1/3），模拟卡片被向下压缩的立体感。
 * [alpha] 传 [PressScaleState.shadowAlpha]，未按下时为 0，绘制自动跳过。
 */
fun Modifier.pressInnerShadow(shape: Shape, alpha: Float): Modifier =
    this.then(
        Modifier
            .clip(shape)
            .drawWithContent {
                drawContent()
                if (alpha > 0.001f) {
                    drawPressInnerShadow(alpha)
                }
            },
    )

private fun DrawScope.drawPressInnerShadow(alpha: Float) {
    val shadowHeight = size.height * SharedLedgerMotion.PressInnerShadowHeightFraction
    drawRect(
        brush = Brush.verticalGradient(
            colors = listOf(Color.Black.copy(alpha = alpha), Color.Transparent),
            startY = 0f,
            endY = shadowHeight,
        ),
        topLeft = Offset.Zero,
        size = Size(size.width, shadowHeight),
    )
}
