package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
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
import androidx.compose.ui.semantics.Role
import com.ffocalors.sharedledger.ui.theme.SharedLedgerHaptics
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.rememberSharedLedgerHaptics

/**
 * 卡片按下反馈状态：
 * - 按下：scale 0.965（临界阻尼 spring 快速下压，无弹跳）+ 顶部深度内阴影。
 * - 释放：轻微超调 spring（damping 0.72）回弹后稳定。
 */
class PressScaleState internal constructor(
    val interactionSource: MutableInteractionSource,
    val modifier: Modifier,
    val shadowAlpha: Float,
)

@Composable
fun rememberPressScaleState(
    enableHaptics: Boolean = true,
): PressScaleState {
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val haptics = rememberSharedLedgerHaptics()

    LaunchedEffect(pressed) {
        if (pressed && enableHaptics) {
            haptics.click()
        }
    }

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
 * 工业级工件微倒角高光 Modifier：
 * 在组件内边缘绘制一道微弱自上而下的冷光切面，模拟精密阳极氧化铝工件的边缘倒角折射，
 * 彻底消除 AI 式蓝紫大光晕，带来沉稳、真实的物理工艺感。
 */
fun Modifier.specularMachinedBorder(
    shape: Shape = SharedLedgerRadius.Large,
    highlightAlpha: Float = 0.28f,
): Modifier = this.then(
    Modifier
        .clip(shape)
        .drawWithContent {
            drawContent()
            // 绘制顶部 1.5dp 的精密冷白微倒角高光
            val highlightHeight = 1.5f * density
            drawRect(
                brush = Brush.verticalGradient(
                    colors = listOf(
                        Color.White.copy(alpha = highlightAlpha),
                        Color.Transparent,
                    ),
                    startY = 0f,
                    endY = highlightHeight * 2.5f,
                ),
                topLeft = Offset.Zero,
                size = Size(size.width, highlightHeight * 2.5f),
            )
        },
)

/**
 * 按压深度内阴影 modifier：先裁剪到 [shape]，再在内容上层绘制顶部渐隐深色
 * 渐变，模拟按键被手指按进机壳内的机械景深。
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

/**
 * 操作系统级通用物理按压卡片 Modifier：
 * - 结合机械微动触觉反馈；
 * - 临界阻尼下陷缩放与内阴影深度；
 * - 精密工件微倒角高光；
 * - 若指定 [onClick]，使用无波纹（纯物理）或轻波纹响应。
 */
fun Modifier.pressablePhysics(
    shape: Shape = SharedLedgerRadius.Large,
    enabled: Boolean = true,
    haptic: Boolean = true,
    onClick: (() -> Unit)? = null,
): Modifier = composed {
    if (!enabled) return@composed this

    val pressState = rememberPressScaleState(enableHaptics = haptic)

    var base = this
        .then(pressState.modifier)
        .pressInnerShadow(shape, pressState.shadowAlpha)
        .specularMachinedBorder(shape)

    if (onClick != null) {
        base = base.clickable(
            interactionSource = pressState.interactionSource,
            indication = null, // 纯物理阻尼形变与触觉，替代廉价灰色大涟漪
            role = Role.Button,
            onClick = onClick,
        )
    }

    base
}
