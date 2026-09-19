package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.layout.widthIn
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
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
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
    primaryAmount: BigDecimal?,
    statistics: List<SettlementStatistic>,
    modifier: Modifier = Modifier,
    currencyCode: String = "CNY",
    secondaryTitle: String? = null,
    secondaryAmount: BigDecimal? = null,
    statusContent: (@Composable () -> Unit)? = null,
) {
    val breathing = rememberSummaryBreathing()
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
                    val decorativeDiameter = SharedLedgerDimens.SummaryDecorativeSize.toPx() * breathing.scale
                    val gradientCenter = Offset(
                        x = size.width * breathing.centerXFraction,
                        y = size.height * breathing.centerYFraction,
                    )
                    drawRect(
                        brush = Brush.radialGradient(
                            colors = listOf(
                                IconContainerSage.copy(alpha = breathing.intensity),
                                Color.Transparent,
                            ),
                            center = gradientCenter,
                            radius = decorativeDiameter / 2f + SharedLedgerSpacing.Large.toPx(),
                        ),
                    )
                }
        ) {
            Column(modifier = Modifier.padding(SharedLedgerSpacing.Large)) {
                if (secondaryTitle != null) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Large),
                    ) {
                        SummaryMetric(title, primaryAmount, currencyCode, Modifier.weight(1f))
                        SummaryMetric(secondaryTitle, secondaryAmount, currencyCode, Modifier.weight(1f))
                    }
                } else {
                    Text(
                        text = title,
                        style = SharedLedgerTextStyles.SummaryLabel,
                        color = MaterialTheme.colorScheme.outline,
                    )
                    if (primaryAmount != null) {
                        SummaryAmount(
                            amount = primaryAmount,
                            currencyCode = currencyCode,
                            modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                        )
                    } else {
                        Text(
                            text = "—",
                            style = SharedLedgerTextStyles.SummaryAmount,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                        )
                    }
                }
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
                                    color = MaterialTheme.colorScheme.outline,
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

private data class SummaryBreathing(
    val scale: Float,
    val centerXFraction: Float,
    val centerYFraction: Float,
    val intensity: Float,
)

/** Slow breathing for the summary card's decorative gradient; static in previews. */
@Composable
private fun rememberSummaryBreathing(): SummaryBreathing {
    if (LocalInspectionMode.current) {
        return SummaryBreathing(scale = 1f, centerXFraction = 0.82f, centerYFraction = 0.2f, intensity = 0.3f)
    }
    val transition = rememberInfiniteTransition(label = "summaryBreathing")
    val scale by transition.animateFloat(
        initialValue = 0.75f,
        targetValue = 1.35f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 5200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "summaryBreathingScale",
    )
    val centerXFraction by transition.animateFloat(
        initialValue = 0.15f,
        targetValue = 0.88f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 7300, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "summaryBreathingX",
    )
    val centerYFraction by transition.animateFloat(
        initialValue = 0.1f,
        targetValue = 0.85f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 6100, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "summaryBreathingY",
    )
    val intensity by transition.animateFloat(
        initialValue = 0.15f,
        targetValue = 0.5f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 4600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "summaryBreathingIntensity",
    )
    return SummaryBreathing(
        scale = scale,
        centerXFraction = centerXFraction,
        centerYFraction = centerYFraction,
        intensity = intensity,
    )
}

@Composable
private fun SummaryMetric(
    title: String,
    amount: BigDecimal?,
    currencyCode: String,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        Text(title, style = SharedLedgerTextStyles.SummaryLabel, color = MaterialTheme.colorScheme.outline)
        if (amount == null) {
            Text(
                "—",
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.outline,
                modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
            )
        } else {
            AmountDisplay(
                amount = amount,
                currencyCode = currencyCode,
                size = AmountSize.Medium,
                modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
            )
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
            MaterialTheme.colorScheme.secondary.copy(alpha = SharedLedgerDimens.CardBorderAlpha),
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
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = SharedLedgerDimens.CardBorderAlpha),
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
                    color = MaterialTheme.colorScheme.outline,
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
    val pressScale = rememberPressScaleState()
    Card(
        onClick = onClick,
        modifier = pressScale.modifier.then(modifier).fillMaxWidth()
            .pressInnerShadow(SharedLedgerRadius.Large, pressScale.shadowAlpha),
        interactionSource = pressScale.interactionSource,
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = SharedLedgerDimens.CardBorderAlpha),
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
                    if (activity.participantCount != null) {
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
                                color = MaterialTheme.colorScheme.outline,
                            )
                        }
                    }
                    Text(
                        text = activity.updatedAt,
                        style = SharedLedgerTextStyles.ActionLabel,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
            if (activity.amountAvailable) {
                AmountDisplay(
                    amount = activity.amount,
                    currencyCode = activity.currencyCode,
                    size = AmountSize.SubActivity,
                    fractionDigitsOverride = activity.fractionDigitsOverride,
                )
            } else {
                Text(
                    text = "—",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
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
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .drawWithContent {
                drawContent()
                drawRoundRect(
                    color = borderColor,
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(
                        SharedLedgerRadius.LargeCorner.toPx(),
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
    icon: ImageVector? = null,
    onClick: () -> Unit = {},
) {
    val pressScale = rememberPressScaleState()
    Card(
        onClick = onClick,
        modifier = pressScale.modifier.then(
            modifier
                .fillMaxWidth()
                .semantics {
                    if (expense.isDeleted) stateDescription = "已删除，不计入统计"
                }
                .pressInnerShadow(SharedLedgerRadius.Large, pressScale.shadowAlpha),
        ),
        interactionSource = pressScale.interactionSource,
        shape = SharedLedgerRadius.Large,
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = SharedLedgerDimens.CardBorderAlpha),
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Row(
            modifier = Modifier
                .padding(SharedLedgerSpacing.Medium),
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
                        imageVector = icon ?: expenseIconVector(expense.iconKey),
                        contentDescription = null,
                        modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                        tint = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                }
            }
            Column(
                modifier = Modifier
                    .weight(1f)
                    .widthIn(min = 0.dp),
            ) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = expense.name,
                        modifier = Modifier.weight(1f),
                        style = SharedLedgerTextStyles.Body,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    )
                    if (expense.isDeleted) {
                        Surface(
                            shape = SharedLedgerRadius.Full,
                            color = MaterialTheme.colorScheme.errorContainer,
                            contentColor = MaterialTheme.colorScheme.onErrorContainer,
                        ) {
                            Text(
                                text = "已删除",
                                modifier = Modifier.padding(
                                    horizontal = SharedLedgerSpacing.Small,
                                    vertical = SharedLedgerSpacing.XSmall,
                                ),
                                style = SharedLedgerTextStyles.Label,
                            )
                        }
                    }
                }
                Text(
                    text = "${expense.payerName}付款 · ${expense.participantCount}人参与",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.outline,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
                expense.time?.let {
                    Text(
                        text = it,
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.outline,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    )
                }
                if (expense.participants.isNotEmpty()) {
                    ParticipantAvatarGroup(
                        participants = expense.participants,
                        // Match Stitch's compact expense row: two avatars plus one overflow chip.
                        maxVisible = 2,
                        modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                    )
                }
            }
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            if (expense.amountAvailable) {
                AmountDisplay(
                    amount = expense.amount,
                    currencyCode = expense.currencyCode,
                    size = AmountSize.Small,
                )
            } else {
                Text(
                    text = "—",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
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
