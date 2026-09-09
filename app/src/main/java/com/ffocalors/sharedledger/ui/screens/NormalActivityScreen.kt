package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CalendarToday
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.LocalTaxi
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.CurrencyExchange
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.ExpenseCard
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.components.ExpenseActionSheet
import com.ffocalors.sharedledger.ui.components.PaymentStatusCard
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.DividerSubtle
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.ui.expense.ExpenseListUiState
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
    val outstandingDebt = activity?.summary?.totalDebt?.toBigDecimalOrNull() ?: BigDecimal.ZERO
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
                        onTransfer?.let { BottomActionItem("转账", Icons.Rounded.SwapHoriz, it) },
                        if (onNewExpense != null || onRefund != null) {
                            BottomActionItem("记一笔", Icons.Rounded.Edit) {
                                expenseActionSheetVisible = true
                            }
                        } else null,
                        onReceive?.let { BottomActionItem("收款", Icons.Rounded.RequestQuote, it) },
                    ).filterNotNull(),
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
                    item(key = "activity-state") {
                        ActivityDetailStateMessage(
                            isLoading = isLoading || expenseLoading,
                            errorMessage = errorMessage ?: expenseErrorMessage,
                            onRetry = if (errorMessage != null) onRetry else onExpenseRetry,
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
                    item(key = "fund-records") {
                        SharedLedgerButton(
                            text = "资金记录",
                            onClick = onFundRecords,
                            tone = SharedLedgerButtonTone.Neutral,
                            icon = Icons.Rounded.History,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    item(key = "expenses") {
                        ExpenseTimeline(
                            expenses = expenses,
                            onExpenseClick = onExpenseClick,
                        )
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

@Composable
private fun ActivityDetailStateMessage(
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
            Text("正在加载活动…", style = SharedLedgerTextStyles.BodySecondary)
        } else {
            Text(
                text = errorMessage ?: "活动加载失败",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.error,
            )
            SharedLedgerButton(
                text = "重试",
                onClick = onRetry,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Composable
private fun ExpenseTimeline(
    expenses: List<ExpenseCardUiModel>,
    onExpenseClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Text(
            text = "活动明细",
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.XSmall),
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Spacer(Modifier.height(SharedLedgerSpacing.Medium))
        if (expenses.isEmpty()) {
            Text("暂无账单", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            TimelineDateHeader()
            expenses.forEachIndexed { index, expense ->
                TimelineExpense(
                    expense = expense,
                    icon = if (index == 0) Icons.Rounded.Restaurant else Icons.Rounded.LocalTaxi,
                    onClick = { onExpenseClick(expense.expenseId) },
                )
            }
        }
    }
}

@Composable
private fun TimelineDateHeader(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
    ) {
        Surface(
            modifier = Modifier.size(SharedLedgerDimens.AvatarMedium),
            shape = SharedLedgerRadius.Full,
            color = MaterialTheme.colorScheme.surfaceVariant,
            border = BorderStroke(SharedLedgerDimens.AvatarBorder, AppBackground),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    imageVector = Icons.Rounded.CalendarToday,
                    contentDescription = null,
                    modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Surface(
            shape = SharedLedgerRadius.Full,
            color = MaterialTheme.colorScheme.surfaceVariant,
            tonalElevation = SharedLedgerElevation.Card,
        ) {
            Text(
                text = "今天",
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

@Composable
private fun TimelineExpense(
    expense: ExpenseCardUiModel,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .width(SharedLedgerDimens.AvatarMedium)
                .height(132.dp),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .width(1.dp)
                    .fillMaxHeight()
                    .background(DividerSubtle.copy(alpha = 0.8f)),
            )
        }
        ExpenseCard(
            expense = expense,
            icon = icon,
            onClick = onClick,
            modifier = Modifier
                .weight(1f)
                .padding(vertical = SharedLedgerSpacing.Small),
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
