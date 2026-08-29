package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer

@Composable
fun SharedLedgerTopBar(
    title: String,
    modifier: Modifier = Modifier,
    showBackButton: Boolean = false,
    avatarName: String = "我",
    onBackClick: () -> Unit = {},
    onMoreClick: () -> Unit = {},
    businessAction: (@Composable RowScope.() -> Unit)? = null,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = SharedLedgerDimens.TopBarHeight)
                .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (showBackButton) {
                IconButton(onClick = onBackClick) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Rounded.ArrowBack,
                        contentDescription = "返回",
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
            IconButton(onClick = onMoreClick) {
                Icon(
                    imageVector = Icons.Rounded.MoreVert,
                    contentDescription = "更多",
                )
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
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.BottomActionBar,
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = SharedLedgerElevation.Floating,
        tonalElevation = SharedLedgerElevation.Card,
    ) {
        Row(
            modifier = Modifier
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
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        modifier = Modifier
            .weight(if (emphasized) 1.25f else 1f)
            .clickable(onClick = action.onClick),
        shape = SharedLedgerRadius.Full,
        color = containerColor,
        contentColor = contentColor,
    ) {
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
                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
            )
            Spacer(Modifier.height(SharedLedgerSpacing.XSmall))
            Text(text = action.label, style = SharedLedgerTextStyles.Label)
        }
    }
}
