package com.ffocalors.sharedledger.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Clear
import androidx.compose.material.icons.rounded.FlashOn
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Paid
import androidx.compose.material.icons.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material.icons.rounded.Sync
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.data.transfer.SettlementAllocationMode
import com.ffocalors.sharedledger.data.transfer.SettlementCandidateKind
import com.ffocalors.sharedledger.data.transfer.SettlementCurrencyOption
import com.ffocalors.sharedledger.data.transfer.SettlementExpenseOption
import com.ffocalors.sharedledger.data.transfer.SettlementParticipant
import com.ffocalors.sharedledger.data.transfer.SettlementPreviewLine
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.NumericKeypadState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SegmentedControl
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.sharedLedgerButtonPaletteFor
import com.ffocalors.sharedledger.ui.components.SharedLedgerCtaBottomBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerFluidCurrencyPicker
import com.ffocalors.sharedledger.ui.components.SharedLedgerNumericKeypad
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.numericKeypadTarget
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.ComponentSizes
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SageGreenContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLow
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.WarmOrange
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors
import com.ffocalors.sharedledger.ui.transfer.TransferCandidateUi
import com.ffocalors.sharedledger.ui.transfer.TransferUiState
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
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
    val expenseOptions: List<SettlementExpenseOption> = emptyList(),
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
    val allocationMode: SettlementAllocationMode = SettlementAllocationMode.FIFO,
    val targetExpenseIds: List<String> = emptyList(),
    val expectedFinancialVersion: Long? = null,
)

/**
 * Modernized ledger transfer / settlement screen.
 * Follows Material 3 and SharedLedger design language with clean information architecture.
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
    onPreview: ((TransferDraft) -> Unit)? = null,
    onConfirm: ((TransferDraft) -> Unit)? = null,
) {
    var selectedIndex by rememberSaveable(mode) { mutableIntStateOf(0) }
    var amountText by rememberSaveable(mode) { mutableStateOf("") }
    var selectedCurrency by rememberSaveable(mode) { mutableStateOf(state.baseCurrency) }
    var selectedOnBehalfId by rememberSaveable(mode) { mutableStateOf<String?>(null) }
    var candidateScope by rememberSaveable(mode) { mutableStateOf(TransferCandidateScope.PERSONAL) }
    var allocationMode by rememberSaveable(mode) { mutableStateOf(SettlementAllocationMode.FIFO) }
    var selectedExpenseIds by remember(mode) { mutableStateOf<Set<String>>(emptySet()) }
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
                if (candidate.claimedUserId != null) {
                    AvatarBackground.Bound(candidate.avatarStyle, candidate.claimedUserId)
                } else {
                    AvatarBackground.Unbound(candidate.participantId)
                },
            ),
            amount = candidate.amount,
            fromParticipantId = candidate.fromParticipantId,
            fromParticipantName = candidate.fromParticipantName,
            toParticipantId = candidate.toParticipantId,
            toParticipantName = candidate.toParticipantName,
            kind = candidate.kind,
            onBehalfOptions = candidate.onBehalfOptions,
            currencyOptions = candidate.currencyOptions,
            expenseOptions = candidate.expenseOptions,
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
        allocationMode = pending?.allocationMode ?: SettlementAllocationMode.FIFO
        selectedExpenseIds = pending?.targetExpenseIds?.toSet().orEmpty()
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

    LaunchedEffect(selected?.candidateKey, selectedCurrency) {
        val available = selected?.expenseOptions.orEmpty()
            .filter { selectedCurrency == state.baseCurrency || it.normalizedCurrencyCode == selectedCurrency }
            .map { it.expenseId }
            .toSet()
        selectedExpenseIds = selectedExpenseIds intersect available
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

    val eligibleExpenses = selected?.expenseOptions.orEmpty().filter { expense ->
        selectedCurrency == state.baseCurrency || expense.normalizedCurrencyCode == selectedCurrency
    }

    val selectedExpenseCap = eligibleExpenses
        .filter { it.expenseId in selectedExpenseIds }
        .sumOf { if (selectedCurrency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount }

    val effectiveAmountCap = if (allocationMode == SettlementAllocationMode.TARGETED) {
        minOf(selectedExpenseCap, selectedAmountCap)
    } else {
        selectedAmountCap
    }

    val isAmountValid = selected != null &&
        (allocationMode == SettlementAllocationMode.FIFO || selectedExpenseIds.isNotEmpty()) &&
        isValidTransferAmount(amountText, effectiveAmountCap)

    val selectedExpectedVersion = selected?.expenseOptions.orEmpty()
        .filter { it.expenseId in selectedExpenseIds }
        .mapNotNull { it.financialVersion }
        .maxOrNull()
        ?: selectedCurrencyOption?.financialVersion

    val previewMatches = state.preview?.let { preview ->
        preview.activityId == activityId &&
            preview.fromParticipantId == selected?.fromParticipantId &&
            preview.toParticipantId == selected?.toParticipantId &&
            preview.allocationMode == allocationMode &&
            preview.currency == selectedCurrency &&
            preview.requestedAmount.compareTo(amountText.toBigDecimalOrNull() ?: BigDecimal.ZERO) == 0 &&
            preview.targetExpenseIds.toSet() == selectedExpenseIds &&
            (selectedExpectedVersion == null || preview.financialVersion == selectedExpectedVersion)
    } == true

    LaunchedEffect(selected?.candidateKey, selectedCurrency, amountText, allocationMode, selectedExpenseIds, selectedExpectedVersion) {
        if (selected != null && isAmountValid && onPreview != null) {
            onPreview(
                TransferDraft(
                    activityId = activityId,
                    ledgerUnitId = ledgerUnitId,
                    mode = mode,
                    participantId = selected.participantId,
                    amount = amountText,
                    onBehalfOfParticipantId = selectedOnBehalfId,
                    candidateKey = selected.candidateKey,
                    currency = selectedCurrency,
                    allocationMode = allocationMode,
                    targetExpenseIds = selectedExpenseIds.toList(),
                    expectedFinancialVersion = selectedExpectedVersion,
                ),
            )
        }
    }

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
                        val formattedAmount = amountText.toBigDecimalOrNull()?.let {
                            MoneyFormatter.format(
                                it,
                                selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency,
                                if ((selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency) == "CNY") 1 else 2,
                            )
                        }.orEmpty()

                        val buttonText = buildString {
                            when {
                                selected.kind == SettlementCandidateKind.ON_BEHALF -> append("确认代记已付款")
                                isTransfer -> append("确认已转账")
                                else -> append("确认已收款")
                            }
                            if (formattedAmount.isNotBlank() && isAmountValid) {
                                append(" ")
                                append(formattedAmount)
                            }
                        }

                        // 视觉可用条件：金额输入合法、无预览错误，且未在最终写入中
                        val isInputValid = isAmountValid && state.previewErrorMessage == null && !state.isSubmitting
                        // 实际可提交条件：视觉合法且后端试算完成匹配
                        val isActuallyReady = isInputValid && previewMatches && !state.isPreviewing

                        var isAwaitingPreviewToConfirm by remember { mutableStateOf(false) }

                        // 当用户在 preview 还在返回途中点击了按钮时，一旦 preview 达成匹配，立即自动触发提交
                        LaunchedEffect(previewMatches, isAwaitingPreviewToConfirm, state.isPreviewing, state.previewErrorMessage) {
                            if (isAwaitingPreviewToConfirm) {
                                if (state.previewErrorMessage != null) {
                                    isAwaitingPreviewToConfirm = false
                                } else if (previewMatches && !state.isPreviewing && !state.isSubmitting) {
                                    isAwaitingPreviewToConfirm = false
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
                                            allocationMode = allocationMode,
                                            targetExpenseIds = selectedExpenseIds.toList(),
                                            expectedFinancialVersion = selectedExpectedVersion,
                                        ),
                                    )
                                }
                            }
                        }

                        val resolvedTone = if (isTransfer) SharedLedgerButtonTone.SoftPrimary else SharedLedgerButtonTone.WarmSecondary
                        val palette = sharedLedgerButtonPaletteFor(resolvedTone)

                        // 按钮颜色平滑过渡动画：杜绝在黄和灰之间生硬硬闪！
                        val targetContainerColor = if (isInputValid) palette.containerColor else MaterialTheme.colorScheme.surfaceVariant
                        val targetContentColor = if (isInputValid) palette.contentColor else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)

                        val animatedContainerColor by animateColorAsState(
                            targetValue = targetContainerColor,
                            animationSpec = tween(durationMillis = 200),
                            label = "buttonContainerColor",
                        )
                        val animatedContentColor by animateColorAsState(
                            targetValue = targetContentColor,
                            animationSpec = tween(durationMillis = 200),
                            label = "buttonContentColor",
                        )

                        val isButtonLoading = state.isSubmitting || isAwaitingPreviewToConfirm
                        val loadingMessage = if (state.isSubmitting) "提交中…" else "核算中…"

                        Surface(
                            onClick = {
                                if (!isInputValid || state.isSubmitting) return@Surface
                                if (isActuallyReady) {
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
                                            allocationMode = allocationMode,
                                            targetExpenseIds = selectedExpenseIds.toList(),
                                            expectedFinancialVersion = selectedExpectedVersion,
                                        ),
                                    )
                                } else {
                                    isAwaitingPreviewToConfirm = true
                                }
                            },
                            enabled = isInputValid && !isButtonLoading,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(SharedLedgerDimens.ButtonHeight),
                            shape = SharedLedgerRadius.Full,
                            color = animatedContainerColor,
                            contentColor = animatedContentColor,
                        ) {
                            Box(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .padding(horizontal = SharedLedgerSpacing.Large),
                                contentAlignment = Alignment.Center,
                            ) {
                                if (isButtonLoading) {
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                                    ) {
                                        CircularProgressIndicator(
                                            modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                                            color = animatedContentColor,
                                            strokeWidth = 2.dp,
                                        )
                                        Text(
                                            text = loadingMessage,
                                            style = SharedLedgerTextStyles.Button,
                                            color = animatedContentColor,
                                        )
                                    }
                                } else {
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                                    ) {
                                        Icon(
                                            imageVector = Icons.AutoMirrored.Rounded.ArrowForward,
                                            contentDescription = null,
                                            tint = animatedContentColor,
                                            modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                                        )
                                        Text(
                                            text = buttonText,
                                            style = SharedLedgerTextStyles.Button,
                                            color = animatedContentColor,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            },
        ) { innerPadding ->
            Box(
                modifier = Modifier.fillMaxSize(),
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
                                top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Small,
                                end = SharedLedgerDimens.PageHorizontalPadding,
                                bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Large,
                            ),
                        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumLarge),
                    ) {
                        // 1. 范围选择：仅在允许代记时出现，采用紧凑的 SegmentedControl
                        if (state.canActOnBehalf) {
                            SegmentedControl(
                                options = listOf("我的结算", "代记结算"),
                                selectedIndex = if (candidateScope == TransferCandidateScope.PERSONAL) 0 else 1,
                                onSelected = { index ->
                                    candidateScope = if (index == 0) TransferCandidateScope.PERSONAL else TransferCandidateScope.ON_BEHALF
                                    selectedExpenseIds = emptySet()
                                },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }

                        if (selected == null) {
                            Card(
                                modifier = Modifier.fillMaxWidth(),
                                shape = SharedLedgerRadius.Large,
                                colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
                                border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                            ) {
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(SharedLedgerSpacing.XLarge),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Text(
                                        text = if (candidateScope == TransferCandidateScope.PERSONAL) {
                                            "当前暂无个人未结账目"
                                        } else {
                                            "当前暂无可代记账目"
                                        },
                                        style = SharedLedgerTextStyles.BodySecondary,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        } else {
                            // 2. 交易对象与方向卡片
                            CounterpartySelectionSection(
                                participants = participants,
                                selectedIndex = selectedIndex,
                                selected = selected,
                                isTransfer = isTransfer,
                                candidateScope = candidateScope,
                                currencyCode = state.baseCurrency,
                                onSelectIndex = { index ->
                                    selectedIndex = index
                                    val option = defaultTransferCurrencyOption(
                                        currencyOptions = participants[index].currencyOptions,
                                        baseCurrency = state.baseCurrency,
                                        multiCurrencyEnabled = state.multiCurrencyEnabled,
                                    )
                                    val newCurrency = option?.normalizedCurrencyCode ?: state.baseCurrency
                                    selectedCurrency = newCurrency
                                    val newAmountCap = option?.amount ?: participants[index].amount
                                    if (allocationMode == SettlementAllocationMode.TARGETED) {
                                        val newEligible = participants[index].expenseOptions.filter {
                                            newCurrency == state.baseCurrency || it.normalizedCurrencyCode == newCurrency
                                        }
                                        val allIds = newEligible.map { it.expenseId }.toSet()
                                        selectedExpenseIds = allIds
                                        val expenseCap = newEligible.filter { it.expenseId in allIds }
                                            .sumOf { if (newCurrency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount }
                                        amountText = minOf(expenseCap, newAmountCap).toPlainString()
                                    } else {
                                        amountText = newAmountCap.toPlainString()
                                        selectedExpenseIds = emptySet()
                                    }
                                    selectedOnBehalfId = participants[index].onBehalfOptions.firstOrNull()?.participantId
                                },
                            )

                            // 3. 核心金额英雄输入卡片
                            TransferAmountHeroCard(
                                mode = mode,
                                selected = selected,
                                amountText = amountText,
                                isAmountValid = isAmountValid,
                                currencyCode = selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency,
                                baseCurrency = state.baseCurrency,
                                multiCurrencyEnabled = state.multiCurrencyEnabled,
                                currencyOptions = selected.currencyOptions,
                                selectedCurrency = selectedCurrencyOption?.normalizedCurrencyCode ?: state.baseCurrency,
                                totalDebtAmount = selectedAmountCap,
                                maxAmount = effectiveAmountCap,
                                onCurrencyChange = { currency ->
                                    selectedCurrency = currency
                                    val newOption = selected.currencyOptions.firstOrNull {
                                        it.normalizedCurrencyCode == currency
                                    }
                                    val newAmountCap = newOption?.amount ?: selected.amount
                                    if (allocationMode == SettlementAllocationMode.TARGETED) {
                                        val newEligible = selected.expenseOptions.filter {
                                            currency == state.baseCurrency || it.normalizedCurrencyCode == currency
                                        }
                                        val allIds = newEligible.map { it.expenseId }.toSet()
                                        selectedExpenseIds = allIds
                                        val expenseCap = newEligible.filter { it.expenseId in allIds }
                                            .sumOf { if (currency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount }
                                        amountText = minOf(expenseCap, newAmountCap).toPlainString()
                                    } else {
                                        selectedExpenseIds = emptySet()
                                        amountText = newAmountCap.toPlainString()
                                    }
                                },
                                onAmountChange = {
                                    amountText = sanitizeTransferAmount(
                                        it,
                                        fractionDigits = if ((selectedCurrencyOption?.normalizedCurrencyCode
                                                ?: state.baseCurrency) == state.baseCurrency) 1 else 2,
                                    )
                                },
                                onFillMax = {
                                    if (allocationMode == SettlementAllocationMode.TARGETED) {
                                        val allIds = eligibleExpenses.map { it.expenseId }.toSet()
                                        selectedExpenseIds = allIds
                                        val expenseCap = eligibleExpenses.filter { it.expenseId in allIds }
                                            .sumOf { if (selectedCurrency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount }
                                        amountText = minOf(expenseCap, selectedAmountCap).toPlainString()
                                    } else {
                                        amountText = selectedAmountCap.toPlainString()
                                    }
                                },
                                keypad = keypad,
                            )

                            // 4. 抵扣方式与账单明细核销
                            AllocationStrategySection(
                                allocationMode = allocationMode,
                                onAllocationModeChange = { modeSelection ->
                                    allocationMode = modeSelection
                                    if (modeSelection == SettlementAllocationMode.TARGETED) {
                                        val allIds = eligibleExpenses.map { it.expenseId }.toSet()
                                        selectedExpenseIds = allIds
                                        val expenseCap = eligibleExpenses.filter { it.expenseId in allIds }
                                            .sumOf { if (selectedCurrency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount }
                                        amountText = minOf(expenseCap, selectedAmountCap).toPlainString()
                                    } else {
                                        selectedExpenseIds = emptySet()
                                        amountText = selectedCurrencyOption?.amount?.toPlainString()
                                            ?: selected.amount.toPlainString()
                                    }
                                },
                                eligibleExpenses = eligibleExpenses,
                                selectedExpenseIds = selectedExpenseIds,
                                currencyCode = selectedCurrency,
                                previewMatches = previewMatches,
                                previewLines = state.preview?.lines.orEmpty(),
                                isPreviewing = state.isPreviewing,
                                previewErrorMessage = state.previewErrorMessage,
                                onSelectedExpensesChange = { ids ->
                                    selectedExpenseIds = ids
                                    val expenseCap = eligibleExpenses.filter { it.expenseId in ids }
                                        .sumOf { if (selectedCurrency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount }
                                    amountText = minOf(expenseCap, selectedAmountCap).toPlainString()
                                },
                            )

                            // 5. 代记经办人选项（当代记且有经办人选项时）
                            if (state.canActOnBehalf && selected.onBehalfOptions.isNotEmpty()) {
                                OnBehalfPickerCard(
                                    options = selected.onBehalfOptions,
                                    currentParticipantId = state.currentParticipantId.takeIf { selected.kind == SettlementCandidateKind.PERSONAL },
                                    selectedId = selectedOnBehalfId,
                                    onSelected = { selectedOnBehalfId = it },
                                )
                            }
                        }
                    }
                }
            }
        }

        // 外部数字键盘弹出层
        SharedLedgerNumericKeypad(
            state = keypad,
            onDismiss = { focusManager.clearFocus() },
            modifier = Modifier.matchParentSize(),
        )
    }
}

/**
 * 结算交易对手方选择展示区
 */
@Composable
private fun CounterpartySelectionSection(
    participants: List<TransferParticipant>,
    selectedIndex: Int,
    selected: TransferParticipant,
    isTransfer: Boolean,
    candidateScope: TransferCandidateScope,
    currencyCode: String,
    onSelectIndex: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        // 多人选择横滑胶囊条
        if (participants.size > 1) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = when (candidateScope) {
                        TransferCandidateScope.PERSONAL -> if (isTransfer) "选择收款方" else "选择付款方"
                        TransferCandidateScope.ON_BEHALF -> "选择代记账目"
                    },
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "共 ${participants.size} 人",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.outline,
                )
            }

            LazyRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
                itemsIndexed(
                    items = participants,
                    key = { _, item -> item.candidateKey },
                ) { index, item ->
                    val isCurrent = index == selectedIndex
                    val chipBg by animateColorAsState(
                        targetValue = if (isCurrent) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                        animationSpec = tween(SharedLedgerMotion.Durations.TabIndicator),
                        label = "chipBg",
                    )
                    val borderStroke = if (isCurrent) {
                        BorderStroke(1.5.dp, MaterialTheme.colorScheme.primary)
                    } else {
                        BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant)
                    }

                    Surface(
                        onClick = { onSelectIndex(index) },
                        shape = SharedLedgerRadius.Full,
                        color = chipBg,
                        border = borderStroke,
                    ) {
                        Row(
                            modifier = Modifier.padding(
                                start = SharedLedgerSpacing.XSmall,
                                end = SharedLedgerSpacing.Medium,
                                top = SharedLedgerSpacing.XSmall,
                                bottom = SharedLedgerSpacing.XSmall,
                            ),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            ParticipantAvatar(
                                name = item.participant.name,
                                background = item.participant.avatarBackground,
                                size = SharedLedgerDimens.AvatarSmall,
                            )
                            Text(
                                text = if (item.kind == SettlementCandidateKind.ON_BEHALF) {
                                    "${item.fromParticipantName}→${item.toParticipantName}"
                                } else {
                                    item.participant.name
                                },
                                style = SharedLedgerTextStyles.Label,
                                fontWeight = if (isCurrent) FontWeight.SemiBold else FontWeight.Normal,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            AmountDisplay(
                                amount = item.amount,
                                currencyCode = currencyCode,
                                fractionDigitsOverride = 1,
                                size = AmountSize.Small,
                                emphasis = if (isCurrent) AmountEmphasis.Primary else AmountEmphasis.Muted,
                            )
                        }
                    }
                }
            }
        }

        // 当前选中对象的名片大卡
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = SharedLedgerRadius.ExtraLarge,
            colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
            border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
            elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(SharedLedgerSpacing.Large),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                if (selected.kind == SettlementCandidateKind.ON_BEHALF) {
                    // 代记流向图示
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Surface(
                            shape = SharedLedgerRadius.Full,
                            color = MaterialTheme.colorScheme.tertiaryContainer,
                        ) {
                            Text(
                                text = "代记转账",
                                modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Small, vertical = 2.dp),
                                style = SharedLedgerTextStyles.ActionLabel,
                                color = MaterialTheme.colorScheme.onTertiaryContainer,
                            )
                        }
                        Text(
                            text = "债务总计",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
                        ) {
                            Text(
                                text = selected.fromParticipantName,
                                style = SharedLedgerTextStyles.CardTitle,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            Icon(
                                imageVector = Icons.Rounded.SwapHoriz,
                                contentDescription = "转账给",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                            )
                            Text(
                                text = selected.toParticipantName,
                                style = SharedLedgerTextStyles.CardTitle,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }

                        AmountDisplay(
                            amount = selected.amount,
                            currencyCode = currencyCode,
                            fractionDigitsOverride = 1,
                            size = AmountSize.Medium,
                            emphasis = AmountEmphasis.Primary,
                        )
                    }
                } else {
                    // 个人债务结算卡
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
                        ) {
                            ParticipantAvatar(
                                name = selected.participant.name,
                                background = selected.participant.avatarBackground,
                                size = SharedLedgerDimens.AvatarLarge,
                            )
                            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Text(
                                    text = selected.participant.name,
                                    style = SharedLedgerTextStyles.CardTitle,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Text(
                                    text = if (isTransfer) "待结清欠款对象" else "待收款债务人",
                                    style = SharedLedgerTextStyles.Label,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                        }

                        Column(horizontalAlignment = Alignment.End) {
                            Text(
                                text = if (isTransfer) "应付金额" else "应收金额",
                                style = SharedLedgerTextStyles.Label,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            AmountDisplay(
                                amount = selected.amount,
                                currencyCode = currencyCode,
                                fractionDigitsOverride = 1,
                                size = AmountSize.Medium,
                                emphasis = AmountEmphasis.Primary,
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 核心金额英雄输入卡片（Hero Amount Card）
 */
@Composable
private fun TransferAmountHeroCard(
    mode: TransferMode,
    selected: TransferParticipant,
    amountText: String,
    isAmountValid: Boolean,
    currencyCode: String,
    baseCurrency: String,
    multiCurrencyEnabled: Boolean,
    currencyOptions: List<SettlementCurrencyOption>,
    selectedCurrency: String,
    totalDebtAmount: BigDecimal,
    maxAmount: BigDecimal,
    onCurrencyChange: (String) -> Unit,
    onAmountChange: (String) -> Unit,
    onFillMax: () -> Unit,
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

    val currentVal = amountText.toBigDecimalOrNull()
    val targetDebtCap = if (totalDebtAmount > BigDecimal.ZERO) totalDebtAmount else maxAmount
    val fractionDigits = if (currencyCode == "CNY") 1 else 2

    val isOverMax = currentVal != null && maxAmount > BigDecimal.ZERO && currentVal > maxAmount
    val isFullSettled = currentVal != null && targetDebtCap > BigDecimal.ZERO && currentVal.compareTo(targetDebtCap) == 0
    val isPartialSettled = currentVal != null && targetDebtCap > BigDecimal.ZERO && currentVal > BigDecimal.ZERO && currentVal < targetDebtCap

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            if (isOverMax) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.outlineVariant,
        ),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            // 顶行：标题与币种切换
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    Icon(
                        imageVector = if (isTransfer) Icons.Rounded.Paid else Icons.Rounded.AccountBalanceWallet,
                        contentDescription = null,
                        tint = if (isTransfer) SageGreen else WarmOrange,
                        modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                    )
                    Text(
                        text = if (selected.kind == SettlementCandidateKind.ON_BEHALF) {
                            "转账金额"
                        } else if (isTransfer) {
                            "付款金额"
                        } else {
                            "收款金额"
                        },
                        style = SharedLedgerTextStyles.SectionTitle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }

                if (shouldShowTransferCurrencyPicker(multiCurrencyEnabled) && visibleCurrencyOptions.size > 1) {
                    SharedLedgerFluidCurrencyPicker(
                        expanded = showCurrencyMenu,
                        onExpandedChange = { showCurrencyMenu = it },
                        currencyCodes = visibleCurrencyOptions.map { it.normalizedCurrencyCode },
                        selectedCode = selectedCurrency,
                        onSelected = onCurrencyChange,
                    )
                } else {
                    Surface(
                        shape = SharedLedgerRadius.Full,
                        color = SurfaceWarmLow,
                        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                    ) {
                        Text(
                            text = currencyCode,
                            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = 4.dp),
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }

            // 大字号金额输入区域
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
                label = "金额",
                placeholder = "0.0",
                readOnly = keypad != null,
                leadingIcon = {
                    Text(
                        text = currencySymbol(currencyCode),
                        style = SharedLedgerTextStyles.SummaryCurrency,
                        color = MaterialTheme.colorScheme.primary,
                    )
                },
                trailingContent = if (amountText.isNotBlank()) {
                    @Composable {
                        IconButton(onClick = { onAmountChange("") }) {
                            Icon(
                                imageVector = Icons.Rounded.Clear,
                                contentDescription = "清除金额",
                                tint = MaterialTheme.colorScheme.outline,
                                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                            )
                        }
                    }
                } else null,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )

            // 下方状态与辅助 Chips：根据是否全部结清实时显示
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 限额说明 / 实时结清状态
                Column(modifier = Modifier.weight(1f)) {
                    when {
                        isOverMax -> {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.Info,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.size(14.dp),
                                )
                                Text(
                                    text = "金额已超过当前上限",
                                    style = SharedLedgerTextStyles.Label,
                                    color = MaterialTheme.colorScheme.error,
                                    fontWeight = FontWeight.Medium,
                                )
                            }
                        }
                        isFullSettled -> {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.CheckCircle,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(14.dp),
                                )
                                Text(
                                    text = "已全部结清",
                                    style = SharedLedgerTextStyles.Label,
                                    color = MaterialTheme.colorScheme.primary,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                        }
                        isPartialSettled -> {
                            val diff = targetDebtCap - currentVal
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.Info,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(14.dp),
                                )
                                Text(
                                    text = "未全部结清 · 还差 ${MoneyFormatter.format(diff, currencyCode, fractionDigits)}",
                                    style = SharedLedgerTextStyles.Label,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        else -> {
                            Text(
                                text = "未全部结清 · 最多可结清 ${MoneyFormatter.format(targetDebtCap, currencyCode, fractionDigits)}",
                                style = SharedLedgerTextStyles.Label,
                                color = MaterialTheme.colorScheme.outline,
                            )
                        }
                    }
                }

                // 快捷填充 Chip：全部结清 vs 已全部结清
                if (isFullSettled) {
                    Surface(
                        shape = SharedLedgerRadius.Full,
                        color = MaterialTheme.colorScheme.primaryContainer,
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.Check,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onPrimaryContainer,
                                modifier = Modifier.size(14.dp),
                            )
                            Text(
                                text = "已全部结清",
                                style = SharedLedgerTextStyles.ActionLabel,
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                } else {
                    Surface(
                        onClick = onFillMax,
                        shape = SharedLedgerRadius.Full,
                        color = MaterialTheme.colorScheme.secondaryContainer,
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.FlashOn,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSecondaryContainer,
                                modifier = Modifier.size(14.dp),
                            )
                            Text(
                                text = "全部结清",
                                style = SharedLedgerTextStyles.ActionLabel,
                                color = MaterialTheme.colorScheme.onSecondaryContainer,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 抵扣策略与账单明细核销区
 */
@Composable
private fun AllocationStrategySection(
    allocationMode: SettlementAllocationMode,
    onAllocationModeChange: (SettlementAllocationMode) -> Unit,
    eligibleExpenses: List<SettlementExpenseOption>,
    selectedExpenseIds: Set<String>,
    currencyCode: String,
    previewMatches: Boolean,
    previewLines: List<SettlementPreviewLine>,
    isPreviewing: Boolean,
    previewErrorMessage: String?,
    onSelectedExpensesChange: (Set<String>) -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            // 顶部分段：平账抵扣方式
            Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                Text(
                    text = "抵扣核销方式",
                    style = SharedLedgerTextStyles.SectionTitle,
                    color = MaterialTheme.colorScheme.onSurface,
                )

                SegmentedControl(
                    options = listOf("按账单顺序抵扣", "指定账单抵扣"),
                    selectedIndex = if (allocationMode == SettlementAllocationMode.FIFO) 0 else 1,
                    onSelected = { index ->
                        onAllocationModeChange(
                            if (index == 0) SettlementAllocationMode.FIFO else SettlementAllocationMode.TARGETED,
                        )
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            // FIFO 说明
            AnimatedVisibility(
                visible = allocationMode == SettlementAllocationMode.FIFO,
                enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically(),
            ) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = SharedLedgerRadius.Medium,
                    color = SurfaceWarmLow,
                ) {
                    Row(
                        modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Info,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                        )
                        Text(
                            text = "系统将按发生时间自动冲抵最早未结清的账单，转账后自动结清相应款项。",
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            // TARGETED 指定账单抵扣列表
            AnimatedVisibility(
                visible = allocationMode == SettlementAllocationMode.TARGETED,
                enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically(),
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    // 工具栏：已选数量与全选/清空
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "已选 ${selectedExpenseIds.size} / ${eligibleExpenses.size} 笔账单",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
                            TextButton(
                                onClick = {
                                    onSelectedExpensesChange(eligibleExpenses.map { it.expenseId }.toSet())
                                },
                                contentPadding = PaddingValues(horizontal = SharedLedgerSpacing.Small, vertical = 0.dp),
                            ) {
                                Text("全选", style = SharedLedgerTextStyles.ActionLabel)
                            }
                            TextButton(
                                onClick = { onSelectedExpensesChange(emptySet()) },
                                contentPadding = PaddingValues(horizontal = SharedLedgerSpacing.Small, vertical = 0.dp),
                            ) {
                                Text("清空", style = SharedLedgerTextStyles.ActionLabel)
                            }
                        }
                    }

                    if (eligibleExpenses.isEmpty()) {
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = SharedLedgerRadius.Medium,
                            color = SurfaceWarmLow,
                        ) {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(SharedLedgerSpacing.Large),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    text = "当前币种下没有可供指定抵扣的账单",
                                    style = SharedLedgerTextStyles.BodySecondary,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                        }
                    } else {
                        val allocationPreview = if (previewMatches) previewLines.associateBy { it.expenseId } else emptyMap()

                        eligibleExpenses
                            .groupBy { it.subActivityId.orEmpty() to (it.subActivityName ?: "当前活动") }
                            .toSortedMap(compareBy<Pair<String, String>> { it.second }.thenBy { it.first })
                            .forEach { (_, groupedExpenses) ->
                                val groupTitle = groupedExpenses.firstOrNull()?.subActivityName ?: "当前活动"
                                Text(
                                    text = groupTitle,
                                    style = SharedLedgerTextStyles.Label,
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                                )

                                groupedExpenses.forEach { expense ->
                                    val isSelected = expense.expenseId in selectedExpenseIds
                                    val amount = if (currencyCode == expense.normalizedCurrencyCode) {
                                        expense.remainingOriginalAmount
                                    } else {
                                        expense.remainingBaseAmount
                                    }

                                    Surface(
                                        onClick = {
                                            onSelectedExpensesChange(
                                                if (isSelected) selectedExpenseIds - expense.expenseId
                                                else selectedExpenseIds + expense.expenseId,
                                            )
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                        shape = SharedLedgerRadius.Large,
                                        color = if (isSelected) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f) else SurfaceWarmLow,
                                        border = BorderStroke(
                                            SharedLedgerDimens.OutlineWidth,
                                            if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
                                        ),
                                    ) {
                                        Column(modifier = Modifier.padding(SharedLedgerSpacing.Medium)) {
                                            Row(
                                                modifier = Modifier.fillMaxWidth(),
                                                verticalAlignment = Alignment.CenterVertically,
                                                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                                            ) {
                                                Checkbox(
                                                    checked = isSelected,
                                                    onCheckedChange = { checked ->
                                                        onSelectedExpensesChange(
                                                            if (checked) selectedExpenseIds + expense.expenseId
                                                            else selectedExpenseIds - expense.expenseId,
                                                        )
                                                    },
                                                    colors = CheckboxDefaults.colors(
                                                        checkedColor = MaterialTheme.colorScheme.primary,
                                                    ),
                                                )

                                                Column(modifier = Modifier.weight(1f)) {
                                                    Text(
                                                        text = expense.title?.takeIf { it.isNotBlank() } ?: "未命名账单",
                                                        style = SharedLedgerTextStyles.Body,
                                                        fontWeight = if (isSelected) FontWeight.Medium else FontWeight.Normal,
                                                        color = MaterialTheme.colorScheme.onSurface,
                                                        maxLines = 1,
                                                        overflow = TextOverflow.Ellipsis,
                                                    )
                                                    expense.occurredAt?.takeIf { it.isNotBlank() }?.let {
                                                        Text(
                                                            text = it.take(10),
                                                            style = SharedLedgerTextStyles.Label,
                                                            color = MaterialTheme.colorScheme.outline,
                                                        )
                                                    }
                                                }

                                                AmountDisplay(
                                                    amount = amount,
                                                    currencyCode = if (currencyCode == expense.normalizedCurrencyCode) expense.normalizedCurrencyCode else currencyCode,
                                                    fractionDigitsOverride = if (currencyCode == "CNY") 1 else 2,
                                                    size = AmountSize.SubActivity,
                                                    emphasis = if (isSelected) AmountEmphasis.Primary else AmountEmphasis.Standard,
                                                )
                                            }

                                            // 核销预览标签
                                            allocationPreview[expense.expenseId]?.let { line ->
                                                val remaining = if (currencyCode == expense.normalizedCurrencyCode) {
                                                    line.remainingOriginalAmount ?: line.remainingAmount
                                                } else {
                                                    line.remainingBaseAmount ?: line.remainingAmount
                                                }
                                                HorizontalDivider(
                                                    modifier = Modifier.padding(vertical = SharedLedgerSpacing.Small),
                                                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                                                )
                                                Row(
                                                    modifier = Modifier.fillMaxWidth(),
                                                    horizontalArrangement = Arrangement.SpaceBetween,
                                                    verticalAlignment = Alignment.CenterVertically,
                                                ) {
                                                    Text(
                                                        text = "本次抵扣 " + MoneyFormatter.format(line.amount, currencyCode, if (currencyCode == "CNY") 1 else 2),
                                                        style = SharedLedgerTextStyles.Label,
                                                        color = MaterialTheme.colorScheme.primary,
                                                        fontWeight = FontWeight.Medium,
                                                    )
                                                    remaining?.let { rem ->
                                                        Text(
                                                            text = "剩余 " + MoneyFormatter.format(rem, currencyCode, if (currencyCode == "CNY") 1 else 2),
                                                            style = SharedLedgerTextStyles.Label,
                                                            color = MaterialTheme.colorScheme.outline,
                                                        )
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                    }

                    // 预览加载/错误反馈
                    if (isPreviewing) {
                        Row(
                            modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(14.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.primary,
                            )
                            Text(
                                text = "正在核对抵扣试算…",
                                style = SharedLedgerTextStyles.Label,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }

                    previewErrorMessage?.let { message ->
                        Text(
                            text = message,
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                        )
                    }
                }
            }
        }
    }
}

/**
 * 代记经办人选项卡片
 */
@Composable
private fun OnBehalfPickerCard(
    options: List<SettlementParticipant>,
    currentParticipantId: String?,
    selectedId: String?,
    onSelected: (String?) -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Text(
                text = if (currentParticipantId == null) "代记经办人（必选）" else "代记经办人（可选）",
                style = SharedLedgerTextStyles.SectionTitle,
                color = MaterialTheme.colorScheme.onSurface,
            )

            Text(
                text = "请指定这笔交易在谁的账目下扣除或增加",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            LazyRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
                if (currentParticipantId != null) {
                    item(key = "self") {
                        val isSelf = selectedId == null
                        Surface(
                            onClick = { onSelected(null) },
                            shape = SharedLedgerRadius.Full,
                            color = if (isSelf) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                            border = BorderStroke(
                                SharedLedgerDimens.OutlineWidth,
                                if (isSelf) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
                            ),
                        ) {
                            Text(
                                text = "本人",
                                modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.Small),
                                style = SharedLedgerTextStyles.Label,
                                fontWeight = if (isSelf) FontWeight.SemiBold else FontWeight.Normal,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                    }
                }

                itemsIndexed(options) { _, option ->
                    val isOptionSelected = selectedId == option.participantId
                    Surface(
                        onClick = { onSelected(option.participantId) },
                        shape = SharedLedgerRadius.Full,
                        color = if (isOptionSelected) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLow,
                        border = BorderStroke(
                            SharedLedgerDimens.OutlineWidth,
                            if (isOptionSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
                        ),
                    ) {
                        Text(
                            text = option.participantName,
                            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.Small),
                            style = SharedLedgerTextStyles.Label,
                            fontWeight = if (isOptionSelected) FontWeight.SemiBold else FontWeight.Normal,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
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

@Preview(name = "转账模式", showBackground = true, widthDp = 390, heightDp = 844)
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
                    TransferCandidateUi(
                        participantId = "preview-alice",
                        participantName = "张三",
                        amount = BigDecimal("120.0"),
                        fromParticipantId = "preview-me",
                        fromParticipantName = "我",
                        toParticipantId = "preview-alice",
                        toParticipantName = "张三",
                    ),
                ),
            ),
        )
    }
}

@Preview(name = "收款模式", showBackground = true, widthDp = 390, heightDp = 844)
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
