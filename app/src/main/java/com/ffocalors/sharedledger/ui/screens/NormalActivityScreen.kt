package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.DoneAll
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.ExpenseCard
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.components.ExpenseActionSheet
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.QuickActionItem
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerActionItemsRow
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.isTerminalActivityError
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.data.activity.ActivityDetail
import java.math.BigDecimal

private val PreviewNormalActivityParticipants = listOf(
    ParticipantUiModel("张三", IconContainerSage),
    ParticipantUiModel("李四", WarmOrangeContainer),
    ParticipantUiModel("王五"),
    ParticipantUiModel("赵六"),
    ParticipantUiModel("我"),
)

private val PreviewNormalActivityExpenses = listOf(
    ExpenseCardUiModel(
        name = "晚餐",
        amount = BigDecimal("560.0"),
        payerName = "张三",
        participantCount = 5,
        participants = PreviewNormalActivityParticipants,
        expenseId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.DINNER_EXPENSE,
    ),
    ExpenseCardUiModel(
        name = "打车",
        amount = BigDecimal("100.0"),
        payerName = "李四",
        participantCount = 5,
        participants = listOf(PreviewNormalActivityParticipants[1], PreviewNormalActivityParticipants[4]),
        expenseId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.TAXI_EXPENSE,
        isDeleted = true,
    ),
)

/**
 * 普通活动详情页。活动、参与人和账单由宿主提供，导航意图通过回调交给宿主处理。
 */
@Composable
fun NormalActivityScreen(
    activityTitle: String = "",
    participants: List<ParticipantUiModel> = emptyList(),
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
    onTransfer: (() -> Unit)? = {},
    onNewExpense: (() -> Unit)? = {},
    onRefund: (() -> Unit)? = {},
    onReceive: (() -> Unit)? = {},
    onFinalSettlement: (() -> Unit)? = null,
    onFundRecords: () -> Unit = {},
    onManageActivity: (() -> Unit)? = null,
    onExpenseClick: (String) -> Unit = {},
) {
    val displayTitle = activity?.summary?.name ?: activityTitle
    val displayParticipants = activity?.participants?.mapIndexed { index, participant ->
        ParticipantUiModel(
            name = participant.name,
            backgroundColor = if (index % 2 == 0) IconContainerSage else WarmOrangeContainer,
        )
    } ?: participants
    val displayUsers = activity?.members?.mapIndexed { index, member ->
        ParticipantUiModel(
            name = member.displayName,
            backgroundColor = if (index % 2 == 0) IconContainerSage else WarmOrangeContainer,
        )
    } ?: emptyList()
    val displayCurrency = activity?.summary?.baseCurrency ?: "CNY"
    val outstandingDebt = activity?.summary?.totalDebt?.toBigDecimalOrNull()
    var expenseActionSheetVisible by remember { mutableStateOf(false) }
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = displayTitle,
                showBackButton = true,
                onBackClick = onBack,
                onMoreClick = onManageActivity,
                containerColor = MaterialTheme.colorScheme.background,
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
            val bottomActions = listOfNotNull(
                onTransfer?.let { BottomActionItem("转账", Icons.Rounded.SwapHoriz, it) },
                if (onNewExpense != null || onRefund != null) {
                    BottomActionItem("记一笔", Icons.Rounded.Edit) {
                        expenseActionSheetVisible = true
                    }
                } else null,
                onReceive?.let { BottomActionItem("收款", Icons.Rounded.RequestQuote, it) },
            )
            if (bottomActions.isNotEmpty()) {
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
                    SharedLedgerBottomActionBar(actions = bottomActions)
                }
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
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
            ) {
                if (isLoading) {
                    item(key = "activity-state") {
                        LoadingState(message = "正在加载活动…")
                    }
                } else if (errorMessage != null) {
                    item(key = "activity-state") {
                        ErrorState(
                            message = errorMessage,
                            onRetry = if (isTerminalActivityError(errorMessage)) null else onRetry,
                        )
                    }
                } else {
                    item(key = "summary") {
                        SettlementSummaryCard(
                            title = "实际消费",
                            primaryAmount = totalBaseAmount?.takeIf { participantBound },
                            secondaryTitle = "待结算",
                            secondaryAmount = outstandingDebt,
                            currencyCode = displayCurrency,
                            statistics = listOf(
                                SettlementStatistic(
                                    "参与人",
                                    "${displayParticipants.size} 人",
                                ),
                            ),
                        )
                    }
                    item(key = "quick-actions") {
                        SharedLedgerActionItemsRow(
                            items = listOfNotNull(
                                onFinalSettlement?.let { callback ->
                                    QuickActionItem("最终结算", Icons.Rounded.DoneAll, onClick = callback)
                                },
                                QuickActionItem(
                                    "资金记录",
                                    Icons.Rounded.AccountBalanceWallet,
                                    onClick = onFundRecords,
                                ),
                            ),
                        )
                    }
                    item(key = "expenses-header") {
                        Text(
                            text = "活动明细",
                            modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall, start = SharedLedgerSpacing.XSmall),
                            style = SharedLedgerTextStyles.SectionTitle,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                    }
                    if (expenseLoading) {
                        item(key = "expenses-state") {
                            LoadingState(message = "正在加载账单…")
                        }
                    } else if (expenseErrorMessage != null) {
                        item(key = "expenses-state") {
                            ErrorState(
                                message = expenseErrorMessage,
                                onRetry = if (isTerminalActivityError(expenseErrorMessage)) null else onExpenseRetry,
                            )
                        }
                    } else if (expenses.isEmpty()) {
                        item(key = "expenses-empty") {
                            EmptyState(title = "暂无账单")
                        }
                    } else {
                        items(expenses, key = { it.expenseId.ifBlank { it.name } }) { expense ->
                            ExpenseCard(
                                expense = expense,
                                onClick = { onExpenseClick(expense.expenseId) },
                                modifier = Modifier.animateItem(),
                            )
                        }
                    }
                }
            }
        }
    }
    if (expenseActionSheetVisible) {
        ExpenseActionSheet(
            onDismiss = { expenseActionSheetVisible = false },
            onNewExpense = onNewExpense,
            onRefund = onRefund,
        )
    }
}

@Preview(name = "普通活动详情", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun NormalActivityScreenPreview() {
    SharedLedgerTheme {
        NormalActivityScreen(
            activityTitle = "周末聚餐",
            participants = PreviewNormalActivityParticipants,
            expenses = PreviewNormalActivityExpenses,
        )
    }
}
