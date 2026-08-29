package com.ffocalors.sharedledger.ui.theme

import android.os.Build
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val LightColorScheme = lightColorScheme(
    primary = SageGreen,
    onPrimary = Color.White,
    primaryContainer = SageGreenContainer,
    onPrimaryContainer = Color(0xFF495935),
    secondary = WarmBrown,
    onSecondary = Color.White,
    secondaryContainer = WarmOrangeContainer,
    onSecondaryContainer = WarmBrown,
    tertiary = Color(0xFF625E53),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFCEC8BA),
    onTertiaryContainer = Color(0xFF575449),
    background = AppBackground,
    onBackground = DeepCharcoal,
    surface = AppSurface,
    onSurface = DeepCharcoal,
    surfaceVariant = AppSurfaceVariant,
    onSurfaceVariant = SoftCharcoal,
    outline = AppOutline,
    outlineVariant = AppOutlineVariant,
    error = ErrorRed,
    onError = Color.White,
    errorContainer = ErrorContainer,
    onErrorContainer = Color(0xFF93000A),
)

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFFBBCDA0),
    onPrimary = Color(0xFF273315),
    primaryContainer = Color(0xFF3D4B29),
    onPrimaryContainer = Color(0xFFD7E9BA),
    secondary = Color(0xFFE9BF8B),
    onSecondary = Color(0xFF412D08),
    background = Color(0xFF1B1C1C),
    onBackground = Color(0xFFE4E2E2),
    surface = Color(0xFF303030),
    onSurface = Color(0xFFF2F0F0),
    surfaceVariant = Color(0xFF45483E),
    onSurfaceVariant = Color(0xFFC5C8BB),
)

private val SharedLedgerShapes = Shapes(
    small = SharedLedgerRadius.Small,
    medium = SharedLedgerRadius.Large,
    large = SharedLedgerRadius.ExtraLarge,
)

@Composable
fun SharedLedgerTheme(
    darkTheme: Boolean = false,
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && darkTheme -> {
            dynamicDarkColorScheme(context)
        }
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }

    CompositionLocalProvider(
        LocalSharedLedgerSemanticColors provides LightSharedLedgerSemanticColors,
    ) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = SharedLedgerTypography,
            shapes = SharedLedgerShapes,
            content = content,
        )
    }
}
