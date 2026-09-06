package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
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
import androidx.compose.runtime.LaunchedEffect
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
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.demo.DemoRouteIds
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
import com.ffocalors.sharedledger.ui.transfer.TransferCandidateUi
import com.ffocalors.sharedledger.ui.transfer.TransferUiState
import java.math.BigDecimal

/** The two lightweight UI states supported by the single transfer screen. */
enum class TransferMode {
    TRANSFER,
    RECEIVE,
}

private data class TransferParticipant(
    val participantId: String,
    val participant: ParticipantUiModel,
    val amount: BigDecimal,
)

data class TransferDraft(
    val activityId: String,
    val ledgerUnitId: String?,
    val mode: TransferMode,
    val participantId: String,
    val amount: String,
)

/** Preview/test compatibility only; the runtime transfer route does not call this helper. */
data class TransferCreationResult(
    val transferId: String,
    val activityId: String,
    val ledgerUnitId: String?,
)

internal fun demoCreateTransfer(draft: TransferDraft): TransferCreationResult = TransferCreationResult(
    transferId = DemoRouteIds.transfer(
        activityId = draft.activityId,
        ledgerUnitId = draft.ledgerUnitId,
        mode = if (draft.mode == TransferMode.RECEIVE) "receive" else "transfer",
        participantId = draft.participantId,
    ),
    activityId = draft.activityId,
    ledgerUnitId = draft.ledgerUnitId,
)

/**
 * ledger transfer; the host decides what to do after [onConfirm].
 */
@Composable
fun TransferScreen(
    mode: TransferMode,
    activityId: String,
    ledgerUnitId: String? = null,
    state: TransferUiState = TransferUiState(),
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onRetry: () -> Unit = {},
    onConfirm: ((TransferDraft) -> Unit)? = null,
) {
    var selectedIndex by rememberSaveable(mode) { mutableIntStateOf(0) }
    var amountText by rememberSaveable(mode) { mutableStateOf("") }
    val participants = state.candidates.mapIndexed { index, candidate ->
        TransferParticipant(
            participantId = candidate.participantId,
            participant = ParticipantUiModel(
                candidate.participantName,
                if (index % 2 == 0) IconContainerSage else IconContainerOrange,
            ),
            amount = candidate.amount,
        )
    }
    LaunchedEffect(mode, state.candidates) {
        selectedIndex = selectedIndex.coerceIn(0, (participants.size - 1).coerceAtLeast(0))
        amountText = participants.getOrNull(selectedIndex)?.amount?.toPlainString().orEmpty()
    }
    val selected = participants.getOrNull(selectedIndex)
    val isTransfer = mode == TransferMode.TRANSFER
    val title = if (isTransfer) "转账" else "收款"
    val isAmountValid = selected != null && isValidTransferAmount(amountText, selected.amount)

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = title,
                showBackButton = onBack != null,
                onBackClick = onBack,
                containerColor = MaterialTheme.colorScheme.background,
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
            when {
                state.isLoading -> TransferStateMessage("正在加载真实债务…", onBack)
                state.errorMessage != null -> TransferErrorMessage(state.errorMessage, onBack, onRetry)
                state.emptyMessage != null || selected == null -> TransferEmptyMessage(state.emptyMessage ?: "当前没有可结算的债务", onBack, onRetry)
                else -> Column(
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
                        participants = participants,
                        selectedIndex = selectedIndex,
                        currencyCode = state.baseCurrency,
                        onSelected = { index ->
                            selectedIndex = index
                            amountText = participants[index].amount.toPlainString()
                        },
                    )

                    TransferAmountCard(
                        mode = mode,
                        selected = selected,
                        amountText = amountText,
                        isAmountValid = isAmountValid,
                        currencyCode = state.baseCurrency,
                        isSubmitting = state.isSubmitting,
                        onAmountChange = { amountText = sanitizeCnyAmount(it) },
                        onConfirm = onConfirm?.let { callback -> {
                            callback(
                                TransferDraft(
                                    activityId = activityId,
                                    ledgerUnitId = ledgerUnitId,
                                    mode = mode,
                                    participantId = selected.participantId,
                                    amount = amountText,
                                ),
                            )
                        } },
                    )
                }
            }
        }
    }
}

@Composable
private fun ParticipantPicker(
    participants: List<TransferParticipant>,
    selectedIndex: Int,
    currencyCode: String,
    onSelected: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        // The picker is already inside the page's horizontal padding. Its maxWidth is therefore
        // the actual available content width; do not subtract page padding a second time.
        val itemSpacing = SharedLedgerSpacing.Medium
        val twoCardWidth = (maxWidth - itemSpacing) / 2
        val cardWidth = if (participants.size >= 2) twoCardWidth else maxWidth

        LazyRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(itemSpacing),
        ) {
            itemsIndexed(
                items = participants,
                key = { _, item -> item.participant.name },
            ) { index, item ->
                val selected = index == selectedIndex
                Surface(
                    modifier = Modifier
                        .width(cardWidth)
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
                            currencyCode = currencyCode,
                            fractionDigitsOverride = 1,
                            size = AmountSize.SubActivity,
                            emphasis = AmountEmphasis.Standard,
                        )
                    }
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
    isAmountValid: Boolean,
    currencyCode: String,
    isSubmitting: Boolean,
    onAmountChange: (String) -> Unit,
    onConfirm: (() -> Unit)?,
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
                label = "金额（$currencyCode）",
                placeholder = "0.0",
                leadingIcon = {
                    Text(
                        text = currencySymbol(currencyCode),
                        style = SharedLedgerTextStyles.SummaryCurrency,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            Text(
                text = if (isTransfer) {
                    "最多可转 ${MoneyFormatter.format(selected.amount, currencyCode, 1)}"
                } else {
                    "当前欠款 ${MoneyFormatter.format(selected.amount, currencyCode, 1)}"
                },
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.outline,
            )
            if (!isAmountValid && amountText.isNotBlank()) {
                Text(
                    text = if (amountText.toBigDecimalOrNull()?.let { it > selected.amount } == true) {
                        "金额不能超过当前债务"
                    } else {
                        "请输入大于 0 的金额"
                    },
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            onConfirm?.let { callback ->
                SharedLedgerButton(
                    text = if (isTransfer) "确认已转账" else "确认已收款",
                    onClick = callback,
                    enabled = isAmountValid && !isSubmitting,
                    loading = isSubmitting,
                    loadingText = "提交中…",
                    tone = if (isTransfer) SharedLedgerButtonTone.SoftPrimary else SharedLedgerButtonTone.WarmSecondary,
                    icon = Icons.Rounded.ArrowForward,
                )
            }
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

internal fun isValidTransferAmount(value: String): Boolean =
    value.toBigDecimalOrNull()?.let { it > BigDecimal.ZERO } == true

internal fun isValidTransferAmount(value: String, maxAmount: BigDecimal): Boolean =
    value.toBigDecimalOrNull()?.let { it > BigDecimal.ZERO && it <= maxAmount } == true

private fun currencySymbol(currencyCode: String): String = when (currencyCode.uppercase()) {
    "CNY" -> "¥"
    "USD" -> "$"
    "EUR" -> "€"
    "GBP" -> "£"
    "JPY" -> "¥"
    else -> currencyCode.uppercase()
}

@Composable
private fun TransferStateMessage(message: String, onBack: (() -> Unit)?) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(SharedLedgerSpacing.XLarge),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        androidx.compose.material3.CircularProgressIndicator()
        Text(message, style = SharedLedgerTextStyles.BodySecondary)
        onBack?.let { SharedLedgerButton("返回", it, tone = SharedLedgerButtonTone.Neutral) }
    }
}

@Composable
private fun TransferErrorMessage(message: String, onBack: (() -> Unit)?, onRetry: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(SharedLedgerSpacing.XLarge),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Text(message, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.error)
        SharedLedgerButton("重试", onRetry, tone = SharedLedgerButtonTone.SoftPrimary)
        onBack?.let { SharedLedgerButton("返回", it, tone = SharedLedgerButtonTone.Neutral) }
    }
}

@Composable
private fun TransferEmptyMessage(message: String, onBack: (() -> Unit)?, onRetry: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(SharedLedgerSpacing.XLarge),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Text(message, style = SharedLedgerTextStyles.BodySecondary)
        SharedLedgerButton("刷新", onRetry, tone = SharedLedgerButtonTone.SoftPrimary)
        onBack?.let { SharedLedgerButton("返回", it, tone = SharedLedgerButtonTone.Neutral) }
    }
}

@Preview(name = "转账", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun TransferScreenPreview() {
    SharedLedgerTheme {
        TransferScreen(
            mode = TransferMode.TRANSFER,
            activityId = "preview",
            state = TransferUiState(
                isLoading = false,
                candidates = listOf(TransferCandidateUi("preview-bob", "李四", BigDecimal("300.0"))),
            ),
        )
    }
}

@Preview(name = "收款", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun ReceiveScreenPreview() {
    SharedLedgerTheme {
        TransferScreen(
            mode = TransferMode.RECEIVE,
            activityId = "preview",
            state = TransferUiState(
                isLoading = false,
                candidates = listOf(TransferCandidateUi("preview-alice", "张三", BigDecimal("120.0"))),
            ),
        )
    }
}
