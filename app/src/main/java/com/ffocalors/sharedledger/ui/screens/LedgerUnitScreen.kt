package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.ExpenseCard
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.components.PaymentStatusCard
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.Cream
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import java.math.BigDecimal
import com.ffocalors.sharedledger.data.activity.ActivityDetail

private val PreviewLedgerUnitParticipants = listOf(
    ParticipantUiModel("张三", IconContainerSage),
    ParticipantUiModel("李四", WarmOrangeContainer),
    ParticipantUiModel("王五"),
)

private val PreviewTicketLedgerUnitExpenses = listOf(
    ExpenseCardUiModel(
        name = "东京塔门票",
        amount = BigDecimal("120.0"),
        payerName = "张三",
        participantCount = 3,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.TICKET_EXPENSE,
    ),
    ExpenseCardUiModel(
        name = "浅草寺导览",
        amount = BigDecimal("850.0"),
        payerName = "李四",
        participantCount = 3,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = "demo-expense-asakusa",
    ),
    ExpenseCardUiModel(
        name = "迪士尼快速通票",
        amount = BigDecimal("1200.0"),
        payerName = "我",
        participantCount = 2,
        participants = listOf(PreviewLedgerUnitParticipants[0], PreviewLedgerUnitParticipants[2]),
        currencyCode = "CNY",
        expenseId = "demo-expense-disney",
    ),
)

private val PreviewBreakfastLedgerUnitExpenses = listOf(
    ExpenseCardUiModel(
        name = "酒店早餐",
        amount = BigDecimal("320.0"),
        payerName = "张三",
        participantCount = 5,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = "demo-expense-breakfast",
    ),
    ExpenseCardUiModel(
        name = "咖啡",
        amount = BigDecimal("80.0"),
        payerName = "李四",
        participantCount = 2,
        participants = PreviewLedgerUnitParticipants.take(2),
        currencyCode = "CNY",
        expenseId = "demo-expense-coffee",
    ),
)

private val PreviewHotelLedgerUnitExpenses = listOf(
    ExpenseCardUiModel(
        name = "酒店房费",
        amount = BigDecimal("3200.0"),
        payerName = "张三",
        participantCount = 4,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = "demo-expense-hotel",
    ),
    ExpenseCardUiModel(
        name = "城市税",
        amount = BigDecimal("160.0"),
        payerName = "王五",
        participantCount = 4,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = "demo-expense-city-tax",
    ),
)

private data class LedgerUnitPreviewData(
    val title: String,
    val expenses: List<ExpenseCardUiModel>,
)

private fun ledgerUnitPreviewData(ledgerUnitId: String): LedgerUnitPreviewData = when (ledgerUnitId) {
    com.ffocalors.sharedledger.ui.demo.DemoRouteIds.BREAKFAST_LEDGER ->
        LedgerUnitPreviewData("早餐", PreviewBreakfastLedgerUnitExpenses)
    com.ffocalors.sharedledger.ui.demo.DemoRouteIds.HOTEL_LEDGER ->
        LedgerUnitPreviewData("酒店", PreviewHotelLedgerUnitExpenses)
    else -> LedgerUnitPreviewData("门票", PreviewTicketLedgerUnitExpenses)
}

/** Stable presentation helper used by navigation/model tests to verify ledger-unit identity. */
internal fun ledgerUnitDemoTitle(ledgerUnitId: String): String = ledgerUnitPreviewData(ledgerUnitId).title

/**
 * 大型活动中的独立 Ledger，页面内容由 [ledgerUnitId] 选择，导航意图通过回调交给宿主处理。
 */
@Composable
fun LedgerUnitScreen(
    activityId: String = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.LARGE_ACTIVITY,
    ledgerUnitId: String = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.TICKET_LEDGER,
    ledgerUnitTitle: String? = null,
    activity: ActivityDetail? = null,
    isLoading: Boolean = false,
    errorMessage: String? = null,
    expenses: List<ExpenseCardUiModel> = emptyList(),
    totalBaseAmount: BigDecimal? = null,
    participantBound: Boolean = false,
    expenseLoading: Boolean = false,
    expenseErrorMessage: String? = null,
    onExpenseRetry: () -> Unit = {},
    onRetry: () -> Unit = {},
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onTransfer: () -> Unit = {},
    onNewExpense: () -> Unit = {},
    onReceive: () -> Unit = {},
    onFundRecords: () -> Unit = {},
    onExpenseClick: (String) -> Unit = {},
    previewMode: Boolean = false,
) {
    val previewData = ledgerUnitPreviewData(ledgerUnitId)
    val displayTitle = ledgerUnitTitle?.takeIf { it.isNotBlank() }
        ?: activity?.ledgerUnits?.firstOrNull { it.id == ledgerUnitId }?.name
        ?: if (previewMode) previewData.title else "子活动"
    val displayTotal = if (previewMode) previewData.expenses.sumOf { it.amount } else totalBaseAmount
    val displayUsers = activity?.members?.mapIndexed { index, member ->
        ParticipantUiModel(
            name = member.displayName,
            backgroundColor = if (index % 2 == 0) IconContainerSage else WarmOrangeContainer,
        )
    } ?: emptyList()
    Scaffold(
        modifier = modifier.fillMaxSize(),
        // Stitch’s LedgerUnit frame uses the warm cream layer outside the cards.
        containerColor = Cream,
        topBar = {
            SharedLedgerTopBar(
                title = displayTitle,
                showBackButton = true,
                onBackClick = onBack,
                containerColor = Cream,
                businessAction = {
                    ParticipantAvatarGroup(
                        participants = displayUsers,
                        maxVisible = 2,
                        avatarSize = SharedLedgerDimens.AvatarSmall,
                        modifier = Modifier.padding(end = SharedLedgerSpacing.Small),
                    )
                },
            )
        },
        bottomBar = {
            Box(
                modifier = Modifier
                    .navigationBarsPadding()
                    .padding(
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        top = SharedLedgerSpacing.Medium,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = SharedLedgerSpacing.Large,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerBottomActionBar(
                    actions = listOf(
                        BottomActionItem("转账", Icons.Rounded.SwapHoriz, onTransfer),
                        BottomActionItem("记一笔", Icons.Rounded.Add, onNewExpense),
                        BottomActionItem("收款", Icons.Rounded.RequestQuote, onReceive),
                    ),
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
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Medium,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                if (isLoading || errorMessage != null || expenseLoading || expenseErrorMessage != null) {
                    item(key = "ledger-state") {
                        LedgerUnitStateMessage(
                            isLoading = isLoading || expenseLoading,
                            errorMessage = errorMessage ?: expenseErrorMessage,
                            onRetry = if (errorMessage != null) onRetry else onExpenseRetry,
                        )
                    }
                } else {
                    item(key = "summary") {
                        SettlementSummaryCard(
                            title = if (previewMode) "消费合计" else "我的应承担合计",
                            primaryAmount = displayTotal?.takeIf { previewMode || participantBound },
                            currencyCode = activity?.summary?.baseCurrency ?: "CNY",
                            statistics = emptyList(),
                            statusContent = {
                                Column(
                                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
                                ) {
                                    HorizontalDivider(
                                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f),
                                    )
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = "待结算",
                                            style = SharedLedgerTextStyles.BodySecondary,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                        Text(
                                            text = "活动 / $displayTitle",
                                            style = SharedLedgerTextStyles.BodySecondary,
                                            color = MaterialTheme.colorScheme.onSurface,
                                        )
                                    }
                                }
                            },
                        )
                    }
                    item(key = "fund-records") {
                        SharedLedgerButton(
                            text = "资金记录",
                            onClick = onFundRecords,
                            tone = SharedLedgerButtonTone.Neutral,
                            icon = Icons.Rounded.History,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    item(key = "my-status") {
                        PaymentStatusCard(
                            title = "账务状态将在下一阶段接入",
                            amount = BigDecimal.ZERO,
                        )
                    }
                    item(key = "today") {
                        if (previewMode) {
                            LedgerUnitExpenseSection(
                                title = "今天",
                                expenses = previewData.expenses.take(2),
                                onExpenseClick = onExpenseClick,
                            )
                        } else {
                            LedgerUnitExpenseSection(
                                title = "今天",
                                expenses = expenses,
                                onExpenseClick = onExpenseClick,
                            )
                        }
                    }
                    item(key = "yesterday") {
                        if (previewMode) {
                            LedgerUnitExpenseSection(
                                title = "昨天",
                                expenses = previewData.expenses.drop(2),
                                onExpenseClick = onExpenseClick,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LedgerUnitStateMessage(
    isLoading: Boolean,
    errorMessage: String?,
    onRetry: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = SharedLedgerSpacing.XLarge),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        if (isLoading) {
            androidx.compose.material3.CircularProgressIndicator()
            Text("正在加载子活动…", style = SharedLedgerTextStyles.BodySecondary)
        } else {
            Text(errorMessage ?: "子活动加载失败", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.error)
            SharedLedgerButton(
                text = "重试",
                onClick = onRetry,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Composable
private fun LedgerUnitExpenseSection(
    title: String,
    expenses: List<ExpenseCardUiModel>,
    onExpenseClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Text(
            text = title,
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onBackground,
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.XSmall),
        )
        if (expenses.isEmpty()) {
            Text("暂无账单", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            expenses.forEach { expense ->
                ExpenseCard(
                    expense = expense,
                    icon = Icons.AutoMirrored.Rounded.ReceiptLong,
                    onClick = { onExpenseClick(expense.expenseId) },
                )
            }
        }
    }
}

@Preview(name = "子活动详情", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LedgerUnitScreenPreview() {
    SharedLedgerTheme {
        LedgerUnitScreen(previewMode = true)
    }
}
