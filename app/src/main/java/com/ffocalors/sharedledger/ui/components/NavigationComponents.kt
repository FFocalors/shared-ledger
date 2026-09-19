package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.semantics.Role
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.CircleShape
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.TextPrimary
import com.ffocalors.sharedledger.ui.theme.IconContainerNeutral
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconTintNeutral
import com.ffocalors.sharedledger.ui.theme.IconTintOrange
import com.ffocalors.sharedledger.ui.theme.IconTintSage
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLow
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.HazeTint
import dev.chrisbanes.haze.hazeEffect
import dev.chrisbanes.haze.hazeSource
import dev.chrisbanes.haze.rememberHazeState

@Composable
fun SharedLedgerTopBar(
    title: String,
    modifier: Modifier = Modifier,
    containerColor: Color = MaterialTheme.colorScheme.background,
    showBackButton: Boolean = false,
    avatarName: String = "我",
    avatarStyle: String? = null,
    avatarStableKey: String? = null,
    onAvatarClick: (() -> Unit)? = null,
    onBackClick: (() -> Unit)? = null,
    onMoreClick: (() -> Unit)? = null,
    actionIcon: ImageVector? = null,
    actionContentDescription: String? = null,
    onActionClick: (() -> Unit)? = null,
    showMoreButton: Boolean = true,
    businessAction: (@Composable RowScope.() -> Unit)? = null,
    titleStyle: TextStyle = SharedLedgerTextStyles.CardTitle,
    titleColor: Color = MaterialTheme.colorScheme.onBackground,
    moreButtonContainerColor: Color = Color.Transparent,
    hazeState: HazeState? = null,
) {
    val chromeModifier = if (hazeState != null) {
        Modifier
            .hazeEffect(
                state = hazeState,
                style = chromeHazeStyle(containerColor),
            ) {
                mask = smoothAlphaMask(fadeOut = true)
            }
            .then(chromeColorOverlay(containerColor, fadeOut = true))
    } else {
        Modifier.drawWithCache {
            val edgeBrush = Brush.verticalGradient(
                colorStops = smoothAlphaColorStops(containerColor, fadeOut = true),
                startY = 0f,
                endY = size.height,
            )
            onDrawBehind {
                drawRect(brush = edgeBrush)
            }
        }
    }
    Column(modifier = modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(containerColor)
                .statusBarsPadding(),
            contentAlignment = Alignment.Center,
        ) {
            Row(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxWidth()
                    .height(SharedLedgerDimens.TopBarHeight)
                    .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding, vertical = SharedLedgerSpacing.MediumSmall),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (showBackButton && onBackClick != null) {
                    Box(
                        modifier = Modifier
                            .size(SharedLedgerDimens.TopBarActionSize)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f), CircleShape)
                            .clickable(role = Role.Button, onClick = onBackClick),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Rounded.ArrowBack,
                            contentDescription = "返回",
                            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                            tint = TextPrimary,
                        )
                    }
                } else {
                    val avatarModifier = if (onAvatarClick != null) {
                        Modifier
                            .clip(CircleShape)
                            .clickable(onClick = onAvatarClick)
                            .semantics { contentDescription = "打开个人信息" }
                    } else {
                        Modifier
                    }
                    ParticipantAvatar(
                        name = avatarName,
                        modifier = avatarModifier,
                        background = AvatarBackground.Bound(avatarStyle, avatarStableKey),
                        size = SharedLedgerDimens.AvatarMedium,
                    )
                }
                Text(
                    text = title,
                    modifier = Modifier
                        .weight(1f)
                        .padding(horizontal = SharedLedgerSpacing.Medium),
                    style = titleStyle,
                    color = titleColor,
                )
                businessAction?.invoke(this)
                if (actionIcon != null && onActionClick != null) {
                    Box(
                        modifier = Modifier
                            .size(SharedLedgerDimens.TopBarActionSize)
                            .clip(CircleShape)
                            .clickable(role = Role.Button, onClick = onActionClick),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = actionIcon,
                            contentDescription = actionContentDescription ?: "操作",
                            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
                if (showMoreButton && onMoreClick != null) {
                    Box(
                        modifier = Modifier
                            .size(SharedLedgerDimens.TopBarActionSize)
                            .clip(CircleShape)
                            .background(moreButtonContainerColor, CircleShape)
                            .clickable(role = Role.Button, onClick = onMoreClick),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.MoreVert,
                            contentDescription = "更多",
                            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(SharedLedgerDimens.ChromeTransitionDepth)
                .then(chromeModifier),
        )
    }
}

@Composable
fun SharedLedgerBottomActionBar(
    actions: List<BottomActionItem>,
    modifier: Modifier = Modifier,
    emphasizedIndex: Int = 1,
    backgroundColor: Color = MaterialTheme.colorScheme.background,
    hazeState: HazeState? = null,
) {
    if (actions.isEmpty()) return
    SharedLedgerBottomChrome(
        modifier = modifier,
        backgroundColor = backgroundColor,
        imeAware = false,
        hazeState = hazeState,
    ) {
        Surface(
            modifier = Modifier
                .widthIn(max = SharedLedgerDimens.BottomActionBarMaxWidth)
                .fillMaxWidth(),
            shape = SharedLedgerRadius.BottomActionBar,
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = SharedLedgerElevation.Floating,
            tonalElevation = SharedLedgerElevation.Card,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(SharedLedgerDimens.BottomActionBarHeight)
                    .padding(SharedLedgerDimens.BottomActionBarPadding),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                actions.forEachIndexed { index, action ->
                    BottomAction(
                        action = action,
                        emphasized = index == emphasizedIndex,
                    )
                }
            }
        }
    }
}

@Composable
private fun RowScope.BottomAction(
    action: BottomActionItem,
    emphasized: Boolean,
) {
    val containerColor = if (emphasized) {
        WarmOrangeContainer
    } else {
        Color.Transparent
    }
    val contentColor = if (emphasized) {
        MaterialTheme.colorScheme.onSecondaryContainer
    } else {
        MaterialTheme.colorScheme.onSurface
    }
    Surface(
        onClick = action.onClick,
        modifier = Modifier.weight(if (emphasized) 1.25f else 1f),
        shape = SharedLedgerRadius.Full,
        color = containerColor,
        contentColor = contentColor,
    ) {
        if (emphasized) {
            Row(
                modifier = Modifier.padding(
                    horizontal = SharedLedgerSpacing.MediumSmall,
                    vertical = SharedLedgerSpacing.MediumSmall,
                ),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = action.icon,
                    contentDescription = action.label,
                    modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                    tint = MaterialTheme.colorScheme.onSecondaryContainer,
                )
                Spacer(Modifier.width(SharedLedgerSpacing.Small))
                Text(
                    text = action.label,
                    style = SharedLedgerTextStyles.BottomActionEmphasizedLabel,
                    maxLines = 1,
                    softWrap = false,
                )
            }
        } else {
            Column(
                modifier = Modifier.padding(
                    horizontal = SharedLedgerSpacing.Small,
                    vertical = SharedLedgerSpacing.Small,
                ),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Icon(
                    imageVector = action.icon,
                    contentDescription = action.label,
                    modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                    tint = MaterialTheme.colorScheme.outline,
                )
                Spacer(Modifier.height(SharedLedgerSpacing.XSmall))
                Text(
                    text = action.label,
                    style = SharedLedgerTextStyles.BottomActionLabel,
                    maxLines = 1,
                    softWrap = false,
                )
            }
        }
    }
}

@Composable
fun SharedLedgerActionItemsRow(
    items: List<QuickActionItem>,
    modifier: Modifier = Modifier,
) {
    require(items.isNotEmpty()) { "快捷操作至少需要一个入口" }
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
    ) {
        items.forEachIndexed { index, item ->
            SharedLedgerActionItem(
                item = item,
                accentColor = when (index) {
                    0 -> IconContainerSage
                    1 -> IconContainerOrange
                    else -> IconContainerNeutral
                },
                accentTint = when (index) {
                    0 -> IconTintSage
                    1 -> IconTintOrange
                    else -> IconTintNeutral
                },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun SharedLedgerActionItem(
    item: QuickActionItem,
    accentColor: Color,
    accentTint: Color,
    modifier: Modifier = Modifier,
) {
    val containerColor = SurfaceWarmLow
    Surface(
        onClick = item.onClick,
        modifier = modifier,
        shape = SharedLedgerRadius.Large,
        color = containerColor,
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = androidx.compose.foundation.BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = SharedLedgerDimens.CardBorderAlpha),
        ),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Surface(
                modifier = Modifier.size(SharedLedgerDimens.ActionIconContainer),
                shape = SharedLedgerRadius.Full,
                color = item.iconContainerColor.takeUnless { it == Color.Unspecified }
                    ?: accentColor,
                contentColor = item.iconTint.takeUnless { it == Color.Unspecified }
                    ?: accentTint,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = item.icon,
                        contentDescription = item.label,
                        modifier = Modifier.size(SharedLedgerDimens.ActionIcon),
                    )
                }
            }
            Text(
                text = item.label,
                style = SharedLedgerTextStyles.ActionLabel,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                softWrap = false,
            )
        }
    }
}

/**
 * Standard bottom bar for form pages: gradient scrim around a full-width CTA slot.
 * Scrollable content only needs `innerPadding bottom + Spacing.Medium` — no per-page guesses.
 */
@Composable
fun SharedLedgerCtaBottomBar(
    modifier: Modifier = Modifier,
    backgroundColor: Color = MaterialTheme.colorScheme.background,
    hazeState: HazeState? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    SharedLedgerBottomChrome(
        modifier = modifier,
        backgroundColor = backgroundColor,
        imeAware = true,
        hazeState = hazeState,
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            content = content,
        )
    }
}

/**
 * Shared translucent edge between scrolling content and fixed bottom controls.
 * The restrained multi-stop tint reads as frosted glass without applying a
 * continuous backdrop blur to the scrolling layer.
 */
@Composable
private fun SharedLedgerBottomChrome(
    modifier: Modifier,
    backgroundColor: Color,
    imeAware: Boolean,
    hazeState: HazeState?,
    content: @Composable () -> Unit,
) {
    val chromeModifier = if (hazeState != null) {
        Modifier.hazeEffect(
            state = hazeState,
            style = chromeHazeStyle(backgroundColor),
        ) {
            mask = smoothAlphaMask(fadeOut = false)
        }.then(chromeColorOverlay(backgroundColor, fadeOut = false))
    } else {
        Modifier.background(
            Brush.verticalGradient(
                colorStops = smoothAlphaColorStops(backgroundColor, fadeOut = false),
            ),
        )
    }
    Box(
        modifier = modifier
            .fillMaxWidth(),
        contentAlignment = Alignment.TopCenter,
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(SharedLedgerDimens.ChromeTransitionDepth)
                    .then(chromeModifier),
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(backgroundColor)
                    // Insets belong to the opaque lower chrome, not to its
                    // transparent parent. This keeps the bar visually joined
                    // to the physical screen/IME edge and prevents scrolling
                    // content from showing through beneath the CTA.
                    .navigationBarsPadding()
                    .then(if (imeAware) Modifier.imePadding() else Modifier)
                    .padding(
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = SharedLedgerSpacing.Large,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                Box(
                    modifier = Modifier
                        .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                        .fillMaxWidth(),
                    contentAlignment = Alignment.TopCenter,
                ) {
                    content()
                }
            }
        }
    }
}

/**
 * Builds a dense smoothstep alpha ramp so the tint changes continuously across
 * the short chrome transition, without a visible midpoint stop or hard edge.
 * The supplied color remains the only tint source, so theme/container changes
 * are reflected by the same draw pass as the surrounding chrome.
 */
private fun smoothAlphaColorStops(
    color: Color,
    fadeOut: Boolean,
): Array<Pair<Float, Color>> {
    val stopCount = 17
    return Array(stopCount) { index ->
        val position = index / (stopCount - 1f)
        val smoothPosition = position * position * (3f - 2f * position)
        val alpha = if (fadeOut) 1f - smoothPosition else smoothPosition
        position to color.copy(alpha = alpha)
    }
}

private fun chromeHazeStyle(color: Color): HazeStyle = HazeStyle(
    backgroundColor = color.copy(alpha = 0.96f),
    tint = HazeTint(color.copy(alpha = 0.18f)),
    blurRadius = 20.dp,
    noiseFactor = 0f,
)

private fun smoothAlphaMask(fadeOut: Boolean): Brush = Brush.verticalGradient(
    colorStops = smoothAlphaColorStops(Color.White, fadeOut),
)

/**
 * Keeps the first/last strip pixel continuous with the opaque chrome while Haze
 * still contributes sampled content through the rest of the transition.
 */
private fun chromeColorOverlay(color: Color, fadeOut: Boolean): Modifier =
    Modifier.drawWithCache {
        val overlayBrush = Brush.verticalGradient(
            colorStops = edgeOverlayColorStops(color, fadeOut),
            startY = 0f,
            endY = size.height,
        )
        onDrawWithContent {
            drawContent()
            drawRect(brush = overlayBrush)
        }
    }

/**
 * Only bridges the opaque chrome edge. The remaining part of the strip stays
 * transparent so Haze's sampled content remains visible instead of being
 * replaced by a second full-length fixed-color fade.
 */
private fun edgeOverlayColorStops(
    color: Color,
    fadeOut: Boolean,
): Array<Pair<Float, Color>> {
    val stopCount = 17
    val edgeStart = if (fadeOut) 0f else 0.6f
    val edgeEnd = if (fadeOut) 0.4f else 1f
    return Array(stopCount) { index ->
        val position = index / (stopCount - 1f)
        val edgeProgress = ((position - edgeStart) / (edgeEnd - edgeStart)).coerceIn(0f, 1f)
        val smoothProgress = edgeProgress * edgeProgress * (3f - 2f * edgeProgress)
        val alpha = if (fadeOut) 1f - smoothProgress else smoothProgress
        position to color.copy(alpha = alpha)
    }
}

@Composable
fun rememberSharedLedgerHazeState(): HazeState = rememberHazeState()

fun Modifier.sharedLedgerHazeSource(state: HazeState): Modifier = hazeSource(state)
