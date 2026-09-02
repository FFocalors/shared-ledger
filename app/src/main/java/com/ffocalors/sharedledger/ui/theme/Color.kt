package com.ffocalors.sharedledger.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

val SageGreen = Color(0xFF54643F)
val SageGreenContainer = Color(0xFFBDCFA2)
val SageGreenSoft = Color(0xFFD7E9BA)
val WarmOrange = Color(0xFFDDB480)
val WarmOrangeContainer = Color(0xFFFED39C)
val WarmBrown = Color(0xFF78582D)
val Cream = Color(0xFFEBE4D6)
val AppBackground = Color(0xFFFBF9F8)
val AppSurface = Color(0xFFFFFFFF)
val AppSurfaceLow = Color(0xFFF5F3F3)
val AppSurfaceVariant = Color(0xFFE4E2E2)
val DeepCharcoal = Color(0xFF1B1C1C)
val SoftCharcoal = Color(0xFF45483E)
val AppOutline = Color(0xFF75786E)
val AppOutlineVariant = Color(0xFFC5C8BB)
val ErrorRed = Color(0xFFBA1A1A)
val ErrorContainer = Color(0xFFFFDAD6)

/** Button palette tokens from the Stitch color reference. */
val SoftPrimary = Color(0xFFBDCFA2)
val SoftPrimaryContent = Color(0xFF4A4A4A)
val WarmSecondary = Color(0xFFDDB480)
val WarmSecondaryContent = Color(0xFF4A4A4A)
val Neutral = Color(0xFFEBE4D6)
val NeutralContent = Color(0xFF4A4A4A)
val Inverted = Color(0xFF4A4A4A)
val InvertedContent = Color(0xFFEBE4D6)

@Immutable
data class SharedLedgerButtonColorPair(
    val containerColor: Color,
    val contentColor: Color,
)

/** Explicit button tokens; Material color roles remain available for the rest of the app. */
@Immutable
data class SharedLedgerButtonPalette(
    val softPrimary: SharedLedgerButtonColorPair = SharedLedgerButtonColorPair(
        containerColor = SoftPrimary,
        contentColor = SoftPrimaryContent,
    ),
    val warmSecondary: SharedLedgerButtonColorPair = SharedLedgerButtonColorPair(
        containerColor = WarmSecondary,
        contentColor = WarmSecondaryContent,
    ),
    val neutral: SharedLedgerButtonColorPair = SharedLedgerButtonColorPair(
        containerColor = Neutral,
        contentColor = NeutralContent,
    ),
    val inverted: SharedLedgerButtonColorPair = SharedLedgerButtonColorPair(
        containerColor = Inverted,
        contentColor = InvertedContent,
    ),
)

val DefaultSharedLedgerButtonPalette = SharedLedgerButtonPalette()

/** WCAG 2 contrast ratio for a foreground/background pair. */
fun sharedLedgerContrastRatio(foreground: Color, background: Color): Double {
    fun channel(value: Float): Double {
        val normalized = value.toDouble()
        return if (normalized <= 0.03928) {
            normalized / 12.92
        } else {
            Math.pow((normalized + 0.055) / 1.055, 2.4)
        }
    }

    fun luminance(color: Color): Double =
        0.2126 * channel(color.red) +
            0.7152 * channel(color.green) +
            0.0722 * channel(color.blue)

    val foregroundLuminance = luminance(foreground)
    val backgroundLuminance = luminance(background)
    val lighter = maxOf(foregroundLuminance, backgroundLuminance)
    val darker = minOf(foregroundLuminance, backgroundLuminance)
    return (lighter + 0.05) / (darker + 0.05)
}

fun hasAccessibleButtonContrast(
    palette: SharedLedgerButtonColorPair,
    minimumRatio: Double = 4.5,
): Boolean = sharedLedgerContrastRatio(palette.contentColor, palette.containerColor) >= minimumRatio

// Semantic surfaces from the SharedLedger UI Concept Stitch design system.
val SurfaceWarm = Color(0xFFFBF9F8)
val SurfaceWarmLowest = Color(0xFFFFFFFF)
val SurfaceWarmLow = Color(0xFFF5F3F3)
val SurfaceWarmHigh = Color(0xFFEAE8E7)
val SurfaceWarmContainer = Color(0xFFEFEDED)
val SurfaceWarmHighest = Color(0xFFE4E2E2)
val IconContainerSage = Color(0xFFD7E9BA)
val IconContainerOrange = Color(0xFFFFDDB5)
val IconContainerNeutral = Color(0xFFE9E2D4)
val IconContainerNeutralTint = Color(0xFF575449)
val IconContainerTertiary = Color(0xFFCEC8BA)
val IconTintSage = Color(0xFF121F03)
val IconTintOrange = Color(0xFF2A1800)
val IconTintNeutral = Color(0xFF1E1B13)
val SubActivityBreakfastContainer = Color(0xFFFED39C)
val TextPrimary = Color(0xFF1B1C1C)
val TextSecondary = Color(0xFF45483E)
val DividerSubtle = Color(0xFFC5C8BB)

@Immutable
data class SharedLedgerSemanticColors(
    val success: Color,
    val onSuccess: Color,
    val successContainer: Color,
    val onSuccessContainer: Color,
    val warning: Color,
    val onWarning: Color,
    val warningContainer: Color,
    val onWarningContainer: Color,
    val payable: Color,
    val onPayable: Color,
    val disputed: Color,
    val onDisputed: Color,
)

internal val LightSharedLedgerSemanticColors = SharedLedgerSemanticColors(
    success = SageGreen,
    onSuccess = Color.White,
    successContainer = SageGreenSoft,
    onSuccessContainer = Color(0xFF3D4B29),
    warning = WarmBrown,
    onWarning = Color.White,
    warningContainer = Color(0xFFFFDDB5),
    onWarningContainer = Color(0xFF5E4118),
    payable = WarmOrange,
    onPayable = Color(0xFF2A1800),
    disputed = ErrorRed,
    onDisputed = Color.White,
)

internal val LocalSharedLedgerSemanticColors = staticCompositionLocalOf {
    LightSharedLedgerSemanticColors
}

val MaterialTheme.sharedLedgerColors: SharedLedgerSemanticColors
    @Composable get() = LocalSharedLedgerSemanticColors.current
