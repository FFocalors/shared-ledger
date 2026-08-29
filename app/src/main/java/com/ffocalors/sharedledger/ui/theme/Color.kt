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
