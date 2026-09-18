package com.ffocalors.sharedledger.ui.components

import android.animation.ValueAnimator
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.avatarGradientFor
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors
import com.ffocalors.sharedledger.ui.theme.solidAvatarColorFor
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun ParticipantAvatar(
    name: String,
    modifier: Modifier = Modifier,
    image: Painter? = null,
    background: AvatarBackground = AvatarBackground.Unbound(name),
    size: Dp = SharedLedgerDimens.AvatarMedium,
    animateBackground: Boolean = true,
) {
    Surface(
        modifier = modifier.size(size),
        shape = CircleShape,
        color = Color.Transparent,
        border = BorderStroke(SharedLedgerDimens.AvatarBorder, MaterialTheme.colorScheme.background),
    ) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            AvatarBackgroundLayer(
                background = background,
                avatarSize = size,
                animate = animateBackground,
            )
            if (image != null) {
                Image(
                    painter = image,
                    contentDescription = "$name 的头像",
                    modifier = Modifier.fillMaxSize().clip(CircleShape),
                    contentScale = ContentScale.Crop,
                )
            } else {
                Text(
                    text = name.trim().take(1).ifEmpty { "账" },
                    modifier = Modifier.semantics { contentDescription = "$name 的头像" },
                    style = SharedLedgerTextStyles.Label.copy(
                        shadow = Shadow(Color.Black.copy(alpha = 0.28f), blurRadius = 4f),
                    ),
                    color = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Clip,
                )
            }
        }
    }
}

@Composable
private fun AvatarBackgroundLayer(
    background: AvatarBackground,
    avatarSize: Dp,
    animate: Boolean,
) {
    when (background) {
        is AvatarBackground.Unbound -> Canvas(Modifier.fillMaxSize()) {
            drawRect(solidAvatarColorFor(background.stableKey))
        }
        is AvatarBackground.Bound -> {
            val preset = avatarGradientFor(background.presetId)
            val motionKey = background.stableKey?.takeIf(String::isNotBlank)
                ?: "preset:${preset.id}"
            val motion = remember(motionKey) { avatarSmokeMotionFor(motionKey) }
            // Compact 32dp avatar stacks stay static. They are frequently repeated and the
            // motion is not visually legible enough there to justify continuous redraws.
            val shouldAnimate = animate &&
                avatarSize >= SharedLedgerDimens.AvatarMedium &&
                ValueAnimator.areAnimatorsEnabled()
            val cycle = if (shouldAnimate) {
                val transition = rememberInfiniteTransition(label = "avatar smoke")
                val animatedCycle by transition.animateFloat(
                    initialValue = 0f,
                    targetValue = 1f,
                    animationSpec = infiniteRepeatable(
                        animation = tween(
                            durationMillis = motion.durationMillis +
                                if (avatarSize >= SharedLedgerDimens.AvatarLarge) 0 else 1_200,
                            easing = LinearEasing,
                        ),
                    ),
                    label = "avatar smoke phase",
                )
                animatedCycle
            } else {
                0f
            }
            val direction = if (motion.reversed) -1f else 1f
            val angle = ((motion.phase + cycle * direction) * 2f * PI).toFloat()
            val amplitude = when {
                avatarSize >= SharedLedgerDimens.AvatarLarge -> 0.14f
                avatarSize >= SharedLedgerDimens.AvatarMedium -> 0.08f
                else -> 0f
            }
            val radiusPulseAmplitude = when {
                avatarSize >= SharedLedgerDimens.AvatarLarge -> 0.12f
                avatarSize >= SharedLedgerDimens.AvatarMedium -> 0.075f
                else -> 0f
            }
            Canvas(Modifier.fillMaxSize()) {
                val longest = maxOf(size.width, size.height)
                val radiusPulse = 1f + sin(angle * 2f + 0.7f) * radiusPulseAmplitude
                val firstCenter = Offset(
                    x = size.width * (0.24f + sin(angle) * amplitude),
                    y = size.height * (0.20f + cos(angle) * amplitude * 0.72f),
                )
                val secondCenter = Offset(
                    x = size.width * (0.88f + cos(angle + 2.094f) * amplitude),
                    y = size.height * (0.32f + sin(angle * 2f + 1.15f) * amplitude * 0.62f),
                )
                val baseCenter = Offset(
                    x = size.width * (0.50f + sin(angle + 4.188f) * amplitude * 0.48f),
                    y = size.height * (1.04f + cos(angle * 2f) * amplitude * 0.42f),
                )
                val highlightCenter = Offset(
                    x = size.width * (0.43f + cos(angle + 0.55f) * amplitude * 0.6f),
                    y = size.height * (0.40f + sin(angle + 0.55f) * amplitude * 0.5f),
                )
                drawRect(preset.colors[0])
                drawRect(
                    Brush.radialGradient(
                        listOf(preset.colors[1], preset.colors[1].copy(alpha = 0.72f), Color.Transparent),
                        firstCenter, longest * 0.9f * radiusPulse,
                    ),
                )
                drawRect(
                    Brush.radialGradient(
                        listOf(preset.colors[2], preset.colors[2].copy(alpha = 0.62f), Color.Transparent),
                        secondCenter, longest * 0.78f / radiusPulse,
                    ),
                )
                drawRect(
                    Brush.radialGradient(
                        listOf(preset.colors[0].copy(alpha = 0.88f), Color.Transparent),
                        baseCenter, longest * 0.72f * radiusPulse,
                    ),
                )
                drawRect(
                    Brush.radialGradient(
                        listOf(Color.White.copy(alpha = 0.2f), Color.Transparent),
                        highlightCenter, longest * 0.48f / radiusPulse,
                    ),
                )
            }
        }
    }
}

private data class AvatarSmokeMotion(
    val phase: Float,
    val reversed: Boolean,
    val durationMillis: Int,
)

private fun avatarSmokeMotionFor(stableKey: String): AvatarSmokeMotion {
    var hash = 17
    stableKey.forEach { hash = hash * 31 + it.code }
    val positiveHash = hash.toLong().let { if (it < 0) -it else it }
    return AvatarSmokeMotion(
        phase = (positiveHash % 1_000L) / 1_000f,
        reversed = positiveHash % 2L == 0L,
        durationMillis = 6_000 + (positiveHash % 2_000L).toInt(),
    )
}

@Composable
fun ParticipantAvatarGroup(
    participants: List<ParticipantUiModel>,
    modifier: Modifier = Modifier,
    maxVisible: Int = 3,
    avatarSize: Dp = SharedLedgerDimens.AvatarSmall,
) {
    val visible = participants.take(maxVisible.coerceAtLeast(0))
    val overflowCount = (participants.size - visible.size).coerceAtLeast(0)
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerDimens.AvatarOverlap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        visible.forEach { participant ->
            ParticipantAvatar(participant.name, background = participant.avatarBackground, size = avatarSize)
        }
        if (overflowCount > 0) {
            Surface(
                modifier = Modifier.height(avatarSize).defaultMinSize(minWidth = avatarSize),
                shape = CircleShape,
                color = MaterialTheme.colorScheme.surfaceVariant,
            ) {
                Box(
                    modifier = Modifier.height(avatarSize).padding(horizontal = SharedLedgerSpacing.XSmall),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "+$overflowCount", style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, softWrap = false,
                    )
                }
            }
        }
    }
}

@Composable
fun StatusChip(status: ActivityStatus, modifier: Modifier = Modifier) {
    val semantic = MaterialTheme.sharedLedgerColors
    val (label, colors) = when (status) {
        ActivityStatus.InProgress -> "进行中" to (MaterialTheme.colorScheme.primaryContainer to MaterialTheme.colorScheme.onPrimaryContainer)
        ActivityStatus.PendingSettlement -> "待结算" to (semantic.warningContainer to semantic.onWarningContainer)
        ActivityStatus.Settled -> "已结清" to (semantic.successContainer to semantic.onSuccessContainer)
        ActivityStatus.Archived -> "已归档" to (MaterialTheme.colorScheme.surfaceVariant to MaterialTheme.colorScheme.onSurfaceVariant)
        ActivityStatus.Disputed -> "有争议" to (MaterialTheme.colorScheme.errorContainer to MaterialTheme.colorScheme.onErrorContainer)
    }
    Surface(modifier = modifier, shape = CircleShape, color = colors.first, contentColor = colors.second) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.XSmall),
            style = SharedLedgerTextStyles.Label,
        )
    }
}
