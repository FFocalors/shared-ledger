package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.EditNote
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material.icons.rounded.Schedule
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.expense.ExpenseSplitMethod
import com.ffocalors.sharedledger.ui.components.ParticipantAmountRow
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SegmentedControl
import com.ffocalors.sharedledger.ui.components.SharedLedgerPrimaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.expense.ExpenseFormDraft
import com.ffocalors.sharedledger.ui.expense.ExpenseFormMode
import com.ffocalors.sharedledger.ui.expense.ExpenseFormParticipant
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconContainerTertiary
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import java.math.BigDecimal
import java.time.Instant

private val PreviewParticipants = listOf(
    ExpenseFormParticipant("demo-zhang", "张三"),
    ExpenseFormParticipant("demo-li", "李四"),
    ExpenseFormParticipant("demo-wang", "王五"),
)

internal fun createDefaultExpenseDraft(
    ledgerUnitId: String,
    participants: List<ExpenseFormParticipant>,
    baseCurrency: String,
    occurredAt: String = Instant.now().toString(),
) = ExpenseFormDraft(
    ledgerUnitId = ledgerUnitId,
    title = "晚餐",
    amount = "300.0",
    currency = baseCurrency,
    fxRate = "1",
    payerIds = participants.firstOrNull()?.id?.let(::listOf).orEmpty(),
    payerAmounts = participants.firstOrNull()?.id?.let { mapOf(it to "300.0") }.orEmpty(),
    splitMethod = ExpenseSplitMethod.Aa,
    manualSplitAmounts = emptyMap(),
    aaParticipantIds = participants.map(ExpenseFormParticipant::id),
    occurredAt = occurredAt,
    note = "",
)

/** Stitch 原版新增消费结构，输入事实由宿主 ViewModel 校验并提交。 */
@Composable
fun NewExpenseScreen(
    modifier: Modifier = Modifier,
    ledgerUnitId: String = "",
    participants: List<ExpenseFormParticipant> = PreviewParticipants,
    baseCurrency: String = "CNY",
    multiCurrencyEnabled: Boolean = false,
    mode: ExpenseFormMode = ExpenseFormMode.Create,
    initialDraft: ExpenseFormDraft? = null,
    isSubmitting: Boolean = false,
    errorMessage: String? = null,
    onBack: () -> Unit = {},
    onSave: (ExpenseFormDraft) -> Unit = {},
) {
    val safeParticipants = if (participants.isEmpty() && ledgerUnitId.isBlank()) PreviewParticipants else participants
    val seed = remember(mode, initialDraft, ledgerUnitId, safeParticipants, baseCurrency) {
        initialDraft ?: createDefaultExpenseDraft(ledgerUnitId, safeParticipants, baseCurrency)
    }
    var draft by remember(mode, seed) { mutableStateOf(seed) }
    LaunchedEffect(multiCurrencyEnabled, baseCurrency, draft.currency) {
        if ((!multiCurrencyEnabled || draft.currency.equals(baseCurrency, ignoreCase = true)) && draft.fxRate != "1") {
            draft = draft.copy(currency = baseCurrency, fxRate = "1")
        }
    }
    val title = when (mode) {
        ExpenseFormMode.Create -> "新增消费"
        ExpenseFormMode.Edit -> "编辑消费"
        ExpenseFormMode.Refund -> "添加退款"
    }
    val amount = draft.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO
    val splitTotal = when (draft.splitMethod) {
        ExpenseSplitMethod.Manual -> draft.manualSplitAmounts.values.sumOf { it.toBigDecimalOrNull() ?: BigDecimal.ZERO }
        ExpenseSplitMethod.Aa -> amount
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = { SharedLedgerTopBar(title = title, showBackButton = true, onBackClick = onBack, containerColor = AppBackground, showMoreButton = false) },
        bottomBar = {
            Box(
                modifier = Modifier.fillMaxWidth().background(Brush.verticalGradient(listOf(Color.Transparent, AppBackground)))
                    .imePadding().navigationBarsPadding().padding(SharedLedgerDimens.PageHorizontalPadding, SharedLedgerSpacing.XLarge, SharedLedgerDimens.PageHorizontalPadding, SharedLedgerSpacing.Large),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerPrimaryButton(text = if (isSubmitting) "保存中…" else "保存", onClick = { if (!isSubmitting) onSave(draft) }, icon = Icons.Rounded.Save)
            }
        },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().widthIn(max = SharedLedgerDimens.ContentMaxWidth).imePadding(),
            contentPadding = PaddingValues(SharedLedgerDimens.PageHorizontalPadding, innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium, SharedLedgerDimens.PageHorizontalPadding, innerPadding.calculateBottomPadding() + 112.dp),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
        ) {
            item("amount") {
                FormSection {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                        Icon(Icons.Rounded.Restaurant, null, tint = MaterialTheme.colorScheme.secondary, modifier = Modifier.size(SharedLedgerDimens.IconMedium))
                        SharedLedgerTextField(draft.title, { draft = draft.copy(title = it) }, Modifier.weight(1f), placeholder = "消费名称")
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(currencySymbol(draft.currency), style = SharedLedgerTextStyles.CardTitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        SharedLedgerTextField(draft.amount, { draft = draft.copy(amount = it) }, Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                        if (multiCurrencyEnabled) {
                            SharedLedgerTextField(
                                value = draft.currency,
                                onValueChange = { value ->
                                    val code = value.filter(Char::isLetter).uppercase().take(3)
                                    draft = draft.copy(
                                        currency = code,
                                        fxRate = if (code.equals(baseCurrency, ignoreCase = true)) "1" else draft.fxRate,
                                    )
                                },
                                modifier = Modifier.widthIn(min = 76.dp, max = 92.dp),
                                label = "币种",
                            )
                        } else {
                            Surface(shape = CircleShape, color = MaterialTheme.colorScheme.surfaceVariant) {
                                Text(baseCurrency, Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.XSmall), style = SharedLedgerTextStyles.Label)
                            }
                        }
                    }
                    if (multiCurrencyEnabled && !draft.currency.equals(baseCurrency, ignoreCase = true)) {
                        SharedLedgerTextField(draft.fxRate, { draft = draft.copy(fxRate = it) }, Modifier.fillMaxWidth(), label = "汇率（${draft.currency} → $baseCurrency）", keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                    }
                }
            }
            item("payer") {
                FormSection {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("实际付款", Modifier.weight(1f), style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("可多选", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.primary)
                    }
                    safeParticipants.forEachIndexed { index, participant ->
                        val selected = participant.id in draft.payerIds
                        PayerRow(participant, index, selected, draft.payerAmounts[participant.id].orEmpty(), draft.currency, {
                            val next = if (selected) draft.payerIds - participant.id else draft.payerIds + participant.id
                            draft = draft.copy(payerIds = next, payerAmounts = draft.payerAmounts + (participant.id to (draft.payerAmounts[participant.id] ?: "0")))
                        }, { draft = draft.copy(payerAmounts = draft.payerAmounts + (participant.id to it)) })
                    }
                }
            }
            item("split") {
                FormSection {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("分摊方式", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Box(Modifier.weight(1f), contentAlignment = Alignment.CenterEnd) {
                            SegmentedControl(options = listOf("手动分摊", "AA均摊"), selectedIndex = if (draft.splitMethod == ExpenseSplitMethod.Manual) 0 else 1, onSelected = { draft = draft.copy(splitMethod = if (it == 0) ExpenseSplitMethod.Manual else ExpenseSplitMethod.Aa) }, modifier = Modifier.widthIn(max = 172.dp))
                        }
                    }
                    Surface(shape = CircleShape, color = if (splitTotal.compareTo(amount) == 0) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer) {
                        Row(Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.XSmall), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Rounded.CheckCircle, null, Modifier.size(14.dp))
                            Text("已分配 ${currencySymbol(draft.currency)} ${splitTotal.toPlainString()} / ${currencySymbol(draft.currency)} ${amount.toPlainString()}", style = SharedLedgerTextStyles.Label)
                        }
                    }
                    safeParticipants.forEachIndexed { index, participant ->
                        val participantUi = ParticipantUiModel(participant.name, participantColor(index))
                        if (draft.splitMethod == ExpenseSplitMethod.Manual) {
                            val value = draft.manualSplitAmounts[participant.id].orEmpty()
                            ParticipantAmountRow(participantUi, value.toBigDecimalOrNull() ?: BigDecimal.ZERO, currencyCode = draft.currency, editable = true, editableAmount = value, onAmountChange = { draft = draft.copy(manualSplitAmounts = draft.manualSplitAmounts + (participant.id to it)) })
                        } else {
                            val selected = participant.id in draft.aaParticipantIds
                            Surface(Modifier.fillMaxWidth().clickable { draft = draft.copy(aaParticipantIds = if (selected) draft.aaParticipantIds - participant.id else draft.aaParticipantIds + participant.id) }, shape = SharedLedgerRadius.Large, color = if (selected) MaterialTheme.colorScheme.primaryContainer.copy(alpha = .35f) else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .4f), border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant)) {
                                Row(Modifier.padding(SharedLedgerSpacing.Medium), verticalAlignment = Alignment.CenterVertically) {
                                    Text(participant.name, Modifier.weight(1f), style = SharedLedgerTextStyles.Body)
                                    Text(if (selected) "已选择" else "未选择", style = SharedLedgerTextStyles.Label, color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                }
            }
            item("details") {
                FormSection {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.Schedule, null)
                        SharedLedgerTextField(draft.occurredAt, { draft = draft.copy(occurredAt = it) }, Modifier.weight(1f), label = "发生时间（ISO-8601）")
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
                        Icon(Icons.Rounded.EditNote, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        SharedLedgerTextField(draft.note, { draft = draft.copy(note = it) }, Modifier.weight(1f), placeholder = "添加备注（可选）", singleLine = false, minLines = 2)
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
                        Icon(Icons.Rounded.Image, "附件", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("附件将在后续版本接入", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Surface(Modifier.size(48.dp), shape = SharedLedgerRadius.Medium, color = Color.Transparent, border = BorderStroke(2.dp, MaterialTheme.colorScheme.outlineVariant)) { Box(contentAlignment = Alignment.Center) { Icon(Icons.Rounded.Add, "添加附件", tint = MaterialTheme.colorScheme.outline) } }
                    }
                }
            }
            if (!errorMessage.isNullOrBlank()) item("error") { Text(errorMessage, color = MaterialTheme.colorScheme.error, style = SharedLedgerTextStyles.BodySecondary) }
        }
    }
}

@Composable
private fun PayerRow(participant: ExpenseFormParticipant, index: Int, selected: Boolean, amount: String, currency: String, onToggle: () -> Unit, onAmountChange: (String) -> Unit) {
    Surface(Modifier.fillMaxWidth().clickable(onClick = onToggle), shape = SharedLedgerRadius.Medium, color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .52f), border = BorderStroke(SharedLedgerDimens.OutlineWidth, if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant.copy(alpha = .5f))) {
        Row(Modifier.padding(SharedLedgerSpacing.MediumSmall), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
            Surface(Modifier.size(SharedLedgerDimens.AvatarSmall), CircleShape, participantColor(index)) { Box(contentAlignment = Alignment.Center) { Text(participant.name.take(1), style = SharedLedgerTextStyles.Label) } }
            Text(participant.name, Modifier.weight(1f), style = SharedLedgerTextStyles.Body)
            SharedLedgerTextField(amount, onAmountChange, Modifier.widthIn(min = 82.dp, max = 104.dp), placeholder = MoneyFormatter.format(BigDecimal.ZERO, currency), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
        }
    }
}

@Composable
private fun FormSection(content: @Composable ColumnScope.() -> Unit) {
    Surface(Modifier.fillMaxWidth(), shape = SharedLedgerRadius.ExtraLarge, color = MaterialTheme.colorScheme.surface, border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant.copy(alpha = .3f)), shadowElevation = SharedLedgerElevation.Card) {
        Column(Modifier.padding(SharedLedgerSpacing.Large), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium), content = content)
    }
}

private fun participantColor(index: Int): Color = when (index % 3) { 0 -> IconContainerOrange; 1 -> IconContainerTertiary; else -> IconContainerSage }
private fun currencySymbol(code: String): String = when (code.uppercase()) { "EUR" -> "€"; "USD" -> "$"; else -> "¥" }

@Preview(name = "新增消费", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun NewExpenseScreenPreview() { SharedLedgerTheme { NewExpenseScreen() } }
