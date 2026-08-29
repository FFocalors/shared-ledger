package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.WarningAmber
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.ffocalors.sharedledger.ui.theme.SageGreenContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors
import java.math.BigDecimal

@Composable
fun SettlementSummaryCard(
    title: String,
    primaryAmount: BigDecimal,
    statistics: List<SettlementStatistic>,
    modifier: Modifier = Modifier,
    currencyCode: String = "CNY",
    statusContent: (@Composable () -> Unit)? = null,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(
            containerColor = SageGreenContainer.copy(alpha = 0.18f),
        ),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f),
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Text(
                text = title,
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            AmountDisplay(
                amount = primaryAmount,
                currencyCode = currencyCode,
                size = AmountSize.Large,
                emphasis = AmountEmphasis.Standard,
            )
            if (statusContent != null) {
                statusContent()
            }
            if (statistics.isNotEmpty()) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
                ) {
                    statistics.forEach { statistic ->
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = statistic.label,
                                style = SharedLedgerTextStyles.Label,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Text(
                                text = statistic.value,
                                style = SharedLedgerTextStyles.Body,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ActivityCard(
    activity: ActivityCardUiModel,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val icon = when (activity.kind) {
        ActivityKind.Standard -> Icons.Rounded.Restaurant
        ActivityKind.Large -> Icons.Rounded.FlightTakeoff
    }
    val kindLabel = when (activity.kind) {
        ActivityKind.Standard -> "普通活动"
        ActivityKind.Large -> "大型活动"
    }
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f),
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
            ) {
                Surface(
                    shape = SharedLedgerRadius.Full,
                    color = if (activity.kind == ActivityKind.Large) {
                        SageGreenContainer
                    } else {
                        WarmOrangeContainer
                    },
                ) {
                    Box(
                        modifier = Modifier.padding(SharedLedgerSpacing.Small),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = icon,
                            contentDescription = null,
                            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                        )
                    }
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = activity.name,
                        style = SharedLedgerTextStyles.CardTitle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "$kindLabel · ${activity.participantCount}人",
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                StatusChip(activity.status)
            }
            activity.totalAmount?.let {
                Column {
                    Text(
                        text = if (activity.status == ActivityStatus.PendingSettlement) {
                            "待结算"
                        } else {
                            "总金额"
                        },
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    AmountDisplay(
                        amount = it,
                        currencyCode = activity.currencyCode,
                        size = AmountSize.Medium,
                        emphasis = AmountEmphasis.Primary,
                    )
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "更新于 ${activity.updatedAt}",
                    modifier = Modifier.weight(1f),
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                ParticipantAvatarGroup(activity.participants)
            }
        }
    }
}

@Composable
fun ExpenseCard(
    expense: ExpenseCardUiModel,
    modifier: Modifier = Modifier,
    icon: ImageVector = Icons.AutoMirrored.Rounded.ReceiptLong,
    onClick: () -> Unit = {},
) {
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f),
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Surface(
                shape = SharedLedgerRadius.Full,
                color = WarmOrangeContainer,
            ) {
                Box(
                    modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                        tint = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                }
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = expense.name,
                    style = SharedLedgerTextStyles.Body,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "${expense.payerName}付款 · ${expense.participantCount}人参与",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                expense.time?.let {
                    Text(
                        text = it,
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
                if (expense.participants.isNotEmpty()) {
                    ParticipantAvatarGroup(
                        participants = expense.participants,
                        modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                    )
                }
            }
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            AmountDisplay(
                amount = expense.amount,
                currencyCode = expense.currencyCode,
                size = AmountSize.Small,
            )
        }
    }
}

@Composable
fun WarningCard(
    text: String,
    modifier: Modifier = Modifier,
    title: String = "请注意",
) {
    val semantic = MaterialTheme.sharedLedgerColors
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        color = semantic.warningContainer.copy(alpha = 0.72f),
        contentColor = semantic.onWarningContainer,
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            semantic.warning.copy(alpha = 0.18f),
        ),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(
                imageVector = Icons.Rounded.WarningAmber,
                contentDescription = null,
                modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                tint = semantic.warning,
            )
            Column {
                Text(text = title, style = SharedLedgerTextStyles.Body)
                Text(
                    text = text,
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = semantic.onWarningContainer,
                )
            }
        }
    }
}
