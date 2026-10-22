package com.ffocalors.sharedledger.ui.agent

import android.content.Context
import android.provider.Settings
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.indication
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.systemGestureExclusion
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.EditNote
import androidx.compose.material3.Icon
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.layout.layout
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.lerp as lerpDp
import androidx.compose.ui.util.lerp
import com.ffocalors.sharedledger.ui.theme.Inverted
import com.ffocalors.sharedledger.ui.theme.InvertedContent
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.rememberSharedLedgerHaptics
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.launch

private val BodySize = 56.dp
private val TuckedOffset = (-32).dp
private val RevealedOffset = 12.dp
private val TuckedHitWidth = 48.dp
private val RevealedHitWidth = RevealedOffset + BodySize
private val FullRadius = 28.dp
private val TuckedEndRadius = 12.dp
private const val FlingVelocity = 400f

/** False when the system animator duration scale is 0 ("remove animations"). */
internal fun areAnimationsEnabled(context: Context): Boolean = runCatching {
    Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) != 0f
}.getOrDefault(true)

/** Start-side corners go 0 -> 28dp and end-side corners go 12dp -> 28dp with [progress] (tucked -> revealed). */
private class IndexTabShape(private val progress: () -> Float) : Shape {
    override fun createOutline(size: Size, layoutDirection: LayoutDirection, density: Density): Outline {
        val full = with(density) { FullRadius.toPx() }
        val fraction = progress().coerceIn(0f, 1f)
        val start = CornerRadius(full * fraction)
        val end = CornerRadius(lerp(with(density) { TuckedEndRadius.toPx() }, full, fraction))
        // Layout is always left-anchored (the entry lives on the physical left edge).
        return Outline.Rounded(
            RoundRect(
                left = 0f, top = 0f, right = size.width, bottom = size.height,
                topLeftCornerRadius = start, bottomLeftCornerRadius = start,
                topRightCornerRadius = end, bottomRightCornerRadius = end,
            ),
        )
    }
}

/**
 * Index tab on the left screen edge. Tucked: only a 24dp tab with a grip line shows. Revealed: a 56dp
 * Graphite circle with a note icon. State and timers live in [controller]; [onOpen] opens the sheet.
 */
@Composable
fun AgentFloatingEntry(
    controller: AgentEntryController,
    onOpen: () -> Unit,
    modifier: Modifier = Modifier,
    attention: Boolean = false,
) {
    val revealed = controller.revealed
    val context = LocalContext.current
    val density = LocalDensity.current
    val scope = rememberCoroutineScope()
    val haptics = rememberSharedLedgerHaptics()
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val progress = remember { Animatable(if (revealed) 1f else 0f) }
    val shape = remember { IndexTabShape { progress.value } }
    val travelPx = with(density) { (RevealedOffset - TuckedOffset).toPx() }

    suspend fun settle(target: Float) {
        when {
            !areAnimationsEnabled(context) -> progress.snapTo(target)
            target >= 1f -> progress.animateTo(1f, spring(dampingRatio = 0.8f, stiffness = Spring.StiffnessMediumLow))
            else -> progress.animateTo(0f, tween(200, easing = SharedLedgerMotion.Easing.Standard))
        }
    }

    LaunchedEffect(revealed) { settle(if (revealed) 1f else 0f) }

    val dragState = rememberDraggableState { delta ->
        scope.launch(start = CoroutineStart.UNDISPATCHED) {
            progress.snapTo((progress.value + delta / travelPx).coerceIn(0f, 1f))
        }
    }

    Box(
        modifier = modifier
            .layout { measurable, _ ->
                val width = lerpDp(TuckedHitWidth, RevealedHitWidth, progress.value.coerceIn(0f, 1f)).roundToPx()
                val placeable = measurable.measure(Constraints.fixed(width, BodySize.roundToPx()))
                layout(width, placeable.height) { placeable.place(0, 0) }
            }
            .systemGestureExclusion()
            .semantics {
                contentDescription = if (revealed) "打开记账助手" else "展开记账助手"
                customActions = listOf(
                    CustomAccessibilityAction("打开记账助手") {
                        controller.open(onOpen)
                        true
                    },
                )
            }
            .draggable(
                state = dragState,
                orientation = Orientation.Horizontal,
                onDragStarted = { controller.onInteraction() },
                onDragStopped = { velocity ->
                    val wasRevealed = controller.revealed
                    val target = when {
                        velocity > FlingVelocity -> 1f
                        velocity < -FlingVelocity -> 0f
                        progress.value > 0.5f -> 1f
                        else -> 0f
                    }
                    if (target >= 1f) {
                        controller.reveal()
                        if (!wasRevealed) haptics.tick()
                    } else {
                        controller.tuck()
                    }
                    scope.launch { settle(target) }
                },
            )
            .clickable(
                interactionSource = interaction,
                indication = null,
                role = Role.Button,
                onClickLabel = if (revealed) "打开记账助手" else "展开记账助手",
                onClick = {
                    if (!revealed) haptics.tick()
                    controller.onTap(onOpen)
                },
            ),
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(
            modifier = Modifier
                .requiredSize(BodySize)
                .graphicsLayer {
                    val p = progress.value
                    translationX = lerp(TuckedOffset.toPx(), RevealedOffset.toPx(), p)
                    this.shape = shape
                    clip = true
                }
                .background(Inverted)
                .indication(interaction, ripple(color = InvertedContent))
                .then(if (focused) Modifier.border(3.dp, WarmOrangeContainer, shape) else Modifier),
            contentAlignment = Alignment.Center,
        ) {
            // Grip sits in the middle of the 24dp that stays on screen.
            Box(
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = 10.5.dp)
                    .size(width = 3.dp, height = 16.dp)
                    .graphicsLayer { alpha = 1f - progress.value.coerceIn(0f, 1f) }
                    .background(
                        if (attention) WarmOrangeContainer else InvertedContent,
                        RoundedCornerShape(1.5.dp),
                    ),
            )
            Icon(
                imageVector = Icons.Outlined.EditNote,
                contentDescription = null,
                tint = InvertedContent,
                modifier = Modifier
                    .size(28.dp)
                    .graphicsLayer { alpha = progress.value.coerceIn(0f, 1f) },
            )
        }
    }
}
