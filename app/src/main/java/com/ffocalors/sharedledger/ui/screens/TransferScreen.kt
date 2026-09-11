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
import com.ffocalors.sharedledger.data.transfer.SettlementCandidateKind
import com.ffocalors.sharedledger.data.transfer.SettlementParticipant
import java.math.BigDecimal

/** The two lightweight UI states supported by the single transfer screen. */
enum class TransferMode {
    TRANSFER,
    RECEIVE,
}

private data class TransferParticipant(
    val candidateKey: String,
    val participantId: String,
    val participant: ParticipantUiModel,
    val amount: BigDecimal,
    val fromParticipantName: String,
    val toParticipantName: String,
    val kind: SettlementCandidateKind,
    val onBehalfOptions: List<SettlementParticipant> = emptyList(),
)

private enum class TransferCandidateScope { PERSONAL, ON_BEHALF }

data class TransferDraft(
    val activityId: String,
    val ledgerUnitId: String?,
    val mode: TransferMode,
    val participantId: String,
    val amount: String,
    val onBehalfOfParticipantId: String? = null,
    val candidateKey: String? = null,
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
    var selectedOnBehalfId by rememberSaveable(mode) { mutableStateOf<String?>(null) }
    var candidateScope by rememberSaveable(mode) { mutableStateOf(TransferCandidateScope.PERSONAL) }
    val activeCandidates = when (candidateScope) {
        TransferCandidateScope.PERSONAL -> state.candidates
        TransferCandidateScope.ON_BEHALF -> state.onBehalfCandidates
    }
    val participants = activeCandidates.mapIndexed { index, candidate ->
        TransferParticipant(
            candidateKey = candidate.candidateKey,
            participantId = candidate.participantId,
            participant = ParticipantUiModel(
                candidate.participantName,
                if (index % 2 == 0) IconContainerSage else IconContainerOrange,
            ),
            amount = candidate.amount,
            fromParticipantName = candidate.fromParticipantName,
            toParticipantName = candidate.toParticipantName,
            kind = candidate.kind,
            onBehalfOptions = candidate.onBehalfOptions,
        )
    }
    val selected = participants.getOrNull(selectedIndex)
    LaunchedEffect(mode, state.candidates, state.onBehalfCandidates) {
        candidateScope = when {
            state.candidates.isEmpty() && state.onBehalfCandidates.isNotEmpty() -> TransferCandidateScope.ON_BEHALF
            state.currentParticipantId == null && state.canActOnBehalf -> TransferCandidateScope.ON_BEHALF
            state.onBehalfCandidates.isEmpty() -> TransferCandidateScope.PERSONAL
            else -> candidateScope
        }
    }
    LaunchedEffect(mode, candidateScope, activeCandidates) {
        selectedIndex = selectedIndex.coerceIn(0, (participants.size - 1).coerceAtLeast(0))
        amountText = participants.getOrNull(selectedIndex)?.amount?.toPlainString().orEmpty()
        selectedOnBehalfId = null
    }
    LaunchedEffect(selected?.candidateKey, selected?.onBehalfOptions) {
        if (selected?.kind == SettlementCandidateKind.ON_BEHALF && selected.onBehalfOptions.isNotEmpty()) {
            selectedOnBehalfId = selected.onBehalfOptions.first().participantId
        }
    }
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
                state.emptyMessage != null -> TransferEmptyMessage(state.emptyMessage, onBack, onRetry)
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
                    if (state.canActOnBehalf) {
                        CandidateScopePicker(
                            selected = candidateScope,
                            onSelected = { candidateScope = it },
                        )
                    }

                    Text(
                        text = when (candidateScope) {
                            TransferCandidateScope.PERSONAL -> if (isTransfer) "你需要付款给" else "当前欠你钱的人"
                            TransferCandidateScope.ON_BEHALF -> if (isTransfer) "代记他人付款" else "代记他人收款"
                        },
                        style = SharedLedgerTextStyles.PageTitle,
                        color = MaterialTheme.colorScheme.onBackground,
                    )

                    if (candidateScope == TransferCandidateScope.ON_BEHALF) {
                        Text(
                            text = "以下是他人之间的债务，请核对付款方和收款方。",
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    if (selected == null) {
                        Text(
                            text = if (candidateScope == TransferCandidateScope.PERSONAL) "当前没有个人债务" else "当前没有可代记债务",
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        ParticipantPicker(
                            participants = participants,
                            selectedIndex = selectedIndex,
                            currencyCode = state.baseCurrency,
                            onSelected = { index ->
                                selectedIndex = index
                                amountText = participants[index].amount.toPlainString()
                                selectedOnBehalfId = participants[index].onBehalfOptions.firstOrNull()?.participantId
                            },
                        )

                        TransferAmountCard(
                            mode = mode,
                            selected = selected,
                            amountText = amountText,
                            isAmountValid = isAmountValid,
                            currencyCode = state.baseCurrency,
                            isSubmitting = state.isSubmitting,
                            canActOnBehalf = state.canActOnBehalf,
                            currentParticipantId = state.currentParticipantId,
                            onBehalfOptions = selected.onBehalfOptions,
                            selectedOnBehalfId = selectedOnBehalfId,
                            onBehalfOfParticipantIdChanged = { selectedOnBehalfId = it },
                            onAmountChange = { amountText = sanitizeCnyAmount(it) },
                            onConfirm = onConfirm?.let { callback -> {
                                callback(
                                    TransferDraft(
                                        activityId = activityId,
                                        ledgerUnitId = ledgerUnitId,
                                        mode = mode,
                                        participantId = selected.participantId,
                                        amount = amountText,
                                        onBehalfOfParticipantId = selectedOnBehalfId,
                                        candidateKey = selected.candidateKey,
                                    ),
                                )
                            } },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CandidateScopePicker(
    selected: TransferCandidateScope,
    onSelected: (TransferCandidateScope) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        TransferCandidateScope.entries.forEach { scope ->
            Surface(
                modifier = Modifier.weight(1f).clickable { onSelected(scope) },
                shape = SharedLedgerRadius.Full,
                color = if (selected == scope) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
            ) {
                Text(
                    text = if (scope == TransferCandidateScope.PERSONAL) "我的结算" else "代记结算",
                    modifier = Modifier.padding(SharedLedgerSpacing.Small),
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurface,
                )
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
                key = { _, item -> item.candidateKey },
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
                            text = if (item.kind == SettlementCandidateKind.ON_BEHALF) {
                                "${item.fromParticipantName} → ${item.toParticipantName}"
                            } else {
                                item.participant.name
                            },
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
    canActOnBehalf: Boolean,
    currentParticipantId: String?,
    onBehalfOptions: List<SettlementParticipant>,
    selectedOnBehalfId: String?,
    onBehalfOfParticipantIdChanged: (String?) -> Unit,
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
                text = if (selected.kind == SettlementCandidateKind.ON_BEHALF) {
                    "${selected.fromParticipantName} 向 ${selected.toParticipantName} 付款"
                } else if (isTransfer) {
                    "转给 ${selected.participant.name}"
                } else {
                    "向 ${selected.participant.name} 收款"
                },
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
                text = if (selected.kind == SettlementCandidateKind.ON_BEHALF) {
                    "当前债务 ${MoneyFormatter.format(selected.amount, currencyCode, 1)}"
                } else if (isTransfer) {
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
            if (canActOnBehalf && onBehalfOptions.isNotEmpty()) {
                OnBehalfPicker(
                    options = onBehalfOptions,
                    currentParticipantId = currentParticipantId.takeIf { selected.kind == SettlementCandidateKind.PERSONAL },
                    selectedId = selectedOnBehalfId,
                    onSelected = onBehalfOfParticipantIdChanged,
                )
            }
            onConfirm?.let { callback ->
                SharedLedgerButton(
                    text = if (selected.kind == SettlementCandidateKind.ON_BEHALF) {
                        "确认代记已付款"
                    } else if (isTransfer) {
                        "确认已转账"
                    } else {
                        "确认已收款"
                    },
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

@Composable
private fun OnBehalfPicker(
    options: List<SettlementParticipant>,
    currentParticipantId: String?,
    selectedId: String?,
    onSelected: (String?) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        Text(
            text = if (currentParticipantId == null) "代记参与人（必选）" else "代记参与人（可选）",
            style = SharedLedgerTextStyles.Label,
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            if (currentParticipantId != null) {
                item(key = "self") {
                    Surface(
                        modifier = Modifier.clickable { onSelected(null) },
                        shape = SharedLedgerRadius.Full,
                        color = if (selectedId == null) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                    ) {
                        Text("本人", modifier = Modifier.padding(SharedLedgerSpacing.Small), style = SharedLedgerTextStyles.Label)
                    }
                }
            }
            itemsIndexed(options) { _, option ->
                Surface(
                    modifier = Modifier.clickable { onSelected(option.participantId) },
                    shape = SharedLedgerRadius.Full,
                    color = if (selectedId == option.participantId) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                    border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Text(option.participantName, modifier = Modifier.padding(SharedLedgerSpacing.Small), style = SharedLedgerTextStyles.Label)
                }
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
                candidates = listOf(
                    TransferCandidateUi(
                        participantId = "preview-bob",
                        participantName = "李四",
                        amount = BigDecimal("300.0"),
                        fromParticipantId = "preview-me",
                        fromParticipantName = "我",
                        toParticipantId = "preview-bob",
                        toParticipantName = "李四",
                    ),
                ),
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
                candidates = listOf(
                    TransferCandidateUi(
                        participantId = "preview-alice",
                        participantName = "张三",
                        amount = BigDecimal("120.0"),
                        fromParticipantId = "preview-alice",
                        fromParticipantName = "张三",
                        toParticipantId = "preview-me",
                        toParticipantName = "我",
                    ),
                ),
            ),
        )
    }
}
