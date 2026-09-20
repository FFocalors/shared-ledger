package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerCtaBottomBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerNumericKeypad
import com.ffocalors.sharedledger.ui.components.NumericKeypadState
import com.ffocalors.sharedledger.ui.components.numericKeypadTarget
import com.ffocalors.sharedledger.ui.components.SharedLedgerFluidCurrencyPicker
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLow
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import com.ffocalors.sharedledger.ui.transfer.TransferCandidateUi
import com.ffocalors.sharedledger.ui.transfer.TransferUiState
import com.ffocalors.sharedledger.data.transfer.SettlementCandidateKind
import com.ffocalors.sharedledger.data.transfer.SettlementCurrencyOption
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
    val fromParticipantId: String,
    val fromParticipantName: String,
    val toParticipantId: String,
    val toParticipantName: String,
    val kind: SettlementCandidateKind,
    val onBehalfOptions: List<SettlementParticipant> = emptyList(),
    val currencyOptions: List<SettlementCurrencyOption> = emptyList(),
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
    val currency: String = "",
    val requestId: String? = null,
    /** Optional persisted occurrence time used when a caller restores a draft. */
    val occurredAt: String? = null,
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
    var selectedCurrency by rememberSaveable(mode) { mutableStateOf(state.baseCurrency) }
    var selectedOnBehalfId by rememberSaveable(mode) { mutableStateOf<String?>(null) }
    var candidateScope by rememberSaveable(mode) { mutableStateOf(TransferCandidateScope.PERSONAL) }
    val keypad = remember { NumericKeypadState() }
    val focusManager = LocalFocusManager.current
    val activeCandidates = when (candidateScope) {
        TransferCandidateScope.PERSONAL -> state.candidates
        TransferCandidateScope.ON_BEHALF -> state.onBehalfCandidates
    }
    val participants = activeCandidates.map { candidate ->
        TransferParticipant(
            candidateKey = candidate.candidateKey,
            participantId = candidate.participantId,
            participant = ParticipantUiModel(
                candidate.participantName,
                if (candidate.claimedUserId != null) AvatarBackground.Bound(candidate.avatarStyle, candidate.claimedUserId)
                else AvatarBackground.Unbound(candidate.participantId),
            ),
            amount = candidate.amount,
            fromParticipantId = candidate.fromParticipantId,
            fromParticipantName = candidate.fromParticipantName,
            toParticipantId = candidate.toParticipantId,
            toParticipantName = candidate.toParticipantName,
            kind = candidate.kind,
            onBehalfOptions = candidate.onBehalfOptions,
            currencyOptions = candidate.currencyOptions,
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
    LaunchedEffect(mode, candidateScope, activeCandidates, state.pendingRequest?.requestId) {
        val pending = state.pendingRequest
        val pendingIndex = pending?.let { request ->
            participants.indexOfFirst { participant ->
                participant.kind == (if (request.onBehalfOfParticipantId == null) {
                    SettlementCandidateKind.PERSONAL
                } else {
                    SettlementCandidateKind.ON_BEHALF
                }) && participant.fromParticipantId == request.fromParticipantId &&
                    participant.toParticipantId == request.toParticipantId
            }
        }?.takeIf { it >= 0 }
        val targetIndex = pendingIndex
            ?: selectedIndex.coerceIn(0, (participants.size - 1).coerceAtLeast(0))
        selectedIndex = targetIndex
        val participant = participants.getOrNull(targetIndex)
        val pendingOption = pending?.takeIf {
            participant != null &&
                participant.fromParticipantId == it.fromParticipantId &&
                participant.toParticipantId == it.toParticipantId
        }?.let { request ->
            participant?.currencyOptions?.firstOrNull { option ->
                option.normalizedCurrencyCode == request.currency
            }
        }
        val option = participant?.let {
            defaultTransferCurrencyOption(
                currencyOptions = it.currencyOptions,
                baseCurrency = state.baseCurrency,
                multiCurrencyEnabled = state.multiCurrencyEnabled,
            )
        }
        val pendingMatchesParticipant = pendingIndex == targetIndex && participant != null &&
            participant.fromParticipantId == pending?.fromParticipantId &&
            participant.toParticipantId == pending?.toParticipantId
        selectedCurrency = pendingOption?.normalizedCurrencyCode
            ?: option?.normalizedCurrencyCode
            ?: state.baseCurrency
        amountText = if (pendingOption != null && pending != null) {
            pending.amount
        } else {
            option?.amount?.toPlainString() ?: participant?.amount?.toPlainString().orEmpty()
        }
        selectedOnBehalfId = pending?.takeIf { pendingMatchesParticipant }?.onBehalfOfParticipantId
            ?: participant?.onBehalfOptions?.firstOrNull()?.participantId
    }
    LaunchedEffect(selected?.candidateKey, selected?.onBehalfOptions, state.pendingRequest?.requestId) {
        if (selected?.kind == SettlementCandidateKind.ON_BEHALF && selected.onBehalfOptions.isNotEmpty()) {
            selectedOnBehalfId = state.pendingRequest?.onBehalfOfParticipantId
                ?.takeIf { candidateId -> selected.onBehalfOptions.any { it.participantId == candidateId } }
                ?: selected.onBehalfOptions.first().participantId
        }
    }
    val isTransfer = mode == TransferMode.TRANSFER
    val title = if (isTransfer) "转账" else "收款"
    val pendingMatchesSelected = state.pendingRequest?.let { request ->
        selected != null &&
            selected.fromParticipantId == request.fromParticipantId &&
            selected.toParticipantId == request.toParticipantId
    } == true
    val selectedCurrencyOption = selected?.currencyOptions
        ?.firstOrNull {
            (state.multiCurrencyEnabled || pendingMatchesSelected) &&
                it.normalizedCurrencyCode == selectedCurrency
        }
        ?: selected?.currencyOptions?.firstOrNull { it.normalizedCurrencyCode == state.baseCurrency }
        ?: selected?.let { SettlementCurrencyOption(state.baseCurrency, it.amount) }
    val selectedAmountCap = selectedCurrencyOption?.amount ?: BigDecimal.ZERO
    val isAmountValid = selected != null && isValidTransferAmount(amountText, selectedAmountCap)
    val isFormVisible = !state.isLoading && state.errorMessage == null && state.emptyMessage == null
    val hazeState = rememberSharedLedgerHazeState()

    Box(modifier = modifier.fillMaxSize()) {
    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = title,
                showBackButton = onBack != null,
                onBackClick = onBack,
                containerColor = MaterialTheme.colorScheme.background,
                hazeState = hazeState,
            )
        },
        bottomBar = {
            if (isFormVisible && selected != null && onConfirm != null) {
                SharedLedgerCtaBottomBar(hazeState = hazeState) {
                    SharedLedgerButton(
                        text = if (selected.kind == SettlementCandidateKind.ON_BEHALF) {
                            "确认代记已付款"
                        } else if (isTransfer) {
                            "确认已转账"
                        } else {
                            "确认已收款"
                        },
                        onClick = {
                            onConfirm(
                                TransferDraft(
                                    activityId = activityId,
                                    ledgerUnitId = ledgerUnitId,
                                    mode = mode,
                                    participantId = selected.participantId,
                                    amount = amountText,
                                    onBehalfOfParticipantId = selectedOnBehalfId,
                                    candidateKey = selected.candidateKey,
                                    currency = selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency,
                                ),
                            )
                        },
                        enabled = isAmountValid && !state.isSubmitting,
                        loading = state.isSubmitting,
                        loadingText = "提交中…",
                        tone = if (isTransfer) SharedLedgerButtonTone.SoftPrimary else SharedLedgerButtonTone.WarmSecondary,
                        icon = Icons.Rounded.ArrowForward,
                    )
                }
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
            when {
                state.isLoading -> LoadingState(
                    modifier = Modifier.padding(innerPadding),
                    message = "正在加载真实债务…",
                )
                state.errorMessage != null -> ErrorState(
                    message = state.errorMessage,
                    modifier = Modifier.padding(innerPadding),
                    onRetry = onRetry,
                )
                state.emptyMessage != null -> EmptyState(
                    title = state.emptyMessage,
                    modifier = Modifier.padding(innerPadding),
                    actionLabel = "刷新",
                    onAction = onRetry,
                )
                else -> Column(
                    modifier = Modifier
                        .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                        .fillMaxSize()
                        .sharedLedgerHazeSource(hazeState)
                        .verticalScroll(rememberScrollState())
                        .padding(
                            start = SharedLedgerDimens.PageHorizontalPadding,
                            top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                            end = SharedLedgerDimens.PageHorizontalPadding,
                            bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Medium,
                        ),
                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Large),
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
                                val option = defaultTransferCurrencyOption(
                                    currencyOptions = participants[index].currencyOptions,
                                    baseCurrency = state.baseCurrency,
                                    multiCurrencyEnabled = state.multiCurrencyEnabled,
                                )
                                selectedCurrency = option?.normalizedCurrencyCode ?: state.baseCurrency
                                amountText = option?.amount?.toPlainString()
                                    ?: participants[index].amount.toPlainString()
                                selectedOnBehalfId = participants[index].onBehalfOptions.firstOrNull()?.participantId
                            },
                        )

                        TransferAmountCard(
                            mode = mode,
                            selected = selected,
                            amountText = amountText,
                            isAmountValid = isAmountValid,
                            currencyCode = selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency,
                            baseCurrency = state.baseCurrency,
                            multiCurrencyEnabled = state.multiCurrencyEnabled,
                            currencyOptions = selected.currencyOptions,
                            selectedCurrency = selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency,
                            maxAmount = selectedAmountCap,
                            onCurrencyChange = { currency ->
                                selectedCurrency = currency
                                amountText = selected.currencyOptions.firstOrNull {
                                    it.normalizedCurrencyCode == currency
                                }?.amount?.toPlainString().orEmpty()
                            },
                            canActOnBehalf = state.canActOnBehalf,
                            currentParticipantId = state.currentParticipantId,
                            onBehalfOptions = selected.onBehalfOptions,
                            selectedOnBehalfId = selectedOnBehalfId,
                            onBehalfOfParticipantIdChanged = { selectedOnBehalfId = it },
                            onAmountChange = {
                                amountText = sanitizeTransferAmount(
                                    it,
                                    fractionDigits = if ((selectedCurrencyOption?.normalizedCurrencyCode
                                            ?: state.baseCurrency) == state.baseCurrency) 1 else 2,
                                )
                            },
                            keypad = keypad,
                        )
                    }
                }
            }
        }
    }
        SharedLedgerNumericKeypad(
            state = keypad,
            onDismiss = { focusManager.clearFocus() },
            modifier = Modifier.matchParentSize(),
        )
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
                onClick = { onSelected(scope) },
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = SharedLedgerDimens.TopBarActionSize),
                shape = SharedLedgerRadius.Full,
                color = if (selected == scope) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.MediumSmall),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = if (scope == TransferCandidateScope.PERSONAL) "我的结算" else "代记结算",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurface,
                        textAlign = TextAlign.Center,
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
                key = { _, item -> item.candidateKey },
            ) { index, item ->
                val selected = index == selectedIndex
                Surface(
                    onClick = { onSelected(index) },
                    modifier = Modifier
                        .width(cardWidth),
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
                    shadowElevation = if (selected) SharedLedgerElevation.Card else SharedLedgerElevation.Flat,
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
                                background = item.participant.avatarBackground,
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
    baseCurrency: String,
    multiCurrencyEnabled: Boolean,
    currencyOptions: List<SettlementCurrencyOption>,
    selectedCurrency: String,
    maxAmount: BigDecimal,
    onCurrencyChange: (String) -> Unit,
    canActOnBehalf: Boolean,
    currentParticipantId: String?,
    onBehalfOptions: List<SettlementParticipant>,
    selectedOnBehalfId: String?,
    onBehalfOfParticipantIdChanged: (String?) -> Unit,
    onAmountChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    keypad: NumericKeypadState? = null,
) {
    val isTransfer = mode == TransferMode.TRANSFER
    var showCurrencyMenu by remember { mutableStateOf(false) }
    val visibleCurrencyOptions = visibleTransferCurrencyOptions(
        multiCurrencyEnabled = multiCurrencyEnabled,
        currencyOptions = currencyOptions,
        baseCurrency = baseCurrency,
    ).ifEmpty {
        listOf(SettlementCurrencyOption(baseCurrency, maxAmount))
    }
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
            if (shouldShowTransferCurrencyPicker(multiCurrencyEnabled)) {
                Text(
                    text = "结算币种",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                SharedLedgerFluidCurrencyPicker(
                    expanded = showCurrencyMenu,
                    onExpandedChange = { showCurrencyMenu = it },
                    currencyCodes = visibleCurrencyOptions.map { it.normalizedCurrencyCode },
                    selectedCode = selectedCurrency,
                    onSelected = onCurrencyChange,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            SharedLedgerTextField(
                value = amountText,
                onValueChange = onAmountChange,
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (keypad != null) {
                            Modifier.numericKeypadTarget(keypad, { amountText }, onAmountChange)
                        } else {
                            Modifier
                        },
                    ),
                label = "金额（$currencyCode）",
                placeholder = "0.0",
                readOnly = keypad != null,
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
                    "当前债务 ${MoneyFormatter.format(maxAmount, currencyCode, if (currencyCode == baseCurrency) 1 else 2)}"
                } else if (isTransfer) {
                    "最多可转 ${MoneyFormatter.format(maxAmount, currencyCode, if (currencyCode == baseCurrency) 1 else 2)}"
                } else {
                    "当前欠款 ${MoneyFormatter.format(maxAmount, currencyCode, if (currencyCode == baseCurrency) 1 else 2)}"
                },
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.outline,
            )
            if (!isAmountValid && amountText.isNotBlank()) {
                Text(
                    text = if (amountText.toBigDecimalOrNull()?.let { it > maxAmount } == true) {
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
                        onClick = { onSelected(null) },
                        modifier = Modifier.heightIn(min = SharedLedgerDimens.TopBarActionSize),
                        shape = SharedLedgerRadius.Full,
                        color = if (selectedId == null) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                    ) {
                        Text("本人", modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.MediumSmall), style = SharedLedgerTextStyles.Label)
                    }
                }
            }
            itemsIndexed(options) { _, option ->
                Surface(
                    onClick = { onSelected(option.participantId) },
                    modifier = Modifier.heightIn(min = SharedLedgerDimens.TopBarActionSize),
                    shape = SharedLedgerRadius.Full,
                    color = if (selectedId == option.participantId) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                    border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Text(option.participantName, modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.MediumSmall), style = SharedLedgerTextStyles.Label)
                }
            }
        }
    }
}

internal fun sanitizeTransferAmount(value: String, fractionDigits: Int = 1): String {
    val filtered = value.filter { it.isDigit() || it == '.' }
    val dotIndex = filtered.indexOf('.')
    return if (dotIndex < 0) {
        filtered
    } else {
        filtered.substring(0, dotIndex + 1) + filtered.substring(dotIndex + 1).take(fractionDigits.coerceAtLeast(0))
    }
}

/**
 * The settlement options RPC is the source of truth for currencies that have a
 * live debt. Keep the base option supplied by that response, but never widen
 * the list with the exchange-rate catalogue used by expense entry.
 */
internal fun visibleTransferCurrencyOptions(
    multiCurrencyEnabled: Boolean,
    currencyOptions: List<SettlementCurrencyOption>,
    baseCurrency: String,
): List<SettlementCurrencyOption> {
    val base = baseCurrency.trim().uppercase()
    val distinct = currencyOptions
        .filter { it.normalizedCurrencyCode.isNotBlank() && it.amount > BigDecimal.ZERO }
        .distinctBy { it.normalizedCurrencyCode }
    return if (multiCurrencyEnabled) {
        distinct
    } else {
        distinct.filter { it.normalizedCurrencyCode == base }
    }
}

internal fun defaultTransferCurrencyOption(
    currencyOptions: List<SettlementCurrencyOption>,
    baseCurrency: String,
    multiCurrencyEnabled: Boolean,
): SettlementCurrencyOption? {
    val base = baseCurrency.trim().uppercase()
    return currencyOptions.firstOrNull { it.normalizedCurrencyCode == base }
        ?: currencyOptions.firstOrNull().takeIf { multiCurrencyEnabled }
}

internal fun shouldShowTransferCurrencyPicker(multiCurrencyEnabled: Boolean): Boolean = multiCurrencyEnabled

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
