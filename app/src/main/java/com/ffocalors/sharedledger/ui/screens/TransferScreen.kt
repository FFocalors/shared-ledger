package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SharedLedgerPrimaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLow
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import java.math.BigDecimal

/** The two lightweight UI states supported by the single transfer screen. */
enum class TransferMode {
    TRANSFER,
    RECEIVE,
}

private data class TransferParticipant(
    val participant: ParticipantUiModel,
    val amount: BigDecimal,
)

private val TransferParticipants = listOf(
    TransferParticipant(ParticipantUiModel("张三", IconContainerSage), BigDecimal("300.0")),
    TransferParticipant(ParticipantUiModel("李四", IconContainerOrange), BigDecimal("120.0")),
)

/**
 * Focused transfer/receive UI. It intentionally keeps all state local and does not create a
 * ledger transfer; the host decides what to do after [onConfirm].
 */
@Composable
fun TransferScreen(
    mode: TransferMode,
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onConfirm: () -> Unit = {},
) {
    var selectedIndex by rememberSaveable(mode) { mutableIntStateOf(0) }
    var amountText by rememberSaveable(mode) {
        mutableStateOf(if (mode == TransferMode.TRANSFER) "200.0" else "300.0")
    }
    val selected = TransferParticipants[selectedIndex.coerceIn(0, TransferParticipants.lastIndex)]
    val isTransfer = mode == TransferMode.TRANSFER
    val title = if (isTransfer) "转账" else "收款"

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = title,
                showBackButton = true,
                onBackClick = onBack,
                modifier = Modifier.statusBarsPadding(),
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .navigationBarsPadding()
                .imePadding()
                .padding(innerPadding),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .padding(
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        top = SharedLedgerSpacing.Medium,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = SharedLedgerSpacing.XLarge,
                    ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                Text(
                    text = if (isTransfer) "你需要付款给" else "当前欠你钱的人",
                    style = SharedLedgerTextStyles.PageTitle,
                    color = MaterialTheme.colorScheme.onBackground,
                )

                ParticipantPicker(
                    participants = TransferParticipants,
                    selectedIndex = selectedIndex,
                    onSelected = { selectedIndex = it },
                )

                TransferAmountCard(
                    mode = mode,
                    selected = selected,
                    amountText = amountText,
                    onAmountChange = { amountText = sanitizeCnyAmount(it) },
                    onConfirm = onConfirm,
                )
            }
        }
    }
}

@Composable
private fun ParticipantPicker(
    participants: List<TransferParticipant>,
    selectedIndex: Int,
    onSelected: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        participants.forEachIndexed { index, item ->
            val selected = index == selectedIndex
            Surface(
                modifier = Modifier
                    .width(160.dp)
                    .clickable { onSelected(index) },
                shape = SharedLedgerRadius.ExtraLarge,
                color = if (selected) {
                    MaterialTheme.colorScheme.primaryContainer
                } else {
                    SurfaceWarmLow
                },
                contentColor = if (selected) {
                    MaterialTheme.colorScheme.onPrimaryContainer
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
                border = BorderStroke(
                    SharedLedgerDimens.OutlineWidth,
                    if (selected) Color.Transparent else MaterialTheme.colorScheme.outlineVariant,
                ),
                shadowElevation = if (selected) SharedLedgerElevation.Card else 0.dp,
            ) {
                Column(
                    modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ParticipantAvatar(
                            name = item.participant.name,
                            backgroundColor = item.participant.backgroundColor,
                            size = SharedLedgerDimens.AvatarLarge,
                        )
                        if (selected) {
                            Icon(
                                imageVector = Icons.Rounded.CheckCircle,
                                contentDescription = "已选择${item.participant.name}",
                                modifier = Modifier.width(SharedLedgerDimens.IconMedium),
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Rounded.Person,
                                contentDescription = null,
                                modifier = Modifier.width(SharedLedgerDimens.IconMedium),
                                tint = MaterialTheme.colorScheme.outline,
                            )
                        }
                    }
                    Text(
                        text = item.participant.name,
                        style = SharedLedgerTextStyles.Body,
                        color = if (selected) {
                            MaterialTheme.colorScheme.onPrimaryContainer
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                    AmountDisplay(
                        amount = item.amount,
                        currencyCode = "CNY",
                        fractionDigitsOverride = 1,
                        size = AmountSize.SubActivity,
                        emphasis = AmountEmphasis.Standard,
                    )
                }
            }
        }
    }
}

@Composable
private fun TransferAmountCard(
    mode: TransferMode,
    selected: TransferParticipant,
    amountText: String,
    onAmountChange: (String) -> Unit,
    onConfirm: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isTransfer = mode == TransferMode.TRANSFER
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.BottomActionBar,
        color = SurfaceWarmLowest,
        shadowElevation = SharedLedgerElevation.Card,
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant,
        ),
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Text(
                text = if (isTransfer) "转给 ${selected.participant.name}" else "向 ${selected.participant.name} 收款",
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.onSurface,
            )
            SharedLedgerTextField(
                value = amountText,
                onValueChange = onAmountChange,
                modifier = Modifier.fillMaxWidth(),
                label = "金额（CNY）",
                placeholder = "0.0",
                leadingIcon = {
                    Text(
                        text = "¥",
                        style = SharedLedgerTextStyles.SummaryCurrency,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            Text(
                text = if (isTransfer) {
                    "最多可转 ${MoneyFormatter.format(selected.amount, "CNY", 1)}"
                } else {
                    "当前欠款 ${MoneyFormatter.format(selected.amount, "CNY", 1)}"
                },
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.outline,
            )
            SharedLedgerPrimaryButton(
                text = if (isTransfer) "确认已转账" else "确认已收款",
                onClick = onConfirm,
                icon = Icons.Rounded.ArrowForward,
            )
        }
    }
}

private fun sanitizeCnyAmount(value: String): String {
    val filtered = value.filter { it.isDigit() || it == '.' }
    val dotIndex = filtered.indexOf('.')
    return if (dotIndex < 0) {
        filtered
    } else {
        filtered.substring(0, dotIndex + 1) + filtered.substring(dotIndex + 1).take(1)
    }
}

@Preview(name = "转账", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun TransferScreenPreview() {
    SharedLedgerTheme {
        TransferScreen(mode = TransferMode.TRANSFER)
    }
}

@Preview(name = "收款", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun ReceiveScreenPreview() {
    SharedLedgerTheme {
        TransferScreen(mode = TransferMode.RECEIVE)
    }
}
