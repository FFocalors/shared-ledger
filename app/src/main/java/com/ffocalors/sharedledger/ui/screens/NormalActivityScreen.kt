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
import androidx.compose.material.icons.rounded.LocalTaxi
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.ExpenseCard
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.components.PaymentStatusCard
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
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
import java.math.BigDecimal

private val NormalActivityParticipants = listOf(
    ParticipantUiModel("张三", IconContainerSage),
    ParticipantUiModel("李四", WarmOrangeContainer),
    ParticipantUiModel("王五"),
    ParticipantUiModel("赵六"),
    ParticipantUiModel("我"),
)

private val NormalActivityExpenses = listOf(
    ExpenseCardUiModel(
        name = "晚餐",
        amount = BigDecimal("560.0"),
        payerName = "张三",
        participantCount = 5,
        participants = NormalActivityParticipants,
    ),
    ExpenseCardUiModel(
        name = "打车",
        amount = BigDecimal("100.0"),
        payerName = "李四",
        participantCount = 5,
        participants = listOf(NormalActivityParticipants[1], NormalActivityParticipants[4]),
    ),
)

/**
 * 普通活动详情页。页面只负责展示 Demo 账目，并把导航意图交给宿主处理。
 */
@Composable
fun NormalActivityScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onTransfer: () -> Unit = {},
    onNewExpense: () -> Unit = {},
    onReceive: () -> Unit = {},
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "周末聚餐",
                showBackButton = true,
                onBackClick = onBack,
                containerColor = MaterialTheme.colorScheme.background,
                businessAction = {
                    Icon(
                        imageVector = Icons.Rounded.Group,
                        contentDescription = "参与成员",
                        modifier = Modifier
                            .size(SharedLedgerDimens.TopBarActionSize)
                            .padding(SharedLedgerSpacing.Small),
                        tint = MaterialTheme.colorScheme.onSurface,
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
                        BottomActionItem("记一笔", Icons.Rounded.Edit, onNewExpense),
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
                item(key = "summary") {
                    SettlementSummaryCard(
                        title = "当前待结算",
                        primaryAmount = BigDecimal("320.0"),
                        statistics = listOf(
                            // The empty leading column preserves Stitch's right-aligned total.
                            SettlementStatistic("", ""),
                            SettlementStatistic(
                                "总消费",
                                MoneyFormatter.format(BigDecimal("860.0"), "CNY"),
                            ),
                        ),
                    )
                }
                item(key = "my-status") {
                    PaymentStatusCard(
                        title = "你需要支付给 张三",
                        amount = BigDecimal("120.0"),
                    )
                }
                item(key = "expenses") {
                    ExpenseTimeline(
                        expenses = NormalActivityExpenses,
                    )
                }
            }
        }
    }
}

@Composable
private fun ExpenseTimeline(
    expenses: List<ExpenseCardUiModel>,
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
        TimelineDateHeader()
        expenses.forEachIndexed { index, expense ->
            TimelineExpense(
                expense = expense,
                icon = if (index == 0) Icons.Rounded.Restaurant else Icons.Rounded.LocalTaxi,
            )
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
        NormalActivityScreen()
    }
}
