package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.Image
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors

@Composable
fun ParticipantAvatar(
    name: String,
    modifier: Modifier = Modifier,
    image: Painter? = null,
    backgroundColor: Color = MaterialTheme.colorScheme.primaryContainer,
    size: Dp = SharedLedgerDimens.AvatarMedium,
) {
    Surface(
        modifier = modifier.size(size),
        shape = CircleShape,
        color = backgroundColor,
        border = BorderStroke(
            SharedLedgerDimens.AvatarBorder,
            MaterialTheme.colorScheme.background,
        ),
    ) {
        if (image != null) {
            Image(
                painter = image,
                contentDescription = "$name 的头像",
                modifier = Modifier.clip(CircleShape),
                contentScale = ContentScale.Crop,
            )
        } else {
            Box(contentAlignment = Alignment.Center) {
                Text(
                    text = name.trim().take(1).ifEmpty { "账" },
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    maxLines = 1,
                    overflow = TextOverflow.Clip,
                )
            }
        }
    }
}

@Composable
fun ParticipantAvatarGroup(
    participants: List<ParticipantUiModel>,
    modifier: Modifier = Modifier,
    maxVisible: Int = 3,
    avatarSize: Dp = SharedLedgerDimens.AvatarSmall,
) {
    val visible = participants.take(maxVisible.coerceAtLeast(0))
    val overflowCount = (participants.size - visible.size).coerceAtLeast(0)
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerDimens.AvatarOverlap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        visible.forEach { participant ->
            ParticipantAvatar(
                name = participant.name,
                backgroundColor = participant.backgroundColor,
                size = avatarSize,
            )
        }
        if (overflowCount > 0) {
            Surface(
                modifier = Modifier
                    .height(avatarSize)
                    .defaultMinSize(minWidth = avatarSize),
                shape = CircleShape,
                color = MaterialTheme.colorScheme.surfaceVariant,
            ) {
                Box(
                    modifier = Modifier
                        .height(avatarSize)
                        .padding(horizontal = SharedLedgerSpacing.XSmall),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "+$overflowCount",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        softWrap = false,
                    )
                }
            }
        }
    }
}

@Composable
fun StatusChip(
    status: ActivityStatus,
    modifier: Modifier = Modifier,
) {
    val semantic = MaterialTheme.sharedLedgerColors
    val (label, colors) = when (status) {
        ActivityStatus.InProgress -> "进行中" to (
            MaterialTheme.colorScheme.primaryContainer to
                MaterialTheme.colorScheme.onPrimaryContainer
            )
        ActivityStatus.PendingSettlement -> "待结算" to (
            semantic.warningContainer to semantic.onWarningContainer
            )
        ActivityStatus.Settled -> "已结清" to (
            semantic.successContainer to semantic.onSuccessContainer
            )
        ActivityStatus.Archived -> "已归档" to (
            MaterialTheme.colorScheme.surfaceVariant to
                MaterialTheme.colorScheme.onSurfaceVariant
            )
        ActivityStatus.Disputed -> "有争议" to (
            MaterialTheme.colorScheme.errorContainer to
                MaterialTheme.colorScheme.onErrorContainer
            )
    }
    Surface(
        modifier = modifier,
        shape = CircleShape,
        color = colors.first,
        contentColor = colors.second,
    ) {
        Text(
            text = label,
            modifier = Modifier.padding(
                horizontal = SharedLedgerSpacing.MediumSmall,
                vertical = SharedLedgerSpacing.XSmall,
            ),
            style = SharedLedgerTextStyles.Label,
        )
    }
}
