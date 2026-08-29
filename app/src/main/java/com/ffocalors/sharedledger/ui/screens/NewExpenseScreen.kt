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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.EditNote
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.PersonAdd
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material.icons.rounded.Schedule
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.ParticipantAmountRow
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SegmentedControl
import com.ffocalors.sharedledger.ui.components.SharedLedgerPrimaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
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

private val NewExpenseParticipants = listOf(
    ParticipantUiModel("张三", IconContainerOrange),
    ParticipantUiModel("李四", IconContainerTertiary),
    ParticipantUiModel("王五", IconContainerSage),
)

/**
 * 新增消费表单。这里保留完整的本地输入状态，宿主只需要处理 [onBack] 和 [onSave]
 * 两个导航意图即可；金额分配不在这个纯 UI 原型中做校验或计算。
 */
@Composable
fun NewExpenseScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onSave: () -> Unit = {},
) {
    var expenseName by rememberSaveable { mutableStateOf("晚餐") }
    var amount by rememberSaveable { mutableStateOf("300.0") }
    var currencyCode by rememberSaveable { mutableStateOf("CNY") }
    var payers by rememberSaveable { mutableStateOf(listOf("张三", "李四")) }
    var selectedPayer by rememberSaveable { mutableStateOf("张三") }
    var splitMode by rememberSaveable { mutableIntStateOf(0) }
    var zhangAmount by rememberSaveable { mutableStateOf("80.0") }
    var liAmount by rememberSaveable { mutableStateOf("100.0") }
    var wangAmount by rememberSaveable { mutableStateOf("120.0") }
    var note by rememberSaveable { mutableStateOf("") }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            SharedLedgerTopBar(
                title = "新增消费",
                showBackButton = true,
                onBackClick = onBack,
                containerColor = AppBackground,
                onMoreClick = {},
            )
        },
        bottomBar = {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(Color.Transparent, AppBackground),
                        ),
                    )
                    .imePadding()
                    .navigationBarsPadding()
                    .padding(
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        top = SharedLedgerSpacing.XLarge,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = SharedLedgerSpacing.Large,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerPrimaryButton(
                    text = "保存",
                    onClick = onSave,
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
                modifier = Modifier
                    .fillMaxWidth()
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .imePadding(),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding() + 112.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
            ) {
                item(key = "amount") {
                    ExpenseAmountSection(
                        name = expenseName,
                        onNameChange = { expenseName = it },
                        amount = amount,
                        onAmountChange = { amount = it },
                        currencyCode = currencyCode,
                        onCurrencyToggle = {
                            currencyCode = if (currencyCode == "CNY") "EUR" else "CNY"
                        },
                    )
                }
                item(key = "payer") {
                    PayerSection(
                        payers = payers,
                        selectedPayer = selectedPayer,
                        currencyCode = currencyCode,
                        onPayerSelected = { selectedPayer = it },
                        onAddPayer = {
                            if ("王五" !in payers) payers = payers + "王五"
                        },
                    )
                }
                item(key = "split") {
                    SplitSection(
                        selectedIndex = splitMode,
                        total = amount,
                        currencyCode = currencyCode,
                        onSelected = { splitMode = it },
                        amountFor = { participant ->
                            when (participant.name) {
                                "张三" -> zhangAmount
                                "李四" -> liAmount
                                else -> wangAmount
                            }
                        },
                        onAmountChange = { participant, changed ->
                            when (participant.name) {
                                "张三" -> zhangAmount = changed
                                "李四" -> liAmount = changed
                                else -> wangAmount = changed
                            }
                        },
                    )
                }
                item(key = "details") {
                    DetailsSection(
                        note = note,
                        onNoteChange = { note = it },
                    )
                }
            }
        }
    }
}

@Composable
private fun ExpenseAmountSection(
    name: String,
    onNameChange: (String) -> Unit,
    amount: String,
    onAmountChange: (String) -> Unit,
    currencyCode: String,
    onCurrencyToggle: () -> Unit,
) {
    ExpenseSection {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Icon(
                imageVector = Icons.Rounded.Restaurant,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.size(SharedLedgerDimens.IconMedium),
            )
            SharedLedgerTextField(
                value = name,
                onValueChange = onNameChange,
                modifier = Modifier.weight(1f),
                placeholder = "消费名称",
            )
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = SharedLedgerSpacing.XSmall),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = currencySymbol(currencyCode),
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            AmountInput(
                value = amount,
                onValueChange = onAmountChange,
                modifier = Modifier.weight(1f),
            )
            Surface(
                modifier = Modifier.clickable(onClick = onCurrencyToggle),
                shape = CircleShape,
                color = MaterialTheme.colorScheme.surfaceVariant,
            ) {
                Text(
                    text = currencyCode,
                    modifier = Modifier.padding(
                        horizontal = SharedLedgerSpacing.MediumSmall,
                        vertical = SharedLedgerSpacing.XSmall,
                    ),
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun AmountInput(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.padding(horizontal = SharedLedgerSpacing.Small),
        textStyle = TextStyle(
            fontFamily = SharedLedgerTextStyles.AmountLarge.fontFamily,
            fontSize = SharedLedgerTextStyles.AmountLarge.fontSize,
            lineHeight = SharedLedgerTextStyles.AmountLarge.lineHeight,
            fontWeight = SharedLedgerTextStyles.AmountLarge.fontWeight,
            letterSpacing = SharedLedgerTextStyles.AmountLarge.letterSpacing,
            color = MaterialTheme.colorScheme.onSurface,
        ),
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
    )
}

@Composable
private fun PayerSection(
    payers: List<String>,
    selectedPayer: String,
    currencyCode: String,
    onPayerSelected: (String) -> Unit,
    onAddPayer: () -> Unit,
) {
    ExpenseSection {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "实际付款",
                modifier = Modifier.weight(1f),
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Surface(
                modifier = Modifier.clickable(onClick = onAddPayer),
                shape = CircleShape,
                color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f),
                contentColor = MaterialTheme.colorScheme.primary,
            ) {
                Row(
                    modifier = Modifier.padding(
                        horizontal = SharedLedgerSpacing.MediumSmall,
                        vertical = SharedLedgerSpacing.XSmall,
                    ),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                ) {
                    Icon(Icons.Rounded.PersonAdd, contentDescription = null, modifier = Modifier.size(16.dp))
                    Text("添加付款人", style = SharedLedgerTextStyles.Label)
                }
            }
        }
        payers.forEachIndexed { index, payer ->
            PayerRow(
                name = payer,
                amount = when (index) {
                    0 -> BigDecimal("200.0")
                    1 -> BigDecimal("100.0")
                    else -> null
                },
                currencyCode = currencyCode,
                selected = payer == selectedPayer,
                onClick = { onPayerSelected(payer) },
            )
        }
    }
}

@Composable
private fun PayerRow(
    name: String,
    amount: BigDecimal?,
    currencyCode: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = SharedLedgerRadius.Medium,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.52f),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.55f)
            else MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
        ),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            Surface(
                modifier = Modifier.size(SharedLedgerDimens.AvatarSmall),
                shape = CircleShape,
                color = when (name) {
                    "张三" -> IconContainerOrange
                    "李四" -> IconContainerTertiary
                    else -> IconContainerSage
                },
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text(name.take(1), style = SharedLedgerTextStyles.Label)
                }
            }
            Text(
                text = name,
                modifier = Modifier.weight(1f),
                style = SharedLedgerTextStyles.Body,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = amount?.let { MoneyFormatter.format(it, currencyCode) } ?: "待填写",
                style = SharedLedgerTextStyles.Body,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

@Composable
private fun SplitSection(
    selectedIndex: Int,
    total: String,
    currencyCode: String,
    onSelected: (Int) -> Unit,
    amountFor: (ParticipantUiModel) -> String,
    onAmountChange: (ParticipantUiModel, String) -> Unit,
) {
    ExpenseSection {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            Text(
                text = "分摊方式",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Box(
                modifier = Modifier.weight(1f),
                contentAlignment = Alignment.CenterEnd,
            ) {
                SegmentedControl(
                    options = listOf("手动分摊", "AA均摊"),
                    selectedIndex = selectedIndex,
                    onSelected = onSelected,
                    modifier = Modifier
                        .fillMaxWidth()
                        .widthIn(max = 172.dp),
                )
            }
        }
        SplitStatus(total = total, currencyCode = currencyCode)
        NewExpenseParticipants.forEach { participant ->
            val value = amountFor(participant)
            ParticipantAmountRow(
                participant = participant,
                amount = value.toBigDecimalOrNull() ?: BigDecimal.ZERO,
                currencyCode = currencyCode,
                editable = true,
                editableAmount = value,
                onAmountChange = { onAmountChange(participant, it) },
            )
        }
    }
}

@Composable
private fun SplitStatus(total: String, currencyCode: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            shape = CircleShape,
            color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.45f),
            contentColor = MaterialTheme.colorScheme.primary,
        ) {
            Row(
                modifier = Modifier.padding(
                    horizontal = SharedLedgerSpacing.MediumSmall,
                    vertical = SharedLedgerSpacing.XSmall,
                ),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            ) {
                Icon(Icons.Rounded.CheckCircle, contentDescription = null, modifier = Modifier.size(14.dp))
                Text(
                    text = "已分配 ${currencySymbol(currencyCode)} $total / ${currencySymbol(currencyCode)} $total",
                    style = SharedLedgerTextStyles.Label,
                )
            }
        }
    }
}

@Composable
private fun DetailsSection(
    note: String,
    onNoteChange: (String) -> Unit,
) {
    ExpenseSection {
        DetailRow(icon = { Icon(Icons.Rounded.Schedule, contentDescription = null) }) {
            Text(
                text = "今天 19:42",
                style = SharedLedgerTextStyles.Body,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
        DetailDivider()
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            Icon(
                imageVector = Icons.Rounded.EditNote,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
            )
            SharedLedgerTextField(
                value = note,
                onValueChange = onNoteChange,
                modifier = Modifier.weight(1f),
                placeholder = "添加备注（可选）",
                singleLine = false,
                minLines = 2,
            )
        }
        DetailDivider()
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            Icon(
                imageVector = Icons.Rounded.Image,
                contentDescription = "附件",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Surface(
                modifier = Modifier.size(64.dp),
                shape = SharedLedgerRadius.Medium,
                color = Color.Transparent,
                border = BorderStroke(
                    2.dp,
                    MaterialTheme.colorScheme.outlineVariant,
                ),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Rounded.Add,
                        contentDescription = "添加附件",
                        tint = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }
    }
}

@Composable
private fun DetailRow(
    icon: @Composable () -> Unit,
    content: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
    ) {
        Box(contentAlignment = Alignment.Center) { icon() }
        content()
    }
}

@Composable
private fun DetailDivider() {
    Spacer(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.surfaceVariant),
    )
}

@Composable
private fun ExpenseSection(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
        ),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            content = content,
        )
    }
}

private fun currencySymbol(currencyCode: String): String = when (currencyCode) {
    "EUR" -> "€"
    else -> "¥"
}

@Preview(name = "新增消费", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun NewExpenseScreenPreview() {
    SharedLedgerTheme {
        NewExpenseScreen()
    }
}
