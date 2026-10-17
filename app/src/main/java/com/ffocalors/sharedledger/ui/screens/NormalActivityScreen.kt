package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import com.ffocalors.sharedledger.ui.components.ExpenseCardSkeleton
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.components.ExpenseActionSheet
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.ParticipantSetupPrompt
import com.ffocalors.sharedledger.ui.components.QuickActionItem
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerActionItemsRow
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerDialog
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.isTerminalActivityError
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.data.activity.ActivityDetail
import java.math.BigDecimal

private val PreviewNormalActivityParticipants = listOf(
    ParticipantUiModel("张三", AvatarBackground.Bound("sage")),
    ParticipantUiModel("李四", AvatarBackground.Bound("terracotta")),
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
    onAddParticipants: (() -> Unit)? = null,
    onExpenseClick: (String) -> Unit = {},
) {
    val displayTitle = activity?.summary?.name ?: activityTitle
    val displayParticipants = activity?.participants?.map { participant ->
        ParticipantUiModel(
            name = participant.name,
            avatarBackground = if (participant.claimedUserId != null) {
                AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
            } else {
                AvatarBackground.Unbound(participant.id)
            },
        )
    } ?: participants
    val displayUsers = activity?.members?.map { member ->
        val identity = member.claimedParticipantId?.let { id -> activity.participants.firstOrNull { it.id == id } }
        ParticipantUiModel(
            name = identity?.name ?: member.displayName,
            avatarBackground = AvatarBackground.Bound(member.avatarStyle, member.userId),
        )
    } ?: emptyList()
    val displayCurrency = activity?.summary?.baseCurrency ?: "CNY"
    val outstandingDebt = activity?.summary?.totalDebt?.toBigDecimalOrNull()
    val needsParticipants = activity != null && activity.participants.isEmpty() && activity.summary.archivedAt == null
    var expenseActionSheetVisible by remember { mutableStateOf(false) }
    var participantRequiredDialogVisible by remember { mutableStateOf(false) }
    val hazeState = rememberSharedLedgerHazeState()
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = displayTitle,
                showBackButton = true,
                onBackClick = onBack,
                hazeState = hazeState,
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
                        if (needsParticipants) {
                            participantRequiredDialogVisible = true
                        } else {
                            expenseActionSheetVisible = true
                        }
                    }
                } else null,
                onReceive?.let { BottomActionItem("收款", Icons.Rounded.RequestQuote, it) },
            )
            if (bottomActions.isNotEmpty()) {
                SharedLedgerBottomActionBar(
                    actions = bottomActions,
                    backgroundColor = MaterialTheme.colorScheme.background,
                    hazeState = hazeState,
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
                    .fillMaxSize()
                    .sharedLedgerHazeSource(hazeState),
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
                    if (needsParticipants) {
                        item(key = "participant-setup") {
                            if (onAddParticipants != null) {
                                ParticipantSetupPrompt(
                                    title = "先添加参与人",
                                    description = "账单要记在参与人名下。添加一起分摊的人后，就能记账、转账和结算。",
                                    actionLabel = "添加参与人",
                                    onAction = onAddParticipants,
                                    modifier = Modifier.animateItem(),
                                )
                            } else {
                                ParticipantSetupPrompt(
                                    title = "等待添加参与人",
                                    description = "创建者添加参与人后，你就可以选择自己的身份并开始记账。",
                                    modifier = Modifier.animateItem(),
                                )
                            }
                        }
                    }
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
                        items(4, key = { "expense-skeleton-$it" }) {
                            ExpenseCardSkeleton(modifier = Modifier.animateItem())
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
                            EmptyState(
                                title = "暂无账单明细",
                                description = if (needsParticipants) {
                                    "添加参与人后，账单会显示在这里。"
                                } else {
                                    "点击底部“记一笔”记录当前活动的消费或退款。"
                                },
                            )
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
    if (participantRequiredDialogVisible) {
        if (onAddParticipants != null) SharedLedgerDialog(
            onDismiss = { participantRequiredDialogVisible = false },
            title = "先添加参与人",
            text = "付款人和分摊人都要从参与人中选。添加参与人后就能记账。",
            confirmText = "添加参与人",
            onConfirm = {
                participantRequiredDialogVisible = false
                onAddParticipants()
            },
            dismissText = "取消",
        ) else SharedLedgerDialog(
            onDismiss = { participantRequiredDialogVisible = false },
            title = "还不能记账",
            text = "活动还没有参与人。创建者添加参与人后，你就可以记账。",
            confirmText = "知道了",
            onConfirm = { participantRequiredDialogVisible = false },
            dismissText = null,
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
