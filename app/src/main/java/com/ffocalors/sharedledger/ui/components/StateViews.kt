package com.ffocalors.sharedledger.ui.components

import android.animation.ValueAnimator
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.Inbox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.foundation.BorderStroke
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SageGreenContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.WarmOrange
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/** 加载动效尺寸等级。 */
enum class LoadingSize(val canvasSize: Dp) {
    /** 适合嵌入列表项、单据内嵌、局部下拉刷新。 */
    Compact(36.dp),

    /** 适合页面初次加载、全屏进入、跨 Tab 主视图加载。 */
    Large(68.dp),
}

/**
 * 共享账本专属动效：【平账律动 · 双星天平 Balance Orbit】
 *
 * 借贷平账、收支对齐的几何隐喻：
 * - 鼠尾草绿（代表收款/资产）与暖橙（代表支出/债务）两颗微粒小球在带有透视仰角的轨道上互为相位差旋转；
 * - 带有立体景深渲染：近端小球放大且光泽明亮，远端小球微小轻柔；
 * - 两星交汇平账瞬间在中心底座扩散出微光脉冲波纹；
 * - 严格支持系统动效关闭检测（若动画关闭则静止平稳展示）。
 */
@Composable
fun BalanceOrbitProgressIndicator(
    modifier: Modifier = Modifier,
    size: LoadingSize = LoadingSize.Large,
    primaryColor: Color = SageGreen,
    secondaryColor: Color = WarmOrange,
) {
    val isInspection = LocalInspectionMode.current
    val animatorsEnabled = isInspection || ValueAnimator.areAnimatorsEnabled()

    val cycle = if (animatorsEnabled) {
        val transition = rememberInfiniteTransition(label = "balanceOrbit")
        val progress by transition.animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 1350, easing = LinearEasing),
                repeatMode = RepeatMode.Restart,
            ),
            label = "orbitProgress",
        )
        progress
    } else {
        0.25f // 静态降级：两星处于对称优雅平衡位置
    }

    val outlineColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.35f)
    val rippleColor = primaryColor.copy(alpha = 0.18f)

    Canvas(modifier = modifier.size(size.canvasSize)) {
        val center = Offset(this.size.width / 2f, this.size.height / 2f)
        val isLarge = size == LoadingSize.Large

        // 几何参数配置
        val orbitRadiusX = this.size.width * 0.38f
        val orbitTiltY = 0.62f // 轨道倾斜压缩率，呈现优雅微仰视椭圆
        val orbitRadiusY = orbitRadiusX * orbitTiltY

        val baseBallRadius = if (isLarge) 6.5.dp.toPx() else 3.6.dp.toPx()
        val orbitStrokeWidth = if (isLarge) 1.5.dp.toPx() else 1.0.dp.toPx()

        // 1. 绘制交汇点平账扩散脉冲涟漪 (Ripple)
        if (animatorsEnabled) {
            // 每周期两次交汇（t = 0.25 与 0.75 时 x 对齐）
            val rippleProgress = ((cycle * 2f) % 1f)
            val rippleRadius = orbitRadiusX * (0.3f + rippleProgress * 0.85f)
            val rippleAlpha = ((1f - rippleProgress) * 0.28f).coerceIn(0f, 1f)
            drawCircle(
                color = rippleColor.copy(alpha = rippleAlpha),
                radius = rippleRadius,
                center = center,
            )
        }

        // 2. 绘制微透轨道背景椭圆环
        drawOval(
            color = outlineColor,
            topLeft = Offset(center.x - orbitRadiusX, center.y - orbitRadiusY),
            size = androidx.compose.ui.geometry.Size(orbitRadiusX * 2f, orbitRadiusY * 2f),
            style = Stroke(width = orbitStrokeWidth),
        )

        // 3. 计算双星位置与三维深度 (Z-index 透视)
        val theta1 = (cycle * 2f * PI).toFloat()
        val theta2 = theta1 + PI.toFloat()

        // 星球 1：鼠尾草绿 (收/资)
        val x1 = center.x + orbitRadiusX * cos(theta1)
        val y1 = center.y + orbitRadiusY * sin(theta1)
        val z1 = sin(theta1) // [-1, 1]，>0 在近端，<0 在远端

        // 星球 2：暖橙 (支/债)
        val x2 = center.x + orbitRadiusX * cos(theta2)
        val y2 = center.y + orbitRadiusY * sin(theta2)
        val z2 = sin(theta2)

        data class OrbitParticle(
            val pos: Offset,
            val z: Float,
            val mainColor: Color,
            val glowColor: Color,
        )

        val particles = listOf(
            OrbitParticle(Offset(x1, y1), z1, primaryColor, SageGreenContainer),
            OrbitParticle(Offset(x2, y2), z2, secondaryColor, WarmOrangeContainer),
        ).sortedBy { it.z } // 先画远端（z 小），再画近端（z 大），形成逼真立体遮挡

        particles.forEach { particle ->
            // 根据深度动态调节缩放和透明度
            val scale = 0.76f + (particle.z + 1f) * 0.24f // [0.76 ~ 1.24]
            val alpha = 0.65f + (particle.z + 1f) * 0.175f // [0.65 ~ 1.0]
            val currentRadius = baseBallRadius * scale

            // 绘制柔和光晕
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        particle.glowColor.copy(alpha = 0.45f * alpha),
                        particle.glowColor.copy(alpha = 0f),
                    ),
                    center = particle.pos,
                    radius = currentRadius * 2.2f,
                ),
                radius = currentRadius * 2.2f,
                center = particle.pos,
            )

            // 绘制实心微粒
            drawCircle(
                color = particle.mainColor.copy(alpha = alpha),
                radius = currentRadius,
                center = particle.pos,
            )

            // 绘制近端高光微点
            if (particle.z > 0.2f) {
                val highlightOffset = Offset(
                    particle.pos.x - currentRadius * 0.28f,
                    particle.pos.y - currentRadius * 0.28f,
                )
                drawCircle(
                    color = Color.White.copy(alpha = 0.65f * particle.z),
                    radius = currentRadius * 0.32f,
                    center = highlightOffset,
                )
            }
        }
    }
}

/**
 * 全局通用加载状态视图：
 * 采用全新的【平账律动 · 双星天平】动效，提供舒缓治愈的呼吸提示，并支持大/小尺寸自适应。
 */
@Composable
fun LoadingState(
    modifier: Modifier = Modifier,
    message: String = "正在加载…",
    isRefreshing: Boolean = false,
    size: LoadingSize? = null,
) {
    val resolvedSize = size ?: if (isRefreshing) LoadingSize.Compact else LoadingSize.Large
    val isInspection = LocalInspectionMode.current
    val animatorsEnabled = isInspection || ValueAnimator.areAnimatorsEnabled()

    // 文字微妙呼吸过渡，避免用户误以为界面卡死
    val textAlpha = if (animatorsEnabled) {
        val transition = rememberInfiniteTransition(label = "loadingTextBreathing")
        val alpha by transition.animateFloat(
            initialValue = 0.72f,
            targetValue = 1.0f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 1500, easing = LinearEasing),
                repeatMode = RepeatMode.Reverse,
            ),
            label = "textAlpha",
        )
        alpha
    } else {
        1.0f
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                vertical = if (resolvedSize == LoadingSize.Large) {
                    SharedLedgerSpacing.XLarge
                } else {
                    SharedLedgerSpacing.Medium
                },
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(
            if (resolvedSize == LoadingSize.Large) SharedLedgerSpacing.Medium else SharedLedgerSpacing.Small,
        ),
    ) {
        BalanceOrbitProgressIndicator(
            size = resolvedSize,
        )

        Text(
            text = if (isRefreshing) "正在刷新…" else message,
            style = if (resolvedSize == LoadingSize.Large) {
                SharedLedgerTextStyles.BodySecondary.copy(fontWeight = FontWeight.Medium)
            } else {
                SharedLedgerTextStyles.Label
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.alpha(textAlpha),
            textAlign = TextAlign.Center,
        )
    }
}

/**
 * 轻量骨架屏微光扫描 Modifier。
 *
 * 遵循 SharedLedger 动效原则：
 * - 扫描周期 1300ms，短促自然；
 * - 严格检测 ValueAnimator.areAnimatorsEnabled()：系统动画关闭时降级为静态浅灰背景；
 * - 自适应组件宽高，倾斜光带无跳跃循环。
 */
@Composable
fun Modifier.shimmerPlaceholder(
    shape: androidx.compose.ui.graphics.Shape = SharedLedgerRadius.Medium,
    color: Color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
    highlightColor: Color = MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
): Modifier {
    val isInspection = LocalInspectionMode.current
    val animatorsEnabled = isInspection || ValueAnimator.areAnimatorsEnabled()

    if (!animatorsEnabled) {
        return this
            .clip(shape)
            .background(color)
    }

    val transition = rememberInfiniteTransition(label = "shimmerTransition")
    val progress by transition.animateFloat(
        initialValue = -0.6f,
        targetValue = 1.6f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1300, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "shimmerProgress",
    )

    return this
        .clip(shape)
        .drawWithContent {
            val width = size.width
            val height = size.height
            val x = width * progress
            drawRect(color)
            val brush = Brush.linearGradient(
                colors = listOf(
                    color,
                    highlightColor,
                    color,
                ),
                start = Offset(x, 0f),
                end = Offset(x + width * 0.6f, height),
            )
            drawRect(brush)
        }
}

/** 主页活动卡片骨架屏（与 [HomeActivityCard] 尺寸轮廓完全一致）。 */
@Composable
fun HomeActivityCardSkeleton(
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(width = 130.dp, height = 20.dp)
                        .shimmerPlaceholder(SharedLedgerRadius.Small),
                )
                Box(
                    modifier = Modifier
                        .size(width = 75.dp, height = 24.dp)
                        .shimmerPlaceholder(SharedLedgerRadius.Full),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy((-6).dp)) {
                    repeat(3) {
                        Box(
                            modifier = Modifier
                                .size(SharedLedgerDimens.AvatarSmall)
                                .shimmerPlaceholder(SharedLedgerRadius.Full),
                        )
                    }
                }
                Box(
                    modifier = Modifier
                        .size(width = 50.dp, height = 14.dp)
                        .shimmerPlaceholder(SharedLedgerRadius.Small),
                )
            }
        }
    }
}

/** 账单流水条目骨架屏（与 [ExpenseCard] 尺寸轮廓完全一致）。 */
@Composable
fun ExpenseCardSkeleton(
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Box(
                modifier = Modifier
                    .size(SharedLedgerDimens.ActionIconContainer)
                    .shimmerPlaceholder(SharedLedgerRadius.Full),
            )
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
                Box(
                    modifier = Modifier
                        .size(width = 110.dp, height = 18.dp)
                        .shimmerPlaceholder(SharedLedgerRadius.Small),
                )
                Box(
                    modifier = Modifier
                        .size(width = 70.dp, height = 14.dp)
                        .shimmerPlaceholder(SharedLedgerRadius.Small),
                )
            }
            Box(
                modifier = Modifier
                    .size(width = 65.dp, height = 20.dp)
                    .shimmerPlaceholder(SharedLedgerRadius.Small),
            )
        }
    }
}

@Composable
fun EmptyState(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector = Icons.Rounded.Inbox,
    description: String? = null,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                horizontal = SharedLedgerDimens.PageHorizontalPadding,
                vertical = SharedLedgerSpacing.XLarge,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        // 具有温度感的品牌混光双层底座
        Box(
            modifier = Modifier.size(76.dp),
            contentAlignment = Alignment.Center,
        ) {
            Surface(
                modifier = Modifier.size(76.dp),
                shape = SharedLedgerRadius.Full,
                color = WarmOrangeContainer.copy(alpha = 0.35f),
            ) {}
            Surface(
                modifier = Modifier.size(56.dp),
                shape = SharedLedgerRadius.Full,
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = SharedLedgerElevation.Card,
                border = BorderStroke(
                    SharedLedgerDimens.OutlineWidth,
                    WarmOrange.copy(alpha = 0.25f),
                ),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = WarmOrange,
                        modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                    )
                }
            }
        }
        Text(
            text = title,
            style = SharedLedgerTextStyles.CardTitle,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        description?.let {
            Text(
                text = it,
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium),
            )
        }
        if (actionLabel != null && onAction != null) {
            Spacer(modifier = Modifier.height(SharedLedgerSpacing.XSmall))
            SharedLedgerButton(
                text = actionLabel,
                onClick = onAction,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Composable
fun ErrorState(
    message: String,
    modifier: Modifier = Modifier,
    onRetry: (() -> Unit)? = null,
    retryLabel: String = "重试",
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                horizontal = SharedLedgerDimens.PageHorizontalPadding,
                vertical = SharedLedgerSpacing.XLarge,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Box(
            modifier = Modifier.size(76.dp),
            contentAlignment = Alignment.Center,
        ) {
            Surface(
                modifier = Modifier.size(76.dp),
                shape = SharedLedgerRadius.Full,
                color = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f),
            ) {}
            Surface(
                modifier = Modifier.size(56.dp),
                shape = SharedLedgerRadius.Full,
                color = MaterialTheme.colorScheme.errorContainer,
                shadowElevation = SharedLedgerElevation.Card,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Rounded.ErrorOutline,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                    )
                }
            }
        }
        Text(
            text = message,
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        onRetry?.let {
            Spacer(modifier = Modifier.height(SharedLedgerSpacing.XSmall))
            SharedLedgerButton(
                text = retryLabel,
                onClick = it,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

/**
 * 终态错误（已删除/不存在/无权限）判断：重试不会成功，调用方应隐藏重试按钮。
 * 状态层目前只向界面传递 message 字符串，故用保守关键字匹配。
 */
fun isTerminalActivityError(message: String?): Boolean =
    message != null && (
        message.contains("已删除") ||
            message.contains("不存在") ||
            message.contains("无权限") ||
            message.contains("没有权限")
        )

@Composable
fun ErrorBanner(
    message: String,
    modifier: Modifier = Modifier,
) {
    AnimatedVisibility(
        visible = message.isNotBlank(),
        enter = expandVertically(
            animationSpec = tween(
                durationMillis = com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion.Durations.Content,
                easing = com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion.Easing.Standard,
            ),
        ) + fadeIn(
            animationSpec = tween(
                durationMillis = com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion.Durations.Content,
            ),
        ),
        exit = shrinkVertically(
            animationSpec = tween(
                durationMillis = com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion.Durations.Content,
                easing = com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion.Easing.Standard,
            ),
        ) + fadeOut(
            animationSpec = tween(
                durationMillis = com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion.Durations.Content,
            ),
        ),
        modifier = modifier.fillMaxWidth(),
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = SharedLedgerRadius.Large,
            color = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer,
        ) {
            Row(
                modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Rounded.ErrorOutline,
                    contentDescription = null,
                    modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                )
                Text(
                    text = message,
                    style = SharedLedgerTextStyles.BodySecondary,
                )
            }
        }
    }
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    trailing: (@Composable RowScope.() -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            modifier = Modifier.weight(1f),
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        trailing?.invoke(this)
    }
}

@Preview(name = "全屏大图加载", showBackground = true)
@Composable
private fun LoadingStateLargePreview() {
    SharedLedgerTheme {
        LoadingState(
            message = "正在读取最新账单与债务…",
            size = LoadingSize.Large,
        )
    }
}

@Preview(name = "紧凑刷新加载", showBackground = true)
@Composable
private fun LoadingStateCompactPreview() {
    SharedLedgerTheme {
        LoadingState(
            message = "正在刷新…",
            isRefreshing = true,
        )
    }
}
