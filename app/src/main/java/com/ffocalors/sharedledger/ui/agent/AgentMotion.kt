package com.ffocalors.sharedledger.ui.agent

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.agent.ExpensePreview
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SoftCharcoal
import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.ceil
import kotlin.math.min

/**
 * "落笔" motion kit: the assistant writes on paper. Warm tones only, every effect reports real work
 * (a draft arriving, a reply streaming, a turn running). All of it collapses to the final state when the
 * system has animations removed.
 */

/** Darkened amber for the shimmer midpoint; 4.5+ against Paper (see AgentContrastTest). */
internal val ShimmerAmber = Color(0xFF8F5E26)

/** Ink dot is a non-text mark, so it can use the lighter amber. */
internal val InkDotAmber = Color(0xFFB07A3A)

internal const val DrawOnOutlineMs = 520
internal const val DrawOnHeaderMs = 220
internal const val DrawOnAmountMs = 360
internal const val RevisionFadeMs = 120
internal const val StreamCharsPerFrame = 2
internal const val StreamFrameMs = 16
internal const val StreamCapMs = 700
internal const val StreamFadeTail = 6
private const val ShimmerCycleMs = 1600

@Composable
internal fun rememberMotionEnabled(): Boolean {
    val context = LocalContext.current
    return remember { areAnimationsEnabled(context) }
}

/** Duration of a streamed reveal for [length] characters. */
internal fun streamDurationMs(length: Int): Int =
    min(StreamCapMs, ceil(length / StreamCharsPerFrame.toFloat()).toInt() * StreamFrameMs)

/**
 * [text] where only the first [revealed] characters are visible and the last [StreamFadeTail] visible ones
 * fade in 0..1. Hidden characters stay laid out (transparent), so the text never reflows while streaming.
 */
internal fun streamedText(text: String, revealed: Float, color: Color): AnnotatedString {
    val shown = revealed.coerceIn(0f, text.length.toFloat())
    if (shown >= text.length + StreamFadeTail) return AnnotatedString(text)
    val fadeStart = (shown.toInt() - StreamFadeTail).coerceAtLeast(0)
    return buildAnnotatedString {
        append(text.substring(0, fadeStart))
        for (i in fadeStart until text.length) {
            val alpha = ((shown - i) / StreamFadeTail).coerceIn(0f, 1f)
            withStyle(SpanStyle(color = color.copy(alpha = color.alpha * alpha))) { append(text[i]) }
        }
    }
}

/** Reveals [text] character by character once; renders it whole when [animate] is false. */
@Composable
internal fun StreamingText(
    text: String,
    animate: Boolean,
    style: TextStyle,
    color: Color,
    modifier: Modifier = Modifier,
) {
    if (!animate || text.isEmpty()) {
        Text(text = text, style = style, color = color, modifier = modifier)
        return
    }
    val revealed = remember(text) { Animatable(0f) }
    LaunchedEffect(text) {
        // The fade tail needs to run past the last character so the final letters finish fading in.
        revealed.animateTo(
            text.length + StreamFadeTail.toFloat(),
            tween(streamDurationMs(text.length), easing = LinearEasing),
        )
    }
    Text(
        text = streamedText(text, revealed.value, color),
        style = style,
        color = color,
        modifier = modifier,
    )
}

/** Status line while a turn runs: a warm band sweeps over the text and an ink dot breathes beside it. */
@Composable
internal fun ShimmerStatus(text: String, modifier: Modifier = Modifier) {
    val motion = rememberMotionEnabled()
    val density = LocalDensity.current
    val style = SharedLedgerTextStyles.BodySecondary
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        if (!motion) {
            Canvas(Modifier.size(6.dp)) { drawCircle(InkDotAmber) }
            Spacer(Modifier.width(8.dp))
            Text(text = text, style = style, color = SoftCharcoal)
            return@Row
        }
        val transition = rememberInfiniteTransition(label = "agentShimmer")
        val sweep by transition.animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(tween(ShimmerCycleMs, easing = LinearEasing)),
            label = "sweep",
        )
        val breath by transition.animateFloat(
            initialValue = 0.8f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(tween(ShimmerCycleMs / 2), RepeatMode.Reverse),
            label = "breath",
        )
        Canvas(Modifier.size(6.dp)) {
            drawCircle(InkDotAmber, radius = size.minDimension / 2f * breath)
        }
        Spacer(Modifier.width(8.dp))
        val band = with(density) { 72.dp.toPx() }
        val travel = with(density) { 200.dp.toPx() }
        val x = -band + (travel + band) * sweep
        val brush = Brush.linearGradient(
            colors = listOf(SoftCharcoal, ShimmerAmber, SoftCharcoal),
            start = Offset(x, 0f),
            end = Offset(x + band, 0f),
        )
        Text(text = text, style = style.copy(brush = brush))
    }
}

/** Sequenced draft entrance values, each 0..1: outline drawn, header strip filled, amount rolled. */
internal class DraftDrawOn(val outline: State<Float>, val header: State<Float>, val amount: State<Float>)

@Composable
internal fun rememberDraftDrawOn(animate: Boolean, onStarted: () -> Unit = {}): DraftDrawOn {
    val outline = remember { Animatable(if (animate) 0f else 1f) }
    val header = remember { Animatable(if (animate) 0f else 1f) }
    val amount = remember { Animatable(if (animate) 0f else 1f) }
    if (animate) {
        LaunchedEffect(Unit) {
            onStarted()
            outline.animateTo(1f, tween(DrawOnOutlineMs, easing = FastOutSlowInEasing))
            header.animateTo(1f, tween(DrawOnHeaderMs, easing = FastOutSlowInEasing))
            amount.animateTo(1f, tween(DrawOnAmountMs, easing = FastOutSlowInEasing))
        }
    }
    return remember { DraftDrawOn(outline.asState(), header.asState(), amount.asState()) }
}

/** The dashed rounded-rect outline, clipped to the first `progress()` of its perimeter. */
internal fun Modifier.dashedOutlineDrawOn(
    color: Color,
    strokeWidthPx: Float,
    cornerRadiusPx: Float,
    progress: () -> Float,
): Modifier = drawWithCache {
    val inset = strokeWidthPx / 2f
    val left = inset
    val top = inset
    val right = size.width - inset
    val bottom = size.height - inset
    val r = cornerRadiusPx.coerceAtMost(min(right - left, bottom - top) / 2f)
    val full = Path().apply {
        moveTo(left + r, top)
        lineTo(right - r, top)
        arcTo(Rect(right - 2 * r, top, right, top + 2 * r), -90f, 90f, false)
        lineTo(right, bottom - r)
        arcTo(Rect(right - 2 * r, bottom - 2 * r, right, bottom), 0f, 90f, false)
        lineTo(left + r, bottom)
        arcTo(Rect(left, bottom - 2 * r, left + 2 * r, bottom), 90f, 90f, false)
        lineTo(left, top + r)
        arcTo(Rect(left, top, left + 2 * r, top + 2 * r), 180f, 90f, false)
        close()
    }
    val measure = PathMeasure().apply { setPath(full, false) }
    val length = measure.length
    val segment = Path()
    val stroke = Stroke(width = strokeWidthPx, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f)))
    onDrawBehind {
        val p = progress().coerceIn(0f, 1f)
        if (p >= 1f) {
            drawPath(full, color, style = stroke)
        } else if (p > 0f) {
            segment.reset()
            measure.getSegment(0f, length * p, segment, true)
            drawPath(segment, color, style = stroke)
        }
    }
}

/** Fills the background from the start edge to `progress()` of the width. */
internal fun Modifier.fillFromStart(color: Color, progress: () -> Float): Modifier = drawWithCache {
    onDrawBehind {
        val p = progress().coerceIn(0f, 1f)
        if (p >= 1f) {
            drawRect(color)
        } else if (p > 0f) {
            drawRect(color, size = androidx.compose.ui.geometry.Size(size.width * p, size.height))
        }
    }
}

/** "750.00 CNY" with the number rolled from zero to its target by [t]; keeps the original decimals. */
internal fun rollingAmountText(preview: ExpensePreview, t: Float): String {
    val full = ProposalPresentation.amountText(preview)
    if (t >= 1f) return full
    val target = preview.after.originalAmount.toBigDecimalOrNull() ?: return full
    val scale = target.scale().coerceAtLeast(0)
    val current = target.multiply(BigDecimal(t.coerceIn(0f, 1f).toDouble())).setScale(scale, RoundingMode.HALF_UP)
    return "${current.toPlainString()} ${preview.after.originalCurrency}"
}
