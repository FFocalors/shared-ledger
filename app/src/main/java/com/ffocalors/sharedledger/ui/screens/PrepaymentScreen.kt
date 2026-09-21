package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.ArrowForward
import androidx.compose.material.icons.rounded.Check
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.financial.FinancialContext
import com.ffocalors.sharedledger.data.financial.PrepaymentAccount
import com.ffocalors.sharedledger.data.financial.PrepaymentPreview
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerCtaBottomBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerNumericKeypad
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.NumericKeypadState
import com.ffocalors.sharedledger.ui.components.numericKeypadTarget
import com.ffocalors.sharedledger.ui.components.SharedLedgerFluidCurrencyPicker
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import java.math.BigDecimal
import kotlinx.coroutines.delay

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
    onSubmit: (ownerId: String, custodianId: String, amount: BigDecimal, currency: String, onBehalfOfParticipantId: String?) -> Unit,
    preview: PrepaymentPreview? = null,
    onPreviewRequested: ((ownerId: String, custodianId: String, amount: BigDecimal, currency: String, onBehalfOfParticipantId: String?) -> Unit)? = null,
) {
    var selectedId by remember(context, mode) { mutableStateOf<String?>(null) }
    var selectedOwnerId by remember(context, mode) {
        mutableStateOf(context?.currentParticipantId ?: context?.participants?.firstOrNull()?.participantId)
    }
    var selectedCustodianId by remember(context, mode) {
        mutableStateOf(
            context?.let { value ->
                value.participants
                    .firstOrNull { it.participantId != (value.currentParticipantId ?: value.participants.firstOrNull()?.participantId) }
                    ?.participantId
            },
        )
    }
    var selectedCurrency by remember(context, mode) {
        mutableStateOf(context?.baseCurrency?.trim()?.uppercase() ?: context?.currency?.trim()?.uppercase() ?: "CNY")
    }
    var showCurrencyMenu by remember(context, mode) { mutableStateOf(false) }
    var amountText by remember(context, mode) { mutableStateOf("") }
    var selectedOnBehalfId by remember(context, mode) { mutableStateOf<String?>(null) }
    val keypad = remember { NumericKeypadState() }
    val focusManager = LocalFocusManager.current
    val currentId = context?.currentParticipantId
    val supportedCurrencies = remember(context) {
        if (context?.multiCurrencyEnabled == true) {
            (listOf(context.currency) + context.supportedCurrencies).map { it.trim().uppercase() }.distinct()
        } else listOf(context?.currency?.trim()?.uppercase() ?: "CNY")
    }
    LaunchedEffect(context?.activityId, context?.participants, context?.multiCurrencyEnabled, supportedCurrencies) {
        val participantIds = context?.participants.orEmpty().map { it.participantId }
        if (selectedOwnerId == null || participantIds.none { it == selectedOwnerId }) {
            selectedOwnerId = currentId ?: participantIds.firstOrNull()
        }
        if (
            selectedCustodianId == null ||
            selectedCustodianId == selectedOwnerId ||
            participantIds.none { it == selectedCustodianId }
        ) {
            selectedCustodianId = participantIds.firstOrNull { it != selectedOwnerId }
        }
        if (context?.multiCurrencyEnabled != true || selectedCurrency !in supportedCurrencies) {
            selectedCurrency = context?.baseCurrency?.trim()?.uppercase()
                ?: context?.currency?.trim()?.uppercase()
                ?: "CNY"
            showCurrencyMenu = false
        }
    }
    // Adding a prepayment is an activity-level operation: the payer and holder may be
    // any activity participants. Acting-on-behalf remains a return-only concern below.
    val fundOwnerOptions = context?.participants.orEmpty()
    val fundCustodianOptions = context?.participants.orEmpty().filter { it.participantId != selectedOwnerId }
    val fundOwner = fundOwnerOptions.firstOrNull { it.participantId == selectedOwnerId }
    val fundCustodian = fundCustodianOptions.firstOrNull { it.participantId == selectedCustodianId }
    val fundCandidate = if (mode == PrepaymentMode.FUND && fundOwner != null && fundCustodian != null) {
        val account = context?.accounts?.firstOrNull {
            it.owner.participantId == fundOwner.participantId &&
                it.custodian.participantId == fundCustodian.participantId &&
                it.currency.equals(selectedCurrency, ignoreCase = true)
        }
        buildPrepaymentPairCandidate(
            mode = PrepaymentMode.FUND,
            owner = fundOwner,
            custodian = fundCustodian,
            account = account,
            unclaimedParticipants = context?.unclaimedParticipants.orEmpty(),
            currency = selectedCurrency,
        )
    } else null
    val returnCandidates = if (mode == PrepaymentMode.RETURN) {
        when {
            context == null -> emptyList()
            context.canActOnBehalf -> context.accounts.map { account ->
                buildPrepaymentPairCandidate(mode, account.owner, account.custodian, account, context.unclaimedParticipants, account.currency)
            }.filter { it.onBehalfOptions.isNotEmpty() || it.custodianId == currentId }
            else -> context.accounts.filter { it.custodian.participantId == currentId }
                .map { buildPrepaymentCandidate(mode, currentId.orEmpty(), it.owner, it, context.unclaimedParticipants) }
        }
    } else emptyList()
    val candidates = if (mode == PrepaymentMode.FUND) listOfNotNull(fundCandidate) else returnCandidates
    val selected = if (mode == PrepaymentMode.FUND) fundCandidate else {
        candidates.firstOrNull { it.key == selectedId } ?: candidates.firstOrNull()
    }
    LaunchedEffect(selected?.key, selected?.onBehalfOptions, mode) {
        selectedOnBehalfId = if (mode == PrepaymentMode.RETURN && currentId == null) {
            selected?.onBehalfOptions?.firstOrNull()?.participantId
        } else {
            null
        }
    }
    val max = prepaymentAmountLimit(mode, selected)
    val amount = amountText.toBigDecimalOrNull()
    val directionValid = selected?.let(::isValidPrepaymentDirection) == true
    val valid = directionValid && amount != null && amount > BigDecimal.ZERO && (max == null || amount <= max)
    val actingPartyValid = if (mode == PrepaymentMode.FUND) {
        true
    } else {
        selected?.let { choice ->
            isValidPrepaymentActingParty(choice, currentId, selectedOnBehalfId)
        } == true
    }
    LaunchedEffect(mode, selected?.key, amountText, selectedOnBehalfId, onPreviewRequested) {
        val choice = selected
        if (mode == PrepaymentMode.FUND && choice != null && valid && onPreviewRequested != null) {
            delay(250)
            onPreviewRequested(
                choice.ownerId,
                choice.custodianId,
                amount!!,
                choice.currency,
                selectedOnBehalfId.takeIf { mode == PrepaymentMode.RETURN },
            )
        }
    }
    val amountSection: @Composable (PrepaymentCandidate) -> Unit = { choice ->
        Column(
            modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            if (mode == PrepaymentMode.FUND) {
                PrepaymentBalanceSummary(
                    account = choice.account,
                    currency = choice.currency,
                )
            }
            SharedLedgerTextField(
                value = amountText,
                onValueChange = { value -> amountText = value.filter { it.isDigit() || it == '.' }.take(12) },
                label = "金额（${choice.currency}）",
                modifier = Modifier
                    .fillMaxWidth()
                    .numericKeypadTarget(keypad, { amountText }, { value -> amountText = value.filter { it.isDigit() || it == '.' }.take(12) }),
                readOnly = true,
            )
            max?.let { Text("最多可返还 ${it.toPlainString()} ${choice.currency}", style = SharedLedgerTextStyles.Label) }
            if (amountText.isNotBlank() && !valid) Text("请输入有效金额${max?.let { "，且不超过 ${it.toPlainString()}" } ?: ""}", color = MaterialTheme.colorScheme.error, style = SharedLedgerTextStyles.Label)
            preview
                ?.takeIf { mode == PrepaymentMode.FUND }
                ?.takeIf {
                    it.ownerParticipantId == choice.ownerId &&
                        it.custodianParticipantId == choice.custodianId &&
                        it.currency.equals(choice.currency, ignoreCase = true) &&
                        it.requestedAmount == amount
                }
                ?.let {
                    Text(
                        "本次用于结算 ${it.settlementAmount.toPlainString()} ${choice.currency}，新增预存余额 ${it.newPrepaymentBalance.toPlainString()} ${choice.currency}",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            if (!directionValid) {
                Text(
                    "预存所有者和保管人不能是同一位参与人",
                    color = MaterialTheme.colorScheme.error,
                    style = SharedLedgerTextStyles.Label,
                )
            }
            if (mode == PrepaymentMode.RETURN) {
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
                                onSubmit(
                                    choice.ownerId,
                                    choice.custodianId,
                                    amount ?: BigDecimal.ZERO,
                                    choice.currency,
                                    selectedOnBehalfId.takeIf { mode == PrepaymentMode.RETURN },
                                )
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
                        title = if (mode == PrepaymentMode.RETURN) "暂无可返还的预存余额" else "暂无可用的预存双方",
                    )
                }
            } else {
                if (mode == PrepaymentMode.FUND) {
                    if (context?.multiCurrencyEnabled == true) {
                        item {
                            Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                                Text("预存币种", style = SharedLedgerTextStyles.SectionTitle)
                                Box(modifier = Modifier.fillMaxWidth()) {
                                    SharedLedgerFluidCurrencyPicker(
                                        expanded = showCurrencyMenu,
                                        onExpandedChange = { showCurrencyMenu = it },
                                        currencyCodes = supportedCurrencies,
                                        selectedCode = selectedCurrency,
                                        onSelected = {
                                            selectedCurrency = it.trim().uppercase()
                                            selectedOnBehalfId = null
                                            amountText = ""
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
                            }
                        }
                    }
                    selected?.let { choice ->
                        item { amountSection(choice) }
                    }
                    item {
                        Column(
                            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
                            modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall),
                        ) {
                            Text("选择预存双方", style = SharedLedgerTextStyles.SectionTitle)
                            PrepaymentPartyDirectionCard(owner = fundOwner, custodian = fundCustodian)
                            PrepaymentPartyTileRow(
                                label = "谁在付款？",
                                participants = fundOwnerOptions,
                                selectedId = selectedOwnerId,
                                onSelected = { participantId ->
                                    selectedOwnerId = participantId
                                    if (selectedCustodianId == participantId) {
                                        selectedCustodianId = context?.participants
                                            ?.firstOrNull { it.participantId != participantId }
                                            ?.participantId
                                    }
                                    selectedOnBehalfId = null
                                    amountText = ""
                                },
                            )
                            PrepaymentPartyTileRow(
                                label = "预存给谁持有？",
                                participants = fundCustodianOptions,
                                selectedId = selectedCustodianId,
                                onSelected = { participantId ->
                                    selectedCustodianId = participantId
                                    selectedOnBehalfId = null
                                    amountText = ""
                                },
                            )
                        }
                    }
                } else {
                    item {
                        Text(
                            "预存来源",
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
                                amountText = candidate.account?.balance?.toPlainString().orEmpty()
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
                                    Text("可返还", style = SharedLedgerTextStyles.Label)
                                }
                                if (context?.multiCurrencyEnabled == true) {
                                    Text(candidate.currency, style = SharedLedgerTextStyles.CardTitle)
                                }
                                PrepaymentBalanceSummary(
                                    account = candidate.account,
                                    currency = candidate.currency,
                                )
                            }
                        }
                    }
                    selected?.let { choice ->
                        item { amountSection(choice) }
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

/** 当前预存方向摘要：左侧付款方、右侧持有方，中间用圆形箭头表达资金流向。 */
@Composable
private fun PrepaymentPartyDirectionCard(
    owner: ParticipantInfo?,
    custodian: ParticipantInfo?,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        color = SurfaceWarmLowest,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PartyEndpoint(
                participant = owner,
                roleLabel = "付款方",
                modifier = Modifier.weight(1f),
            )
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Small),
            ) {
                Box(
                    modifier = Modifier
                        .size(SharedLedgerDimens.ActionIconContainer)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Rounded.ArrowForward,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(SharedLedgerDimens.ActionIcon),
                    )
                }
                Text("发起预存", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            PartyEndpoint(
                participant = custodian,
                roleLabel = "持有方",
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun PartyEndpoint(
    participant: ParticipantInfo?,
    roleLabel: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
    ) {
        if (participant != null) {
            ParticipantAvatar(
                name = participant.displayName,
                background = if (participant.claimedUserId != null) {
                    AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
                } else {
                    AvatarBackground.Unbound(participant.participantId.ifBlank { participant.displayName })
                },
                size = SharedLedgerDimens.AvatarLarge,
            )
            Text(
                participant.displayName,
                style = SharedLedgerTextStyles.CardTitle,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        } else {
            Box(
                modifier = Modifier
                    .size(SharedLedgerDimens.AvatarLarge)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
            )
            Text("未选择", style = SharedLedgerTextStyles.CardTitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(roleLabel, style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** 一方参与人的宫格选择：头像在上、名字在下，选中项带主色描边与对勾角标。 */
@Composable
private fun PrepaymentPartyTileRow(
    label: String,
    participants: List<ParticipantInfo>,
    selectedId: String?,
    onSelected: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
        Text(label, style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (participants.isEmpty()) {
            Text("暂无可选参与人", style = SharedLedgerTextStyles.BodySecondary)
        } else {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) {
                items(participants, key = { it.participantId }) { participant ->
                    PartyTile(
                        name = participant.displayName,
                        avatarBackground = if (participant.claimedUserId != null) {
                            AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
                        } else {
                            AvatarBackground.Unbound(participant.participantId.ifBlank { participant.displayName })
                        },
                        selected = participant.participantId == selectedId,
                        onClick = { onSelected(participant.participantId) },
                    )
                }
            }
        }
    }
}

@Composable
private fun PartyTile(
    name: String,
    avatarBackground: AvatarBackground,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .widthIn(min = 64.dp)
            .clip(SharedLedgerRadius.Medium)
            .clickable(onClick = onClick)
            .padding(SharedLedgerSpacing.XSmall),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
    ) {
        Box {
            Surface(
                shape = CircleShape,
                color = Color.Transparent,
                border = if (selected) {
                    BorderStroke(SharedLedgerDimens.AvatarBorder, MaterialTheme.colorScheme.primary)
                } else {
                    BorderStroke(SharedLedgerDimens.AvatarBorder, Color.Transparent)
                },
            ) {
                ParticipantAvatar(
                    name = name,
                    background = avatarBackground,
                    size = SharedLedgerDimens.AvatarLarge,
                    animateBackground = false,
                )
            }
            if (selected) {
                Surface(
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .size(SharedLedgerDimens.IconSmall),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            Icons.Rounded.Check,
                            contentDescription = "已选择",
                            tint = MaterialTheme.colorScheme.onPrimary,
                            modifier = Modifier.size(12.dp),
                        )
                    }
                }
            }
        }
        Text(
            name,
            style = SharedLedgerTextStyles.Label,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

internal data class PrepaymentCandidate(
    val ownerId: String,
    val custodianId: String,
    val person: ParticipantInfo,
    val account: PrepaymentAccount?,
    val onBehalfOptions: List<ParticipantInfo> = emptyList(),
    val currency: String = "CNY",
) {
    val key: String get() = "${ownerId}:${custodianId}:${currency.trim().uppercase()}"
}

internal fun buildPrepaymentCandidate(
    mode: PrepaymentMode,
    currentParticipantId: String,
    targetParticipant: ParticipantInfo,
    account: PrepaymentAccount? = null,
    unclaimedParticipants: List<ParticipantInfo> = emptyList(),
    currency: String = account?.currency ?: "CNY",
): PrepaymentCandidate = when (mode) {
    PrepaymentMode.FUND -> PrepaymentCandidate(
        ownerId = currentParticipantId,
        custodianId = targetParticipant.participantId,
        person = targetParticipant,
        account = account,
        onBehalfOptions = listOf(currentParticipantId, targetParticipant.participantId).distinct()
            .mapNotNull { id -> unclaimedParticipants.firstOrNull { it.participantId == id } },
        currency = currency.trim().uppercase(),
    )
    PrepaymentMode.RETURN -> PrepaymentCandidate(
        ownerId = account?.owner?.participantId ?: targetParticipant.participantId,
        custodianId = currentParticipantId,
        person = account?.owner ?: targetParticipant,
        account = account,
        onBehalfOptions = listOf(account?.custodian?.participantId ?: currentParticipantId, account?.owner?.participantId ?: targetParticipant.participantId).distinct()
            .mapNotNull { id -> unclaimedParticipants.firstOrNull { it.participantId == id } },
        currency = currency.trim().uppercase(),
    )
}

internal fun buildPrepaymentPairCandidate(
    mode: PrepaymentMode,
    owner: ParticipantInfo,
    custodian: ParticipantInfo,
    account: PrepaymentAccount?,
    unclaimedParticipants: List<ParticipantInfo>,
    currency: String = account?.currency ?: "CNY",
): PrepaymentCandidate = PrepaymentCandidate(
    ownerId = owner.participantId,
    custodianId = custodian.participantId,
    person = if (mode == PrepaymentMode.FUND) custodian else owner,
    account = account,
    onBehalfOptions = listOf(owner.participantId, custodian.participantId).distinct()
        .mapNotNull { id -> unclaimedParticipants.firstOrNull { it.participantId == id } },
    currency = currency.trim().uppercase(),
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
                    PartyTile(
                        name = "本人",
                        avatarBackground = AvatarBackground.Unbound("本人"),
                        selected = selectedId == null,
                        onClick = { onSelected(null) },
                    )
                }
            }
            items(options, key = { it.participantId }) { option ->
                PartyTile(
                    name = option.displayName,
                    avatarBackground = if (option.claimedUserId != null) {
                        AvatarBackground.Bound(option.avatarStyle, option.claimedUserId)
                    } else {
                        AvatarBackground.Unbound(option.participantId.ifBlank { option.displayName })
                    },
                    selected = selectedId == option.participantId,
                    onClick = { onSelected(option.participantId) },
                )
            }
        }
    }
}
