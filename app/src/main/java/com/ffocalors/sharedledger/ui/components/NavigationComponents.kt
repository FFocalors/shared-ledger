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
import androidx.compose.foundation.shape.CircleShape
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
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

@Composable
fun SharedLedgerTopBar(
    title: String,
    modifier: Modifier = Modifier,
    containerColor: Color = MaterialTheme.colorScheme.background,
    showBackButton: Boolean = false,
    avatarName: String = "我",
    onBackClick: () -> Unit = {},
    onMoreClick: () -> Unit = {},
    businessAction: (@Composable RowScope.() -> Unit)? = null,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = containerColor,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding(),
            contentAlignment = Alignment.Center,
        ) {
            Row(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxWidth()
                    .height(SharedLedgerDimens.TopBarHeight)
                    .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding, vertical = SharedLedgerSpacing.Medium),
                verticalAlignment = Alignment.CenterVertically,
            ) {
            if (showBackButton) {
                Box(
                    modifier = Modifier
                        .size(SharedLedgerDimens.TopBarActionSize)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f), CircleShape)
                        .clickable(onClick = onBackClick),
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
                ParticipantAvatar(
                    name = avatarName,
                    size = SharedLedgerDimens.AvatarMedium,
                )
            }
            Text(
                text = title,
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = SharedLedgerSpacing.Medium),
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.onBackground,
            )
            businessAction?.invoke(this)
            Box(
                modifier = Modifier
                    .size(SharedLedgerDimens.TopBarActionSize)
                    .clickable(onClick = onMoreClick),
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
}

@Composable
fun SharedLedgerBottomActionBar(
    actions: List<BottomActionItem>,
    modifier: Modifier = Modifier,
    emphasizedIndex: Int = 1,
) {
    require(actions.isNotEmpty()) { "底部操作栏至少需要一个操作" }
    Box(
        modifier = modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
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
        modifier = Modifier
            .weight(if (emphasized) 1.25f else 1f)
            .clickable(onClick = action.onClick),
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
    val borderAlpha = 0.3f
    Surface(
        modifier = modifier.clickable(onClick = item.onClick),
        shape = SharedLedgerRadius.Large,
        color = containerColor,
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = androidx.compose.foundation.BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = borderAlpha),
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
