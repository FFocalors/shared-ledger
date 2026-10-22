package com.ffocalors.sharedledger.ui.agent

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.exponentialDecay
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.shape.CornerSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.rememberSharedLedgerHaptics
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

private val RubberLimit = 64.dp
private val DragStripHeight = 24.dp
private const val MaxScrimAlpha = 0.32f
private const val SettleDamping = 0.82f
private const val RubberDamping = 0.62f
private const val OffscreenOffset = 1_000_000f

private val SheetShape = SharedLedgerRadius.ExtraLarge.copy(
    bottomStart = CornerSize(0.dp),
    bottomEnd = CornerSize(0.dp),
)

private class SheetAnchors(val expanded: Float, val half: Float, val hidden: Float) {
    val list get() = listOf(expanded, half, hidden)
}

/** Mutable drag bookkeeping that must outlive recomposition but never trigger it. */
private class SheetSession {
    /** Finger-implied (undamped) sheet top while a drag / nested-scroll session is active. */
    var raw = 0f
    var active = false
    var dismissing = false
    var job: Job? = null
}

/**
 * Damped bottom sheet with Expanded / Half / Hidden anchors, rubber band above Expanded and
 * velocity-aware snapping (see `docs/agent-app/UI_PLAN.md`, "抽屉物理"). Physics lives in
 * [AgentSheetPhysics].
 *
 * Place it as a full-screen overlay inside a top-level `Box`; it is not a Dialog. The sheet's
 * bottom edge is always the container's bottom edge and its height follows the visible part, so
 * [content] must apply `navigationBarsPadding()` / `imePadding()` itself.
 *
 * @param visible true opens the sheet (to Expanded if [startExpanded], else Half); false animates
 * it away without calling [onDismissed].
 * @param onDismissed called once the user has closed the sheet (scrim, back, drag, fling) and it
 * reached Hidden. The caller should then set [visible] to false.
 * @param expandRequest bump this value to force Expanded (e.g. when the IME gets focus).
 */
@Composable
fun AgentBottomSheet(
    visible: Boolean,
    onDismissed: () -> Unit,
    startExpanded: Boolean,
    expandRequest: Int,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val context = LocalContext.current
    val density = LocalDensity.current
    val haptics = rememberSharedLedgerHaptics()
    val scope = rememberCoroutineScope()
    val onDismissedState by rememberUpdatedState(onDismissed)
    val startExpandedState by rememberUpdatedState(startExpanded)

    var heightPx by remember { mutableIntStateOf(0) }
    val statusTop = WindowInsets.statusBars.getTop(density)
    val rubberLimitPx = with(density) { RubberLimit.toPx() }
    val anchors = SheetAnchors(
        expanded = statusTop + heightPx * 0.08f,
        half = heightPx * 0.45f,
        hidden = heightPx.toFloat(),
    )
    val anchorsState by rememberUpdatedState(anchors)

    val offset = remember { Animatable(OffscreenOffset) }
    val decay = remember { exponentialDecay<Float>() }
    val session = remember { SheetSession() }

    fun display(rawValue: Float): Float {
        val a = anchorsState
        return if (rawValue < a.expanded) {
            a.expanded - AgentSheetPhysics.rubberBand(a.expanded - rawValue, rubberLimitPx)
        } else {
            rawValue.coerceAtMost(a.hidden)
        }
    }

    fun beginSession() {
        if (session.active) return
        session.job?.cancel()
        val a = anchorsState
        val current = offset.value
        session.raw = if (current < a.expanded) {
            a.expanded - AgentSheetPhysics.rubberBandInverse(a.expanded - current, rubberLimitPx)
        } else {
            current
        }
        session.active = true
    }

    fun dragBy(delta: Float) {
        session.raw = (session.raw + delta).coerceAtMost(anchorsState.hidden)
        val target = display(session.raw)
        scope.launch(start = CoroutineStart.UNDISPATCHED) { offset.snapTo(target) }
    }

    fun animateTo(
        target: Float,
        velocity: Float,
        damping: Float,
        tick: Boolean,
        afterwards: () -> Unit = {},
    ) {
        session.active = false
        session.job?.cancel()
        session.job = scope.launch {
            if (!areAnimationsEnabled(context)) {
                offset.snapTo(target)
            } else {
                offset.animateTo(
                    target,
                    spring(dampingRatio = damping, stiffness = Spring.StiffnessMediumLow),
                    initialVelocity = velocity,
                )
            }
            if (tick) haptics.tick()
            afterwards()
        }
    }

    fun settle(velocity: Float) {
        val a = anchorsState
        val from = offset.value
        val target = AgentSheetPhysics.chooseAnchor(from, velocity, a.list, decay, density.density)
        val damping = if (from < a.expanded) RubberDamping else SettleDamping
        val closing = target == a.hidden
        if (closing) session.dismissing = true
        animateTo(target, velocity, damping, tick = closing || target == a.expanded) {
            if (closing) {
                session.dismissing = false
                onDismissedState()
            }
        }
    }

    fun dismiss() {
        if (session.dismissing) return
        session.dismissing = true
        animateTo(anchorsState.hidden, 0f, SettleDamping, tick = false) {
            session.dismissing = false
            onDismissedState()
        }
    }

    fun goTo(target: Float) = animateTo(target, 0f, SettleDamping, tick = false)

    LaunchedEffect(visible, heightPx > 0) {
        if (heightPx <= 0) return@LaunchedEffect
        val a = anchorsState
        val spec = spring<Float>(dampingRatio = SettleDamping, stiffness = Spring.StiffnessMediumLow)
        if (visible) {
            session.active = false
            offset.snapTo(a.hidden)
            val target = if (startExpandedState) a.expanded else a.half
            if (!areAnimationsEnabled(context)) offset.snapTo(target) else offset.animateTo(target, spec)
        } else if (offset.value < a.hidden) {
            if (!areAnimationsEnabled(context)) offset.snapTo(a.hidden) else offset.animateTo(a.hidden, spec)
        }
    }

    LaunchedEffect(expandRequest) {
        if (expandRequest != 0 && visible && heightPx > 0 && offset.value > anchorsState.expanded + 1f) {
            goTo(anchorsState.expanded)
        }
    }

    val present by remember(visible) {
        derivedStateOf { visible || (heightPx > 0 && offset.value < heightPx - 1f) }
    }
    if (!present) return

    BackHandler(enabled = visible) { dismiss() }

    val draggableState = rememberDraggableState { dragBy(it) }

    val connection = remember {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (source != NestedScrollSource.UserInput || session.dismissing) return Offset.Zero
                val a = anchorsState
                val y = available.y
                if (y < 0f && offset.value > a.expanded + 0.5f) {
                    // Upward: push the sheet up until Expanded before the list scrolls.
                    beginSession()
                    val consumed = maxOf(y, -(session.raw - a.expanded)).coerceAtMost(0f)
                    dragBy(consumed)
                    return Offset(0f, consumed)
                }
                if (y > 0f && offset.value < a.expanded - 0.5f) {
                    // Downward while stretched above Expanded: release the stretch first.
                    beginSession()
                    val consumed = minOf(y, a.expanded - session.raw).coerceAtLeast(0f)
                    dragBy(consumed)
                    return Offset(0f, consumed)
                }
                return Offset.Zero
            }

            override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {
                if (source != NestedScrollSource.UserInput || session.dismissing) return Offset.Zero
                if (available.y > 0f) {
                    // List is at its top: leftover downward drag moves the sheet.
                    beginSession()
                    dragBy(available.y)
                    return Offset(0f, available.y)
                }
                return Offset.Zero
            }

            override suspend fun onPreFling(available: Velocity): Velocity {
                if (session.active && offset.value > anchorsState.expanded + 0.5f) {
                    settle(available.y)
                    return available
                }
                return Velocity.Zero
            }

            override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
                if (session.active || offset.value < anchorsState.expanded - 0.5f) {
                    settle(available.y)
                    return available
                }
                return Velocity.Zero
            }
        }
    }

    Box(modifier.fillMaxSize().onSizeChanged { heightPx = it.height }) {
        Box(
            Modifier
                .fillMaxSize()
                .drawBehind {
                    val a = anchorsState
                    val span = (a.hidden - a.expanded).coerceAtLeast(1f)
                    val open = ((a.hidden - offset.value) / span).coerceIn(0f, 1f)
                    drawRect(Color.Black, alpha = MaxScrimAlpha * open)
                }
                .pointerInput(Unit) { detectTapGestures { dismiss() } },
        )
        Column(
            Modifier
                .layout { measurable, constraints ->
                    val top = offset.value.roundToInt().coerceIn(0, constraints.maxHeight)
                    val h = constraints.maxHeight - top
                    val placeable = measurable.measure(constraints.copy(minHeight = h, maxHeight = h))
                    layout(constraints.maxWidth, constraints.maxHeight) { placeable.place(0, top) }
                }
                .clip(SheetShape)
                .background(AppBackground)
                .pointerInput(Unit) { detectTapGestures { } },
        ) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(DragStripHeight)
                    .draggable(
                        state = draggableState,
                        orientation = Orientation.Vertical,
                        onDragStarted = { beginSession() },
                        onDragStopped = { velocity -> settle(velocity) },
                    )
                    .semantics {
                        contentDescription = "拖动调整面板高度"
                        customActions = listOf(
                            CustomAccessibilityAction("展开面板") { goTo(anchorsState.expanded); true },
                            CustomAccessibilityAction("收起面板") { goTo(anchorsState.half); true },
                            CustomAccessibilityAction("关闭面板") { dismiss(); true },
                        )
                    },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier
                        .size(width = 36.dp, height = 4.dp)
                        .clip(SharedLedgerRadius.Full)
                        .background(AppOutlineVariant),
                )
            }
            Column(Modifier.weight(1f).fillMaxWidth().nestedScroll(connection), content = content)
        }
    }
}
