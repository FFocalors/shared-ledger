package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import com.ffocalors.sharedledger.data.financial.FinancialContext
import com.ffocalors.sharedledger.data.financial.PrepaymentAccount
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerCtaBottomBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerNumericKeypad
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.NumericKeypadState
import com.ffocalors.sharedledger.ui.components.numericKeypadTarget
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import java.math.BigDecimal

enum class PrepaymentMode { FUND, RETURN }

@Composable
fun PrepaymentScreen(
    mode: PrepaymentMode,
    context: FinancialContext?,
    isLoading: Boolean,
    isSubmitting: Boolean,
    errorMessage: String?,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    onSubmit: (ownerId: String, custodianId: String, amount: BigDecimal, onBehalfOfParticipantId: String?) -> Unit,
) {
    var selectedId by remember(context, mode) { mutableStateOf<String?>(null) }
    var amountText by remember(context, mode) { mutableStateOf("") }
    var selectedOnBehalfId by remember(context, mode) { mutableStateOf<String?>(null) }
    val keypad = remember { NumericKeypadState() }
    val focusManager = LocalFocusManager.current
    val currentId = context?.currentParticipantId
    val candidates = when {
        context == null -> emptyList()
        mode == PrepaymentMode.FUND && context.canActOnBehalf -> context.participants.flatMap { owner ->
            context.participants.filter { it.participantId != owner.participantId }.map { target ->
                buildPrepaymentPairCandidate(mode, owner, target, context.accounts.firstOrNull { it.owner.participantId == owner.participantId && it.custodian.participantId == target.participantId }, context.unclaimedParticipants)
            }
        }.filter { it.onBehalfOptions.isNotEmpty() }
            .let { proxyCandidates ->
                val ownCandidates = currentId?.let { current ->
                    context.participants.filter { it.participantId != current }
                        .map { target ->
                            buildPrepaymentCandidate(
                                mode,
                                current,
                                target,
                                context.accounts.firstOrNull { it.owner.participantId == current && it.custodian.participantId == target.participantId },
                                context.unclaimedParticipants,
                            )
                        }
                }.orEmpty()
                (ownCandidates + proxyCandidates).distinctBy { it.key }
            }
        mode == PrepaymentMode.FUND && currentId != null -> context.participants.filter { it.participantId != currentId }
            .map { target -> buildPrepaymentCandidate(mode, currentId, target, context.accounts.firstOrNull { it.owner.participantId == currentId && it.custodian.participantId == target.participantId }, context.unclaimedParticipants) }
        mode == PrepaymentMode.RETURN && context.canActOnBehalf -> context.accounts.map { account ->
            buildPrepaymentPairCandidate(mode, account.owner, account.custodian, account, context.unclaimedParticipants)
        }.filter { it.onBehalfOptions.isNotEmpty() || it.custodianId == currentId }
        else -> context.accounts.filter { it.custodian.participantId == currentId }
            .map { buildPrepaymentCandidate(mode, currentId.orEmpty(), it.owner, it, context.unclaimedParticipants) }
    }
    val selected = candidates.firstOrNull { it.key == selectedId } ?: candidates.firstOrNull()
    LaunchedEffect(selected?.key, selected?.onBehalfOptions) {
        selectedOnBehalfId = if (currentId == null) selected?.onBehalfOptions?.firstOrNull()?.participantId else null
    }
    val max = prepaymentAmountLimit(mode, selected)
    val amount = amountText.toBigDecimalOrNull()
    val directionValid = selected?.let(::isValidPrepaymentDirection) == true
    val valid = directionValid && amount != null && amount > BigDecimal.ZERO && (max == null || amount <= max)
    val actingPartyValid = selected?.let { choice ->
        isValidPrepaymentActingParty(choice, currentId, selectedOnBehalfId)
    } == true
    val hazeState = rememberSharedLedgerHazeState()

    Box(modifier = Modifier.fillMaxSize()) {
    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = if (mode == PrepaymentMode.FUND) "新增预存" else "返还预存",
                showBackButton = true,
                onBackClick = onBack,
                hazeState = hazeState,
            )
        },
        bottomBar = {
            val choice = selected
            if (!isLoading && errorMessage == null && candidates.isNotEmpty() && choice != null) {
                SharedLedgerCtaBottomBar(hazeState = hazeState) {
                    SharedLedgerButton(
                        text = if (mode == PrepaymentMode.FUND) "确认新增预存" else "确认返还预存",
                        onClick = {
                            if (isValidPrepaymentDirection(choice)) {
                                onSubmit(choice.ownerId, choice.custodianId, amount ?: BigDecimal.ZERO, selectedOnBehalfId)
                            }
                        },
                        enabled = valid && actingPartyValid && !isSubmitting,
                        loading = isSubmitting,
                        loadingText = "提交中…",
                        tone = if (mode == PrepaymentMode.FUND) SharedLedgerButtonTone.WarmSecondary else SharedLedgerButtonTone.SoftPrimary,
                        icon = Icons.Rounded.ArrowForward,
                    )
                }
            }
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.widthIn(max = SharedLedgerDimens.ContentMaxWidth).fillMaxSize().sharedLedgerHazeSource(hazeState),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(
                start = SharedLedgerDimens.PageHorizontalPadding,
                top = padding.calculateTopPadding() + SharedLedgerSpacing.Large,
                end = SharedLedgerDimens.PageHorizontalPadding,
                bottom = padding.calculateBottomPadding() + SharedLedgerSpacing.Large,
            ),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                    Text(if (mode == PrepaymentMode.FUND) "预存一笔活动资金" else "选择要返还的预存", style = SharedLedgerTextStyles.PageTitle)
                    Text(
                        if (mode == PrepaymentMode.FUND) "预存会先抵扣当前已有债务，剩余部分进入预存余额。" else "返还金额不能超过服务端记录的可用余额。",
                        style = SharedLedgerTextStyles.BodySecondary,
                    )
                }
            }
            if (isLoading) {
                item { LoadingState(message = "正在读取预存余额…") }
            } else if (errorMessage != null) {
                item { ErrorState(message = errorMessage, onRetry = onRetry) }
            } else if (candidates.isEmpty()) {
                item {
                    EmptyState(
                        title = if (mode == PrepaymentMode.RETURN) "暂无可返还的预存余额" else "当前账号尚未绑定参与人",
                    )
                }
            } else {
                item {
                    Text(
                        if (mode == PrepaymentMode.FUND) "预存给" else "预存来源",
                        style = SharedLedgerTextStyles.SectionTitle,
                        modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall),
                    )
                }
                items(candidates, key = { it.key }) { candidate ->
                    val selectedNow = candidate.key == selected?.key
                    Surface(
                        onClick = {
                            selectedId = candidate.key
                            selectedOnBehalfId = null
                            amountText = if (mode == PrepaymentMode.RETURN) {
                                candidate.account?.balance?.toPlainString().orEmpty()
                            } else {
                                ""
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = SharedLedgerRadius.Large,
                        color = if (selectedNow) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLowest,
                        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                        shadowElevation = if (selectedNow) SharedLedgerElevation.Card else SharedLedgerElevation.Flat,
                    ) {
                        Row(
                            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            Icon(Icons.Rounded.AccountBalanceWallet, contentDescription = null)
                            Column(Modifier.weight(1f)) {
                                Text(candidate.person.displayName, style = SharedLedgerTextStyles.CardTitle)
                                when {
                                    mode == PrepaymentMode.RETURN && candidate.account != null ->
                                        Text("可返还", style = SharedLedgerTextStyles.Label)
                                    mode == PrepaymentMode.FUND && candidate.account != null ->
                                        Text("已有预存，可继续新增", style = SharedLedgerTextStyles.Label)
                                    mode == PrepaymentMode.FUND ->
                                        Text("暂无预存", style = SharedLedgerTextStyles.Label)
                                }
                            }
                            PrepaymentBalanceSummary(
                                account = candidate.account,
                                currency = context?.currency ?: "CNY",
                            )
                        }
                    }
                }
                selected?.let { choice ->
                    item {
                        Column(
                            modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall),
                            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            SharedLedgerTextField(
                                value = amountText,
                                onValueChange = { value -> amountText = value.filter { it.isDigit() || it == '.' }.take(12) },
                                label = "金额（${context?.currency ?: "CNY"}）",
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .numericKeypadTarget(keypad, { amountText }, { value -> amountText = value.filter { it.isDigit() || it == '.' }.take(12) }),
                                readOnly = true,
                            )
                            max?.let { Text("最多可返还 ${it.toPlainString()}", style = SharedLedgerTextStyles.Label) }
                            if (amountText.isNotBlank() && !valid) Text("请输入有效金额${max?.let { "，且不超过 ${it.toPlainString()}" } ?: ""}", color = MaterialTheme.colorScheme.error, style = SharedLedgerTextStyles.Label)
                            if (!directionValid) {
                                Text(
                                    "预存所有者和保管人不能是同一位参与人",
                                    color = MaterialTheme.colorScheme.error,
                                    style = SharedLedgerTextStyles.Label,
                                )
                            }
                            val currentIsParty = currentId != null &&
                                (currentId == choice.ownerId || currentId == choice.custodianId)
                            if (context?.canActOnBehalf == true && choice.onBehalfOptions.isNotEmpty()) {
                                PrepaymentOnBehalfPicker(
                                    options = choice.onBehalfOptions,
                                    showSelfOption = currentIsParty,
                                    required = !currentIsParty,
                                    selectedId = selectedOnBehalfId,
                                    onSelected = { selectedOnBehalfId = it },
                                )
                            }
                        }
                    }
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

internal data class PrepaymentCandidate(
    val ownerId: String,
    val custodianId: String,
    val person: ParticipantInfo,
    val account: PrepaymentAccount?,
    val onBehalfOptions: List<ParticipantInfo> = emptyList(),
) {
    val key: String get() = "${ownerId}:${custodianId}"
}

internal fun buildPrepaymentCandidate(
    mode: PrepaymentMode,
    currentParticipantId: String,
    targetParticipant: ParticipantInfo,
    account: PrepaymentAccount? = null,
    unclaimedParticipants: List<ParticipantInfo> = emptyList(),
): PrepaymentCandidate = when (mode) {
    PrepaymentMode.FUND -> PrepaymentCandidate(
        ownerId = currentParticipantId,
        custodianId = targetParticipant.participantId,
        person = targetParticipant,
        account = account,
        onBehalfOptions = listOf(currentParticipantId, targetParticipant.participantId).distinct()
            .mapNotNull { id -> unclaimedParticipants.firstOrNull { it.participantId == id } },
    )
    PrepaymentMode.RETURN -> PrepaymentCandidate(
        ownerId = account?.owner?.participantId ?: targetParticipant.participantId,
        custodianId = currentParticipantId,
        person = account?.owner ?: targetParticipant,
        account = account,
        onBehalfOptions = listOf(account?.custodian?.participantId ?: currentParticipantId, account?.owner?.participantId ?: targetParticipant.participantId).distinct()
            .mapNotNull { id -> unclaimedParticipants.firstOrNull { it.participantId == id } },
    )
}

internal fun buildPrepaymentPairCandidate(
    mode: PrepaymentMode,
    owner: ParticipantInfo,
    custodian: ParticipantInfo,
    account: PrepaymentAccount?,
    unclaimedParticipants: List<ParticipantInfo>,
): PrepaymentCandidate = PrepaymentCandidate(
    ownerId = owner.participantId,
    custodianId = custodian.participantId,
    person = if (mode == PrepaymentMode.FUND) custodian else owner,
    account = account,
    onBehalfOptions = listOf(owner.participantId, custodian.participantId).distinct()
        .mapNotNull { id -> unclaimedParticipants.firstOrNull { it.participantId == id } },
)

internal fun isValidPrepaymentDirection(candidate: PrepaymentCandidate): Boolean =
    candidate.ownerId.isNotBlank() &&
        candidate.custodianId.isNotBlank() &&
        candidate.ownerId != candidate.custodianId

internal fun isValidPrepaymentActingParty(
    candidate: PrepaymentCandidate,
    currentParticipantId: String?,
    onBehalfOfParticipantId: String?,
): Boolean {
    val currentIsParty = currentParticipantId != null &&
        (currentParticipantId == candidate.ownerId || currentParticipantId == candidate.custodianId)
    return if (currentIsParty) {
        onBehalfOfParticipantId == null || candidate.onBehalfOptions.any { it.participantId == onBehalfOfParticipantId }
    } else {
        onBehalfOfParticipantId != null && candidate.onBehalfOptions.any { it.participantId == onBehalfOfParticipantId }
    }
}

internal fun prepaymentAmountLimit(
    mode: PrepaymentMode,
    candidate: PrepaymentCandidate?,
): BigDecimal? = candidate?.account?.balance?.takeIf { mode == PrepaymentMode.RETURN }

@Composable
private fun PrepaymentBalanceSummary(
    account: PrepaymentAccount?,
    currency: String,
) {
    Column(horizontalAlignment = Alignment.End) {
        Text("当前余额", style = SharedLedgerTextStyles.Label)
        if (account == null) {
            Text("暂无预存", style = SharedLedgerTextStyles.Label)
        } else {
            AmountDisplay(account.balance, currencyCode = currency, size = AmountSize.Small)
            Text("已抵扣", style = SharedLedgerTextStyles.Label)
            AmountDisplay(account.usedAmount, currencyCode = currency, size = AmountSize.Small)
        }
    }
}

@Composable
private fun PrepaymentOnBehalfPicker(
    options: List<ParticipantInfo>,
    showSelfOption: Boolean,
    required: Boolean,
    selectedId: String?,
    onSelected: (String?) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        Text(if (required) "代记参与人（必选）" else "代记参与人（可选）", style = SharedLedgerTextStyles.Label)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            if (showSelfOption) {
                item(key = "self") {
                    OnBehalfChip(
                        label = "本人",
                        selected = selectedId == null,
                        onClick = { onSelected(null) },
                    )
                }
            }
            items(options, key = { it.participantId }) { option ->
                OnBehalfChip(
                    label = option.displayName,
                    selected = selectedId == option.participantId,
                    onClick = { onSelected(option.participantId) },
                )
            }
        }
    }
}

@Composable
private fun OnBehalfChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        onClick = onClick,
        shape = SharedLedgerRadius.Full,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLowest,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Box(
            modifier = Modifier
                .defaultMinSize(minHeight = SharedLedgerDimens.TopBarActionSize)
                .padding(horizontal = SharedLedgerSpacing.Medium),
            contentAlignment = Alignment.Center,
        ) {
            Text(label, style = SharedLedgerTextStyles.Label)
        }
    }
}
