package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerButtonColorPair
import com.ffocalors.sharedledger.ui.theme.DefaultSharedLedgerButtonPalette
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.sharedLedgerContrastRatio

enum class SharedLedgerButtonTone {
    SoftPrimary,
    WarmSecondary,
    Neutral,
    Inverted,
    /** Kept for existing call sites; resolves to the Stitch SoftPrimary token. */
    Primary,
    Success,
    Warning,
    Danger,
}

/** Source-compatible name for existing screens while they migrate to button tones. */
typealias SharedLedgerButtonVariant = SharedLedgerButtonTone

/** Pure tone-to-palette mapping, kept public so the color contract can be unit tested. */
fun sharedLedgerButtonPaletteFor(tone: SharedLedgerButtonTone): SharedLedgerButtonColorPair = when (tone) {
    SharedLedgerButtonTone.SoftPrimary,
    SharedLedgerButtonTone.Primary,
    -> DefaultSharedLedgerButtonPalette.softPrimary
    SharedLedgerButtonTone.WarmSecondary,
    SharedLedgerButtonTone.Warning,
    -> DefaultSharedLedgerButtonPalette.warmSecondary
    SharedLedgerButtonTone.Neutral -> DefaultSharedLedgerButtonPalette.neutral
    SharedLedgerButtonTone.Inverted -> DefaultSharedLedgerButtonPalette.inverted
    SharedLedgerButtonTone.Success -> SharedLedgerButtonColorPair(SageGreen, Color.White)
    SharedLedgerButtonTone.Danger -> SharedLedgerButtonColorPair(ErrorRed, Color.White)
}

/**
 * Outlined controls use a foreground that remains readable against the page surface.
 * In particular, the light content color of the filled Inverted token is not reused here.
 */
fun sharedLedgerButtonOutlineColor(
    tone: SharedLedgerButtonTone,
    backgroundColor: Color = AppSurface,
): Color {
    if (tone == SharedLedgerButtonTone.Success) return SageGreen
    if (tone == SharedLedgerButtonTone.Danger) return ErrorRed

    val palette = sharedLedgerButtonPaletteFor(tone)
    return if (
        sharedLedgerContrastRatio(palette.containerColor, backgroundColor) >=
            sharedLedgerContrastRatio(palette.contentColor, backgroundColor)
    ) {
        palette.containerColor
    } else {
        palette.contentColor
    }
}

/**
 * Shared action contract: 56dp minimum touch height, one radius and one button typeface.
 * Semantic colors make destructive and completion actions distinguishable without changing layout.
 */
@Composable
fun SharedLedgerButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: SharedLedgerButtonTone = SharedLedgerButtonTone.SoftPrimary,
    enabled: Boolean = true,
    loading: Boolean = false,
    loadingText: String = "处理中",
    icon: ImageVector? = null,
    outlined: Boolean = false,
    tone: SharedLedgerButtonTone? = null,
) {
    val resolvedTone = tone ?: variant
    val palette = sharedLedgerButtonPaletteFor(resolvedTone)
    val outlineColor = sharedLedgerButtonOutlineColor(resolvedTone, MaterialTheme.colorScheme.surface)
    val isEnabled = enabled && !loading
    val resolvedText = if (loading) loadingText else text
    val buttonModifier = modifier
        .fillMaxWidth()
        .height(SharedLedgerDimens.ButtonHeight)
        .defaultMinSize(minHeight = SharedLedgerDimens.ButtonHeight)
        .semantics { contentDescription = resolvedText }

    if (outlined) {
        OutlinedButton(
            onClick = onClick,
            modifier = buttonModifier,
            enabled = isEnabled,
            shape = SharedLedgerRadius.Full,
            border = BorderStroke(1.dp, outlineColor.copy(alpha = if (isEnabled) 1f else 0.4f)),
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = outlineColor,
                disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
            ),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = SharedLedgerSpacing.Large),
        ) {
            SharedLedgerButtonContent(resolvedText, loading, icon, outlineColor)
        }
    } else {
        Button(
            onClick = onClick,
            modifier = buttonModifier,
            enabled = isEnabled,
            shape = SharedLedgerRadius.Full,
            colors = ButtonDefaults.buttonColors(
                containerColor = palette.containerColor,
                contentColor = palette.contentColor,
                disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
            ),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = SharedLedgerSpacing.Large),
        ) {
            SharedLedgerButtonContent(resolvedText, loading, icon, palette.contentColor)
        }
    }
}

@Composable
private fun SharedLedgerButtonContent(
    text: String,
    loading: Boolean,
    icon: ImageVector?,
    indicatorColor: androidx.compose.ui.graphics.Color,
) {
    if (loading) {
        CircularProgressIndicator(
            modifier = Modifier.size(20.dp),
            color = indicatorColor,
            strokeWidth = 2.dp,
        )
        Spacer(Modifier.width(SharedLedgerSpacing.Small))
    } else if (icon != null) {
        Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(SharedLedgerDimens.IconSmall))
        Spacer(Modifier.width(SharedLedgerSpacing.Small))
    }
    Text(text = text, style = SharedLedgerTextStyles.Button)
}

@Composable
fun SharedLedgerPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
) {
    SharedLedgerButton(
        text = text,
        onClick = onClick,
        modifier = modifier,
        enabled = enabled,
        icon = icon,
    )
}

@Composable
fun SharedLedgerSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    loading: Boolean = false,
    loadingText: String = "处理中",
) {
    SharedLedgerButton(
        text = text,
        onClick = onClick,
        modifier = modifier,
        variant = SharedLedgerButtonTone.WarmSecondary,
        enabled = enabled,
        loading = loading,
        loadingText = loadingText,
        icon = icon,
        outlined = true,
    )
}

@Composable
fun SharedLedgerTextField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    placeholder: String? = null,
    leadingIcon: (@Composable () -> Unit)? = null,
    trailingContent: (@Composable () -> Unit)? = null,
    error: String? = null,
    enabled: Boolean = true,
    singleLine: Boolean = true,
    minLines: Int = 1,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.defaultMinSize(minHeight = SharedLedgerDimens.TextFieldMinHeight),
        enabled = enabled,
        label = label?.let { { Text(it) } },
        placeholder = placeholder?.let { { Text(it) } },
        leadingIcon = leadingIcon,
        trailingIcon = trailingContent,
        supportingText = error?.let { { Text(it) } },
        isError = error != null,
        singleLine = singleLine,
        minLines = minLines,
        keyboardOptions = keyboardOptions,
        shape = SharedLedgerRadius.Input,
        textStyle = SharedLedgerTextStyles.Body,
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = MaterialTheme.colorScheme.surface,
            unfocusedContainerColor = MaterialTheme.colorScheme.surface,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant,
            focusedBorderColor = MaterialTheme.colorScheme.primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outlineVariant,
        ),
    )
}
