package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.EditNote
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerDialog
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.expense.ExpenseSplitMethod
import com.ffocalors.sharedledger.data.exchange.SupportedExchangeCurrency
import com.ffocalors.sharedledger.data.exchange.ExchangeRate
import com.ffocalors.sharedledger.ui.components.CurrencyFlag
import com.ffocalors.sharedledger.ui.components.ErrorBanner
import com.ffocalors.sharedledger.ui.components.ExpenseIconPickerSheet
import com.ffocalors.sharedledger.ui.components.ParticipantAmountRow
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SegmentedControl
import com.ffocalors.sharedledger.ui.components.SharedLedgerCtaBottomBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerFluidCurrencyPicker
import com.ffocalors.sharedledger.ui.components.SharedLedgerNumericKeypad
import com.ffocalors.sharedledger.ui.components.SharedLedgerPrimaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.NumericKeypadState
import com.ffocalors.sharedledger.ui.components.numericKeypadTarget
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.expenseIconLabel
import com.ffocalors.sharedledger.ui.components.expenseIconVector
import com.ffocalors.sharedledger.ui.expense.ExpenseFormDraft
import com.ffocalors.sharedledger.ui.expense.ExpenseFormMode
import com.ffocalors.sharedledger.ui.expense.ExpenseFormParticipant
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.ComponentSizes
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneOffset

private val PreviewParticipants = listOf(
    ExpenseFormParticipant("demo-zhang", "张三"),
    ExpenseFormParticipant("demo-li", "李四"),
    ExpenseFormParticipant("demo-wang", "王五"),
)

private val ExpenseUiOffset = ZoneOffset.ofHours(8)

internal fun parseExpenseOccurredAt(value: String, fallback: Instant = Instant.now()): LocalDateTime =
    runCatching { Instant.parse(value.trim()).atOffset(ExpenseUiOffset).toLocalDateTime() }
        .recoverCatching { OffsetDateTime.parse(value.trim()).withOffsetSameInstant(ExpenseUiOffset).toLocalDateTime() }
        .getOrElse { fallback.atOffset(ExpenseUiOffset).toLocalDateTime() }

internal fun expenseDateToPickerMillis(date: LocalDate): Long =
    date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()

internal fun pickerMillisToExpenseDate(millis: Long): LocalDate =
    Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()

internal fun expenseOccurredAt(date: LocalDate, time: LocalTime): String =
    LocalDateTime.of(date, time).toInstant(ExpenseUiOffset).toString()

internal fun isExchangeRateStale(observedAt: String, now: Instant = Instant.now()): Boolean {
    val observed = runCatching { Instant.parse(observedAt) }
        .recoverCatching { OffsetDateTime.parse(observedAt).toInstant() }
        .getOrNull() ?: return false
    var cursor = observed
    var remainingBusinessHours = 72
    while (remainingBusinessHours > 0) {
        val day = cursor.atOffset(ZoneOffset.UTC).dayOfWeek
        cursor = cursor.plusSeconds(60 * 60)
        if (day != DayOfWeek.SATURDAY && day != DayOfWeek.SUNDAY) {
            remainingBusinessHours -= 1
        }
    }
    return cursor.isBefore(now)
}

internal fun createDefaultExpenseDraft(
    ledgerUnitId: String,
    participants: List<ExpenseFormParticipant>,
    baseCurrency: String,
    occurredAt: String = Instant.now().toString(),
    defaultPayerParticipantId: String? = null,
): ExpenseFormDraft {
    val payerId = defaultPayerParticipantId
        ?.takeIf { candidate -> participants.any { it.id == candidate } }
        ?: participants.firstOrNull()?.id
    return ExpenseFormDraft(
    ledgerUnitId = ledgerUnitId,
    title = "",
    amount = "",
    currency = baseCurrency,
    fxRate = "1",
    payerIds = payerId?.let(::listOf).orEmpty(),
    payerAmounts = emptyMap(),
    splitMethod = ExpenseSplitMethod.Aa,
    manualSplitAmounts = emptyMap(),
    aaParticipantIds = participants.map(ExpenseFormParticipant::id),
    occurredAt = occurredAt,
    note = "",
)
}

internal fun normalizedAutoPayerAmount(value: String): String? = value.trim().toBigDecimalOrNull()
    ?.takeIf { it >= BigDecimal.ZERO }
    ?.let { amount ->
        val plain = amount.toPlainString()
        if ('.' in plain) plain else "$plain.0"
    }

internal fun allocateRefundPayerAmounts(
    totalValue: String,
    payerIds: List<String>,
    payerWeights: Map<String, String>,
): Map<String, String> {
    val total = totalValue.trim().toBigDecimalOrNull()?.abs() ?: return emptyMap()
    if (payerIds.isEmpty()) return emptyMap()
    if (payerIds.size == 1) return mapOf(payerIds.single() to (normalizedAutoPayerAmount(total.toPlainString()) ?: "0.0"))
    val weights = payerIds.associateWith { payerWeights[it]?.toBigDecimalOrNull()?.abs() ?: BigDecimal.ZERO }
    val weightTotal = weights.values.sumOf { it }
    if (weightTotal <= BigDecimal.ZERO) {
        return mapOf(payerIds.first() to (normalizedAutoPayerAmount(total.toPlainString()) ?: "0.0"))
    }
    var allocated = BigDecimal.ZERO
    return payerIds.mapIndexed { index, payerId ->
        val amount = if (index == payerIds.lastIndex) {
            total - allocated
        } else {
            total.multiply(weights.getValue(payerId)).divide(weightTotal, 4, RoundingMode.DOWN).also { allocated += it }
        }
        payerId to (normalizedAutoPayerAmount(amount.toPlainString()) ?: "0.0")
    }.toMap()
}

enum class ExpenseAttachmentUploadStatus {
    Pending,
    Uploading,
    Uploaded,
    Failed,
}

data class ExpenseAttachmentDraftUiState(
    val attachmentId: String,
    val fileName: String,
    val sizeLabel: String = "",
    val status: ExpenseAttachmentUploadStatus = ExpenseAttachmentUploadStatus.Pending,
    val errorMessage: String? = null,
    val canRemove: Boolean = true,
)

internal fun canAddExpenseAttachment(currentCount: Int): Boolean = currentCount in 0 until 10

/** Stitch 原版新增消费结构，输入事实由宿主 ViewModel 校验并提交。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewExpenseScreen(
    modifier: Modifier = Modifier,
    ledgerUnitId: String = "",
    participants: List<ExpenseFormParticipant> = emptyList(),
    baseCurrency: String = "CNY",
    multiCurrencyEnabled: Boolean = false,
    currentParticipantId: String? = null,
    mode: ExpenseFormMode = ExpenseFormMode.Create,
    presentationOnly: Boolean = false,
    initialDraft: ExpenseFormDraft? = null,
    attachments: List<ExpenseAttachmentDraftUiState> = emptyList(),
    isSubmitting: Boolean = false,
    errorMessage: String? = null,
    onBack: () -> Unit = {},
    onSave: (ExpenseFormDraft) -> Unit = {},
    onRefreshConfirmation: (() -> Unit)? = null,
    onAddAttachment: (() -> Unit)? = null,
    onRemoveAttachment: ((attachmentId: String) -> Unit)? = null,
    onRetryAttachment: ((attachmentId: String) -> Unit)? = null,
    supportedCurrencies: List<SupportedExchangeCurrency> = emptyList(),
    exchangeRates: Map<String, ExchangeRate> = emptyMap(),
    onCurrencySelected: ((String) -> Unit)? = null,
    exchangeRate: String? = null,
    exchangeRateSource: String? = null,
    exchangeRateObservedAt: String? = null,
    isOffline: Boolean = false,
) {
    val safeParticipants = participants
    val seed = remember(mode, initialDraft, ledgerUnitId, safeParticipants, baseCurrency, currentParticipantId) {
        initialDraft ?: createDefaultExpenseDraft(
            ledgerUnitId = ledgerUnitId,
            participants = safeParticipants,
            baseCurrency = baseCurrency,
            defaultPayerParticipantId = currentParticipantId,
        ).let { draft -> if (mode == ExpenseFormMode.Refund) draft.copy(title = "退款") else draft }
    }
    var draft by remember(mode, seed) { mutableStateOf(seed) }
    val refundPayerWeights = remember(mode, seed) { seed.payerAmounts }
    val initialOccurredAt = remember(mode, seed) { parseExpenseOccurredAt(seed.occurredAt) }
    var selectedDate by remember(mode, seed) { mutableStateOf(initialOccurredAt.toLocalDate()) }
    var selectedTime by remember(mode, seed) { mutableStateOf(initialOccurredAt.toLocalTime().withSecond(0).withNano(0)) }
    var showDatePicker by remember { mutableStateOf(false) }
    var showTimePicker by remember { mutableStateOf(false) }
    var showCurrencyMenu by remember { mutableStateOf(false) }
    var showIconPicker by remember { mutableStateOf(false) }
    val currencyOptions = remember(supportedCurrencies, baseCurrency) {
        // Keep the activity base currency first, but do not use its code as a
        // display name. That was the source of labels such as "CNY CNY".
        (listOf(SupportedExchangeCurrency(baseCurrency, "", null)) + supportedCurrencies)
            .distinctBy { it.code.uppercase() }
    }
    val availableCurrencyOptions = remember(currencyOptions, exchangeRates, baseCurrency, draft.currency, isOffline) {
        currencyOptions.filter { currency ->
            !isOffline ||
                currency.code.equals(baseCurrency, true) ||
                currency.code.equals(draft.currency, true) ||
                exchangeRates.containsKey("${baseCurrency.uppercase()}:${currency.code.uppercase()}")
        }
    }
    val selectableCurrencyOptions = remember(availableCurrencyOptions, baseCurrency, multiCurrencyEnabled) {
        if (multiCurrencyEnabled) {
            availableCurrencyOptions
        } else {
            availableCurrencyOptions.filter { it.code.equals(baseCurrency, ignoreCase = true) }
        }
    }
    val hazeState = rememberSharedLedgerHazeState()
    val selectedExchangeRate = exchangeRates["${baseCurrency.uppercase()}:${draft.currency.uppercase()}"]
    val externalCurrency = !draft.currency.equals(baseCurrency, ignoreCase = true)
    val hasRateForSave = !externalCurrency || selectedExchangeRate != null || exchangeRate != null
    LaunchedEffect(multiCurrencyEnabled, baseCurrency, draft.currency) {
        if ((!multiCurrencyEnabled || draft.currency.equals(baseCurrency, ignoreCase = true)) && draft.fxRate != "1") {
            draft = draft.copy(currency = baseCurrency, fxRate = "1")
        }
    }
    LaunchedEffect(mode, draft.amount, draft.payerIds, currentParticipantId) {
        when (mode) {
            ExpenseFormMode.Create -> {
                val currentPayer = currentParticipantId?.takeIf { draft.payerIds == listOf(it) }
                val amountValue = normalizedAutoPayerAmount(draft.amount)
                if (currentPayer != null && amountValue != null && draft.payerAmounts[currentPayer] != amountValue) {
                    draft = draft.copy(payerAmounts = draft.payerAmounts + (currentPayer to amountValue))
                }
            }
            ExpenseFormMode.Refund -> {
                val payerIds = draft.payerIds.ifEmpty {
                    listOfNotNull(currentParticipantId ?: safeParticipants.firstOrNull()?.id)
                }
                val payerAmounts = allocateRefundPayerAmounts(draft.amount, payerIds, refundPayerWeights)
                if (draft.payerIds != payerIds || draft.payerAmounts != payerAmounts) {
                    draft = draft.copy(payerIds = payerIds, payerAmounts = payerAmounts)
                }
            }
            ExpenseFormMode.Edit -> Unit
        }
    }
    val title = when (mode) {
        ExpenseFormMode.Create -> "新增消费"
        ExpenseFormMode.Edit -> "编辑消费"
        ExpenseFormMode.Refund -> if (initialDraft?.originalExpenseId.isNullOrBlank()) "独立退款" else "添加退款"
    }
    val amount = draft.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO
    val splitTotal = when (draft.splitMethod) {
        ExpenseSplitMethod.Manual -> draft.manualSplitAmounts.values.sumOf { it.toBigDecimalOrNull() ?: BigDecimal.ZERO }
        ExpenseSplitMethod.Aa -> amount
    }
    val keypad = remember { NumericKeypadState() }
    val focusManager = LocalFocusManager.current
    val listState = rememberLazyListState()

    // A failed submit is rendered as the final list item. Clear the amount
    // field focus first so the custom keypad cannot cover the message, then
    // reveal that item with one smooth scroll. Keying this effect by the
    // message avoids re-scrolling on ordinary recompositions.
    LaunchedEffect(errorMessage) {
        if (!errorMessage.isNullOrBlank()) {
            focusManager.clearFocus(force = true)
            // The error item is added by the same recomposition that starts
            // this effect; wait for the next layout pass before reading the
            // list size, otherwise the old last-item index would be used.
            withFrameNanos { }
            val lastItemIndex = listState.layoutInfo.totalItemsCount - 1
            if (lastItemIndex >= 0) {
                listState.animateScrollToItem(lastItemIndex)
            }
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = { SharedLedgerTopBar(title = title, showBackButton = true, onBackClick = onBack, containerColor = AppBackground, showMoreButton = false, hazeState = hazeState) },
        bottomBar = {
            SharedLedgerCtaBottomBar(backgroundColor = AppBackground, hazeState = hazeState) {
                SharedLedgerPrimaryButton(
                    text = when {
                        isSubmitting -> "保存中…"
                        onRefreshConfirmation != null -> "请先刷新确认"
                        else -> "保存"
                    },
                    onClick = { if (!isSubmitting && onRefreshConfirmation == null && hasRateForSave) onSave(draft) },
                    enabled = !isSubmitting && onRefreshConfirmation == null && !isOffline && hasRateForSave,
                    icon = Icons.Rounded.Save,
                )
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
        LazyColumn(
            modifier = Modifier.widthIn(max = SharedLedgerDimens.ContentMaxWidth).fillMaxSize().sharedLedgerHazeSource(hazeState),
            state = listState,
            contentPadding = PaddingValues(SharedLedgerDimens.PageHorizontalPadding, innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium, SharedLedgerDimens.PageHorizontalPadding, innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Large),
        ) {
            item("amount") {
                FormSection {
                    if (presentationOnly) {
                        Text(
                            text = "已发生真实转账，仅可修改标题、备注等信息",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (mode != ExpenseFormMode.Refund) {
                        SharedLedgerTextField(
                            draft.title,
                            { draft = draft.copy(title = it) },
                            Modifier.fillMaxWidth(),
                            placeholder = "消费名称",
                            leadingIcon = {
                                IconButton(
                                    onClick = { showIconPicker = true },
                                    modifier = Modifier
                                        .size(SharedLedgerDimens.TopBarActionSize)
                                        .semantics {
                                            contentDescription = "选择消费图标，当前为${expenseIconLabel(draft.iconKey)}"
                                        },
                                ) {
                                    Surface(
                                        modifier = Modifier.size(SharedLedgerDimens.ActionIconContainer),
                                        shape = SharedLedgerRadius.Full,
                                        color = WarmOrangeContainer.copy(alpha = 0.85f),
                                        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                                    ) {
                                        Box(contentAlignment = Alignment.Center) {
                                            Icon(
                                                imageVector = expenseIconVector(draft.iconKey),
                                                contentDescription = null,
                                                modifier = Modifier.size(SharedLedgerDimens.ActionIcon),
                                            )
                                        }
                                    }
                                }
                            },
                        )
                    }
                    Box(modifier = Modifier.fillMaxWidth()) {
                        SharedLedgerTextField(
                            draft.amount,
                            { draft = draft.copy(amount = it) },
                            Modifier
                                .fillMaxWidth()
                                .numericKeypadTarget(keypad, { draft.amount }, { draft = draft.copy(amount = it) }),
                            placeholder = "0.0",
                            enabled = !presentationOnly,
                            readOnly = true,
                            leadingIcon = {
                                Text(currencySymbol(draft.currency), style = SharedLedgerTextStyles.CardTitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            },
                            trailingContent = {
                                Box(
                                    modifier = Modifier.padding(end = SharedLedgerSpacing.Small),
                                ) {
                                    SharedLedgerFluidCurrencyPicker(
                                        expanded = showCurrencyMenu,
                                        onExpandedChange = { showCurrencyMenu = it },
                                        currencyCodes = selectableCurrencyOptions.map { it.code },
                                        selectedCode = draft.currency,
                                        onSelected = { code ->
                                            draft = draft.copy(
                                                currency = code,
                                                fxRate = if (code.equals(baseCurrency, true)) "1" else draft.fxRate,
                                            )
                                            onCurrencySelected?.invoke(code)
                                        },
                                        enabled = mode != ExpenseFormMode.Refund && !presentationOnly,
                                    )
                                }
                            },
                        )
                    }
                    if (mode != ExpenseFormMode.Refund && multiCurrencyEnabled && !draft.currency.equals(baseCurrency, ignoreCase = true)) {
                        Text(
                            text = when {
                                (selectedExchangeRate?.rate?.toPlainString() ?: exchangeRate) != null -> {
                                    val rate = selectedExchangeRate?.rate?.toPlainString() ?: exchangeRate.orEmpty()
                                    val observedAt = selectedExchangeRate?.observedAt ?: exchangeRateObservedAt
                                    "汇率 ${draft.currency} → $baseCurrency：$rate${observedAt?.let { "（ECB ${UiDateTimeFormatter.format(it)}）" }.orEmpty()}"
                                }
                                else -> "暂无 ${draft.currency} → $baseCurrency 汇率缓存，在线保存前请刷新"
                            },
                            style = SharedLedgerTextStyles.Label,
                            color = if ((selectedExchangeRate?.source ?: exchangeRateSource) == "ECB_REFERENCE") MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error,
                        )
                        val observedAt = selectedExchangeRate?.observedAt ?: exchangeRateObservedAt
                        if (!observedAt.isNullOrBlank() && isExchangeRateStale(observedAt)) {
                            Text("ECB 参考汇率已超过 72 个工作小时，仍可在线保存", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.tertiary)
                        }
                        if (!hasRateForSave) {
                            Text("当前币对没有可用汇率缓存，只能使用基础币种", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
            if (mode != ExpenseFormMode.Refund) {
                item("payer") {
                    FormSection {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text("实际付款", Modifier.weight(1f), style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text("可多选", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.primary)
                        }
                        safeParticipants.forEachIndexed { index, participant ->
                            val selected = participant.id in draft.payerIds
                            PayerRow(participant, index, selected, draft.payerAmounts[participant.id].orEmpty(), draft.currency, keypad, {
                                val next = if (selected) draft.payerIds - participant.id else draft.payerIds + participant.id
                                val nextAmounts = if (selected) {
                                    // Deselecting a payer must not leave a visible
                                    // amount which submit validation will ignore.
                                    draft.payerAmounts - participant.id
                                } else {
                                    draft.payerAmounts + (participant.id to (draft.payerAmounts[participant.id] ?: ""))
                                }
                                draft = draft.copy(payerIds = next, payerAmounts = nextAmounts)
                            }, { value ->
                                val parsed = value.trim().toBigDecimalOrNull()
                                val hasPositiveAmount = parsed != null && parsed > BigDecimal.ZERO
                                val isSelected = participant.id in draft.payerIds
                                val nextPayerIds = if (hasPositiveAmount) {
                                    (draft.payerIds + participant.id).distinct()
                                } else {
                                    draft.payerIds
                                }
                                val nextAmounts = if (!isSelected && !hasPositiveAmount) {
                                    // An unselected row cannot retain a zero or
                                    // blank amount that would be misleading in
                                    // the form or diverge from payerIds.
                                    draft.payerAmounts - participant.id
                                } else {
                                    draft.payerAmounts + (participant.id to value)
                                }
                                draft = draft.copy(payerIds = nextPayerIds, payerAmounts = nextAmounts)
                            }, enabled = !presentationOnly)
                        }
                    }
                }
            }
            item("split") {
                FormSection {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("分摊方式", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Box(Modifier.weight(1f), contentAlignment = Alignment.CenterEnd) {
                            SegmentedControl(options = listOf("手动分摊", "AA均摊"), selectedIndex = if (draft.splitMethod == ExpenseSplitMethod.Manual) 0 else 1, onSelected = { draft = draft.copy(splitMethod = if (it == 0) ExpenseSplitMethod.Manual else ExpenseSplitMethod.Aa) }, modifier = Modifier.widthIn(max = ComponentSizes.SegmentedControlMaxWidth), enabled = !presentationOnly)
                        }
                    }
                    Surface(shape = CircleShape, color = if (splitTotal.compareTo(amount) == 0) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer) {
                        Row(Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.XSmall), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Rounded.CheckCircle, null, Modifier.size(SharedLedgerDimens.IconSmall))
                            Text("已分配 ${currencySymbol(draft.currency)} ${splitTotal.toPlainString()} / ${currencySymbol(draft.currency)} ${amount.toPlainString()}", style = SharedLedgerTextStyles.Label)
                        }
                    }
                    safeParticipants.forEachIndexed { index, participant ->
                        val participantUi = ParticipantUiModel(
                            participant.name,
                            if (participant.claimedUserId != null) AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
                            else AvatarBackground.Unbound(participant.id),
                        )
                        if (draft.splitMethod == ExpenseSplitMethod.Manual) {
                            val value = draft.manualSplitAmounts[participant.id].orEmpty()
                            ParticipantAmountRow(participantUi, value.toBigDecimalOrNull() ?: BigDecimal.ZERO, currencyCode = draft.currency, editable = !presentationOnly, editableAmount = value, onAmountChange = { draft = draft.copy(manualSplitAmounts = draft.manualSplitAmounts + (participant.id to it)) }, keypad = keypad)
                        } else {
                            val selected = participant.id in draft.aaParticipantIds
                            Surface(onClick = { draft = draft.copy(aaParticipantIds = if (selected) draft.aaParticipantIds - participant.id else draft.aaParticipantIds + participant.id) }, enabled = !presentationOnly, modifier = Modifier.fillMaxWidth(), shape = SharedLedgerRadius.Large, color = if (selected) MaterialTheme.colorScheme.primaryContainer.copy(alpha = .35f) else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .4f), border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant)) {
                                Row(Modifier.padding(SharedLedgerSpacing.Medium), verticalAlignment = Alignment.CenterVertically) {
                                    Text(participant.name, Modifier.weight(1f), style = SharedLedgerTextStyles.Body)
                                    Text(if (selected) "已选择" else "未选择", style = SharedLedgerTextStyles.Label, color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                }
            }
            if (mode != ExpenseFormMode.Refund) {
                item("details") {
                    FormSection {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.Schedule, null)
                        Surface(
                            onClick = { showDatePicker = true },
                            enabled = !presentationOnly,
                            modifier = Modifier
                                .weight(1f),
                            shape = SharedLedgerRadius.Medium,
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
                        ) {
                            Column(Modifier.padding(SharedLedgerSpacing.MediumSmall)) {
                                Text("发生时间", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(
                                    UiDateTimeFormatter.format(draft.occurredAt),
                                    style = SharedLedgerTextStyles.Body,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                        }
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
                        Icon(Icons.Rounded.EditNote, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        SharedLedgerTextField(draft.note, { draft = draft.copy(note = it) }, Modifier.weight(1f), placeholder = "添加备注（可选）", singleLine = false, minLines = 2)
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                    ) {
                        Icon(Icons.Rounded.Image, "附件", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("附件 (${attachments.size}/10)", modifier = Modifier.weight(1f), style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        onAddAttachment?.let { callback ->
                            TextButton(
                                onClick = callback,
                                enabled = canAddExpenseAttachment(attachments.size) && !isSubmitting,
                                contentPadding = PaddingValues(horizontal = SharedLedgerSpacing.Small),
                            ) {
                                Icon(Icons.Rounded.Add, contentDescription = null, modifier = Modifier.size(SharedLedgerDimens.IconSmall))
                                Text("添加")
                            }
                        }
                    }
                    if (attachments.isEmpty()) {
                        Text("暂无附件", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        attachments.forEach { attachment ->
                            ExpenseAttachmentDraftRow(
                                attachment = attachment,
                                onRemove = onRemoveAttachment?.takeIf { attachment.canRemove }?.let { callback -> { callback(attachment.attachmentId) } },
                                onRetry = onRetryAttachment?.let { callback -> { callback(attachment.attachmentId) } },
                            )
                        }
                    }
                    }
                }
            }
            if (!errorMessage.isNullOrBlank()) {
                item("error") {
                    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                        ErrorBanner(errorMessage)
                        onRefreshConfirmation?.let { callback ->
                            TextButton(onClick = callback) {
                                Icon(Icons.Rounded.Refresh, contentDescription = null)
                                Text("刷新账单后解除提交保护")
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

    if (showIconPicker) {
        ExpenseIconPickerSheet(
            selectedKey = draft.iconKey,
            onSelected = { iconKey -> draft = draft.copy(iconKey = iconKey) },
            onDismissRequest = { showIconPicker = false },
        )
    }

    if (showDatePicker) {
        val datePickerState = rememberDatePickerState(
            initialSelectedDateMillis = expenseDateToPickerMillis(selectedDate),
        )
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        datePickerState.selectedDateMillis
                            ?.let(::pickerMillisToExpenseDate)
                            ?.let { selectedDate = it }
                        showDatePicker = false
                        showTimePicker = true
                    },
                ) { Text("下一步") }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) { Text("取消") }
            },
        ) {
            DatePicker(state = datePickerState)
        }
    }

    if (showTimePicker) {
        val timePickerState = rememberTimePickerState(
            initialHour = selectedTime.hour,
            initialMinute = selectedTime.minute,
            is24Hour = true,
        )
        TimePickerDialog(
            onDismissRequest = { showTimePicker = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        selectedTime = LocalTime.of(timePickerState.hour, timePickerState.minute)
                        draft = draft.copy(occurredAt = expenseOccurredAt(selectedDate, selectedTime))
                        showTimePicker = false
                    },
                ) { Text("确定") }
            },
            title = { Text("选择发生时间") },
            dismissButton = {
                TextButton(onClick = { showTimePicker = false }) { Text("取消") }
            },
        ) {
            TimePicker(state = timePickerState)
        }
    }
}

@Composable
private fun ExpenseAttachmentDraftRow(
    attachment: ExpenseAttachmentDraftUiState,
    onRemove: (() -> Unit)?,
    onRetry: (() -> Unit)?,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.Small),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Icon(Icons.Rounded.Image, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Column(modifier = Modifier.weight(1f)) {
                Text(attachment.fileName, style = SharedLedgerTextStyles.BodySecondary)
                val statusText = when (attachment.status) {
                    ExpenseAttachmentUploadStatus.Pending -> "等待上传"
                    ExpenseAttachmentUploadStatus.Uploading -> "上传中…"
                    ExpenseAttachmentUploadStatus.Uploaded -> attachment.sizeLabel.ifBlank { "已上传" }
                    ExpenseAttachmentUploadStatus.Failed -> attachment.errorMessage ?: "上传失败"
                }
                Text(
                    statusText,
                    style = SharedLedgerTextStyles.Label,
                    color = if (attachment.status == ExpenseAttachmentUploadStatus.Failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (attachment.status == ExpenseAttachmentUploadStatus.Failed) {
                onRetry?.let { callback ->
                    IconButton(onClick = callback, modifier = Modifier.semantics { contentDescription = "重试上传${attachment.fileName}" }) {
                        Icon(Icons.Rounded.Refresh, contentDescription = null)
                    }
                }
            }
            onRemove?.let { callback ->
                IconButton(onClick = callback, modifier = Modifier.semantics { contentDescription = "移除附件${attachment.fileName}" }) {
                    Icon(Icons.Rounded.Delete, contentDescription = null)
                }
            }
        }
    }
}

@Composable
private fun PayerRow(participant: ExpenseFormParticipant, index: Int, selected: Boolean, amount: String, currency: String, keypad: NumericKeypadState, onToggle: () -> Unit, onAmountChange: (String) -> Unit, enabled: Boolean = true) {
    Surface(onClick = onToggle, enabled = enabled, modifier = Modifier.fillMaxWidth(), shape = SharedLedgerRadius.Medium, color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .52f), border = BorderStroke(SharedLedgerDimens.OutlineWidth, if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant.copy(alpha = .5f))) {
        Row(Modifier.padding(SharedLedgerSpacing.MediumSmall), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
            ParticipantAvatar(
                name = participant.name,
                background = if (participant.claimedUserId != null) AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
                else AvatarBackground.Unbound(participant.id),
                size = SharedLedgerDimens.AvatarSmall,
            )
            Text(participant.name, Modifier.weight(1f), style = SharedLedgerTextStyles.Body)
            SharedLedgerTextField(amount, onAmountChange, Modifier.widthIn(min = 82.dp, max = SharedLedgerDimens.ParticipantAmountFieldWidth).numericKeypadTarget(keypad, { amount }, onAmountChange), placeholder = MoneyFormatter.format(BigDecimal.ZERO, currency), enabled = enabled, readOnly = true)
        }
    }
}

@Composable
private fun FormSection(content: @Composable ColumnScope.() -> Unit) {
    Surface(Modifier.fillMaxWidth(), shape = SharedLedgerRadius.ExtraLarge, color = MaterialTheme.colorScheme.surface, border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant.copy(alpha = .3f)), shadowElevation = SharedLedgerElevation.Card) {
        Column(Modifier.padding(SharedLedgerSpacing.Large), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall), content = content)
    }
}

private fun currencySymbol(code: String): String = when (code.uppercase()) { "EUR" -> "€"; "USD" -> "$"; else -> "¥" }

internal fun currencyOptionLabel(currency: SupportedExchangeCurrency): String {
    val code = currency.code.uppercase()
    val displayName = currency.displayName.trim()
    return if (displayName.isBlank() || displayName.equals(code, ignoreCase = true)) {
        code
    } else {
        "$code · $displayName"
    }
}

@Preview(name = "新增消费", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun NewExpenseScreenPreview() {
    SharedLedgerTheme {
        NewExpenseScreen(
            ledgerUnitId = "preview-ledger",
            participants = PreviewParticipants,
        )
    }
}
