package com.ffocalors.sharedledger.ui.agent

import androidx.compose.animation.core.DecayAnimationSpec
import androidx.compose.animation.core.calculateTargetValue
import kotlin.math.abs

/**
 * Pure physics helpers for [AgentBottomSheet]. All offsets are the sheet's top edge in px
 * (0 = screen top, larger = lower). Velocities are px/s, positive = moving down.
 */
internal object AgentSheetPhysics {
    /** Fling speed above which a release must move at least one anchor. */
    const val MinStepVelocityDp = 1800f
    private const val RubberCoefficient = 0.55f

    /** Maps a finger overshoot (px past Expanded) to a damped displacement in [0, limitPx). */
    fun rubberBand(overshootPx: Float, limitPx: Float): Float {
        if (overshootPx <= 0f || limitPx <= 0f) return 0f
        return limitPx * (1f - 1f / (overshootPx * RubberCoefficient / limitPx + 1f))
    }

    /** Inverse of [rubberBand]: the finger overshoot that produces [displacementPx]. */
    fun rubberBandInverse(displacementPx: Float, limitPx: Float): Float {
        if (displacementPx <= 0f || limitPx <= 0f) return 0f
        val ratio = (displacementPx / limitPx).coerceAtMost(0.999f)
        return (1f / (1f - ratio) - 1f) * limitPx / RubberCoefficient
    }

    /** Where the sheet would come to rest if it simply decayed from [offset] with [velocity]. */
    fun projectedLanding(offset: Float, velocity: Float, decay: DecayAnimationSpec<Float>): Float =
        offset + decay.calculateTargetValue(0f, velocity)

    /**
     * Chooses the anchor to settle on after release. [anchors] are sheet-top offsets in any order.
     * Picks the anchor nearest to the projected landing; if |velocity| exceeds
     * [MinStepVelocityDp] the result is pushed at least to the next anchor beyond [offset] in the
     * direction of travel (when one exists).
     */
    fun chooseAnchor(
        offset: Float,
        velocity: Float,
        anchors: List<Float>,
        decay: DecayAnimationSpec<Float>,
        pxPerDp: Float,
    ): Float {
        val sorted = anchors.sorted()
        val projected = projectedLanding(offset, velocity, decay)
        var target = sorted.minBy { abs(it - projected) }
        if (abs(velocity) > MinStepVelocityDp * pxPerDp) {
            if (velocity > 0f) {
                sorted.firstOrNull { it > offset + Epsilon }?.let { target = maxOf(target, it) }
            } else {
                sorted.lastOrNull { it < offset - Epsilon }?.let { target = minOf(target, it) }
            }
        }
        return target
    }

    private const val Epsilon = 0.5f
}
