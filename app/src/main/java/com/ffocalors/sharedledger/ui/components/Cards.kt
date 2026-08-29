package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.Payments
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.vector.ImageVector
import com.ffocalors.sharedledger.ui.theme.DividerSubtle
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SageGreenContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmHigh
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmHighest
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
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
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            SurfaceWarmHighest,
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(SharedLedgerRadius.ExtraLarge)
                .drawBehind {
                    val decorativeDiameter = SharedLedgerDimens.SummaryDecorativeSize.toPx()
                    val decorativeOffset = SharedLedgerDimens.SummaryDecorativeOffset.toPx()
                    val gradientCenter = Offset(
                        x = size.width - decorativeDiameter / 2f + decorativeOffset,
                        y = decorativeDiameter / 2f - decorativeOffset,
                    )
                    drawRect(
                        brush = Brush.radialGradient(
                            colors = listOf(
                                IconContainerSage.copy(alpha = 0.3f),
                                Color.Transparent,
                            ),
                            center = gradientCenter,
                            radius = decorativeDiameter / 2f + SharedLedgerSpacing.Large.toPx(),
                        ),
                    )
                }
        ) {
            Column(modifier = Modifier.padding(SharedLedgerSpacing.Large)) {
                Text(
                    text = title,
                    style = SharedLedgerTextStyles.SummaryLabel,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                SummaryAmount(
                    amount = primaryAmount,
                    currencyCode = currencyCode,
                    modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                )
                if (statusContent != null) {
                    Box(modifier = Modifier.padding(top = SharedLedgerSpacing.Medium)) {
                        statusContent()
                    }
                }
                if (statistics.isNotEmpty()) {
                    HorizontalDivider(
                        modifier = Modifier.padding(top = SharedLedgerSpacing.Large),
                        color = DividerSubtle.copy(alpha = 0.6f),
                    )
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = SharedLedgerSpacing.Medium),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        statistics.take(3).forEachIndexed { index, statistic ->
                            Column(
                                modifier = Modifier.weight(1f),
                                horizontalAlignment = when (index) {
                                    0 -> Alignment.Start
                                    1 -> Alignment.CenterHorizontally
                                    else -> Alignment.End
                                },
                            ) {
                                Text(
                                    text = statistic.label,
                                    style = SharedLedgerTextStyles.SummaryLabel,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                Text(
                                    text = statistic.value,
                                    style = SharedLedgerTextStyles.SummaryStatValue,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Shared payable-status card used by both activity detail ledgers. */
@Composable
fun PaymentStatusCard(
    title: String,
    amount: BigDecimal,
    modifier: Modifier = Modifier,
    currencyCode: String = "CNY",
    containerColor: Color? = null,
    contentColor: Color? = null,
    iconTint: Color? = null,
    onClick: () -> Unit = {},
) {
    val resolvedContainer = containerColor ?: MaterialTheme.colorScheme.secondaryContainer
    val resolvedContent = contentColor ?: MaterialTheme.colorScheme.onSecondaryContainer
    val resolvedIconTint = iconTint ?: MaterialTheme.colorScheme.secondary
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(containerColor = resolvedContainer),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.secondary.copy(alpha = 0.25f),
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Surface(
                modifier = Modifier.size(SharedLedgerDimens.AvatarLarge),
                shape = SharedLedgerRadius.Full,
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = SharedLedgerElevation.Card,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Rounded.Payments,
                        contentDescription = null,
                        tint = resolvedIconTint,
                    )
                }
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(text = title, style = SharedLedgerTextStyles.BodySecondary, color = resolvedContent)
                AmountDisplay(
                    amount = amount,
                    currencyCode = currencyCode,
                    size = AmountSize.SubActivity,
                    emphasis = AmountEmphasis.Standard,
                    modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall / 2),
                )
            }
            Icon(
                imageVector = Icons.AutoMirrored.Rounded.ArrowForward,
                contentDescription = "查看待付款",
                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                tint = resolvedContent,
            )
        }
    }
}

@Composable
private fun SummaryAmount(
    amount: BigDecimal,
    currencyCode: String,
    modifier: Modifier = Modifier,
) {
    val formatted = MoneyFormatter.format(amount, currencyCode)
    val symbolLength = formatted.indexOfFirst { it.isDigit() }.takeIf { it >= 0 } ?: 0
    Row(modifier = modifier, verticalAlignment = Alignment.Bottom) {
        Text(
            text = formatted.take(symbolLength),
            style = SharedLedgerTextStyles.SummaryCurrency,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = formatted.drop(symbolLength),
            style = SharedLedgerTextStyles.SummaryAmount,
            color = MaterialTheme.colorScheme.onSurface,
        )
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
fun SubActivityCard(
    activity: SubActivityUiModel,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Surface(
                modifier = Modifier.size(SharedLedgerDimens.IconContainerLarge),
                shape = SharedLedgerRadius.Full,
                color = activity.iconContainerColor.takeUnless { it == Color.Unspecified }
                    ?: IconContainerSage,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = activity.icon,
                        contentDescription = null,
                        modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                        tint = activity.iconTint.takeUnless { it == Color.Unspecified }
                            ?: MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            ) {
                Text(
                    text = activity.name,
                    style = SharedLedgerTextStyles.Body,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    Surface(
                        shape = SharedLedgerRadius.Full,
                        color = SurfaceWarmHigh,
                    ) {
                        Text(
                            text = "${activity.participantCount}人参与",
                            modifier = Modifier.padding(
                                horizontal = SharedLedgerSpacing.Small,
                                vertical = SharedLedgerSpacing.XSmall / 2,
                            ),
                            style = SharedLedgerTextStyles.ActionLabel,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(
                        text = activity.updatedAt,
                        style = SharedLedgerTextStyles.ActionLabel,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
            AmountDisplay(
                amount = activity.amount,
                currencyCode = activity.currencyCode,
                size = AmountSize.SubActivity,
                fractionDigitsOverride = activity.fractionDigitsOverride,
            )
        }
    }
}

@Composable
fun AddSubActivityButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val borderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .drawWithContent {
                drawContent()
                drawRoundRect(
                    color = borderColor,
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(
                        SharedLedgerDimens.AddSubActivityCornerRadius.toPx(),
                    ),
                    style = androidx.compose.ui.graphics.drawscope.Stroke(
                        width = SharedLedgerDimens.AddSubActivityBorderWidth.toPx(),
                        pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(
                            floatArrayOf(
                                SharedLedgerSpacing.Small.toPx(),
                                SharedLedgerSpacing.Small.toPx(),
                            ),
                        ),
                    ),
                )
            },
        shape = SharedLedgerRadius.Large,
        color = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.primary,
    ) {
        Row(
            modifier = Modifier.padding(vertical = SharedLedgerSpacing.Medium),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Rounded.Add,
                contentDescription = null,
                modifier = Modifier.size(SharedLedgerDimens.IconMedium),
            )
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            Text(text = "添加子活动", style = SharedLedgerTextStyles.BodySecondary)
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
