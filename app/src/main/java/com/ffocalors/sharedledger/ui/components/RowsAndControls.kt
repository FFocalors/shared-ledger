package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import java.math.BigDecimal

@Composable
fun AmountDisplay(
    amount: BigDecimal,
    modifier: Modifier = Modifier,
    currencyCode: String = "CNY",
    size: AmountSize = AmountSize.Medium,
    emphasis: AmountEmphasis = AmountEmphasis.Standard,
) {
    val semantic = MaterialTheme.sharedLedgerColors
    val style = when (size) {
        AmountSize.Large -> SharedLedgerTextStyles.AmountLarge
        AmountSize.Medium -> SharedLedgerTextStyles.AmountMedium
        AmountSize.Small -> SharedLedgerTextStyles.AmountSmall
    }
    val color = when (emphasis) {
        AmountEmphasis.Primary -> MaterialTheme.colorScheme.primary
        AmountEmphasis.Standard -> MaterialTheme.colorScheme.onSurface
        AmountEmphasis.Muted -> MaterialTheme.colorScheme.onSurfaceVariant
        AmountEmphasis.Warning -> semantic.warning
    }
    Text(
        text = MoneyFormatter.format(amount, currencyCode),
        modifier = modifier,
        style = style,
        color = color,
        maxLines = 1,
    )
}

@Composable
fun ParticipantAmountRow(
    participant: ParticipantUiModel,
    amount: BigDecimal,
    modifier: Modifier = Modifier,
    currencyCode: String = "CNY",
    editable: Boolean = false,
    editableAmount: String = amount.toPlainString(),
    onAmountChange: (String) -> Unit = {},
    status: ParticipantAmountStatus = ParticipantAmountStatus.None,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(
            width = SharedLedgerDimens.OutlineWidth,
            color = MaterialTheme.colorScheme.outlineVariant,
        ),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            ParticipantAvatar(
                name = participant.name,
                backgroundColor = participant.backgroundColor,
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = participant.name,
                    style = SharedLedgerTextStyles.Body,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                ParticipantAmountStatusLabel(status)
            }
            if (editable) {
                SharedLedgerTextField(
                    value = editableAmount,
                    onValueChange = onAmountChange,
                    modifier = Modifier.width(SharedLedgerDimens.ParticipantAmountFieldWidth),
                    leadingIcon = {
                        Text(
                            text = MoneyFormatter.format(BigDecimal.ZERO, currencyCode)
                                .takeWhile { !it.isDigit() && it != '0' },
                        )
                    },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                )
            } else {
                AmountDisplay(
                    amount = amount,
                    currencyCode = currencyCode,
                    size = AmountSize.Small,
                )
            }
        }
    }
}

@Composable
private fun ParticipantAmountStatusLabel(status: ParticipantAmountStatus) {
    if (status == ParticipantAmountStatus.None) return
    val semantic = MaterialTheme.sharedLedgerColors
    val (label, color) = when (status) {
        ParticipantAmountStatus.None -> "" to Color.Transparent
        ParticipantAmountStatus.Pending -> "待处理" to semantic.warning
        ParticipantAmountStatus.Paid -> "已支付" to semantic.success
        ParticipantAmountStatus.Returned -> "已返还" to MaterialTheme.colorScheme.primary
        ParticipantAmountStatus.Disputed -> "有争议" to semantic.disputed
    }
    Text(text = label, style = SharedLedgerTextStyles.Label, color = color)
}

@Composable
fun SegmentedControl(
    options: List<String>,
    selectedIndex: Int,
    onSelected: (Int) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    require(options.isNotEmpty()) { "SegmentedControl 至少需要一个选项" }
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Row(modifier = Modifier.padding(SharedLedgerSpacing.XSmall)) {
            options.forEachIndexed { index, label ->
                Segment(
                    label = label,
                    selected = index == selectedIndex,
                    enabled = enabled,
                    onClick = { onSelected(index) },
                )
            }
        }
    }
}

@Composable
private fun RowScope.Segment(
    label: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .weight(1f)
            .clickable(enabled = enabled, onClick = onClick),
        shape = SharedLedgerRadius.Medium,
        color = if (selected) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            Color.Transparent
        },
        contentColor = if (selected) {
            MaterialTheme.colorScheme.onPrimaryContainer
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
    ) {
        Box(
            modifier = Modifier.padding(
                horizontal = SharedLedgerSpacing.Medium,
                vertical = SharedLedgerSpacing.MediumSmall,
            ),
            contentAlignment = Alignment.Center,
        ) {
            Text(text = label, style = SharedLedgerTextStyles.BodySecondary)
        }
    }
}
