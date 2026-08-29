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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Group
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
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.Cream
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import java.math.BigDecimal

private val LedgerUnitParticipants = listOf(
    ParticipantUiModel("张三", IconContainerSage),
    ParticipantUiModel("李四", WarmOrangeContainer),
    ParticipantUiModel("王五"),
)

private val LedgerUnitExpenses = listOf(
    ExpenseCardUiModel(
        name = "东京塔门票",
        amount = BigDecimal("120.0"),
        payerName = "张三",
        participantCount = 3,
        participants = LedgerUnitParticipants,
        currencyCode = "CNY",
    ),
    ExpenseCardUiModel(
        name = "浅草寺导览",
        amount = BigDecimal("850.0"),
        payerName = "李四",
        participantCount = 3,
        participants = LedgerUnitParticipants,
        currencyCode = "CNY",
    ),
    ExpenseCardUiModel(
        name = "迪士尼快速通票",
        amount = BigDecimal("1200.0"),
        payerName = "我",
        participantCount = 2,
        participants = listOf(LedgerUnitParticipants[0], LedgerUnitParticipants[2]),
        currencyCode = "CNY",
    ),
)

/**
 * 门票子活动详情。它是大型活动中的一个独立 Ledger，导航意图通过回调交给宿主处理。
 */
@Composable
fun LedgerUnitScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onTransfer: () -> Unit = {},
    onNewExpense: () -> Unit = {},
    onReceive: () -> Unit = {},
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        // Stitch’s LedgerUnit frame uses the warm cream layer outside the cards.
        containerColor = Cream,
        topBar = {
            SharedLedgerTopBar(
                title = "门票",
                showBackButton = true,
                onBackClick = onBack,
                modifier = Modifier.statusBarsPadding(),
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
                item(key = "summary") {
                    SettlementSummaryCard(
                        title = "消费合计",
                        primaryAmount = BigDecimal("2450.0"),
                        currencyCode = "CNY",
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
                                        text = "日本旅行 / 门票",
                                        style = SharedLedgerTextStyles.BodySecondary,
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                }
                            }
                        },
                    )
                }
                item(key = "my-status") {
                    PaymentStatusCard(
                        title = "你需要支付给 张三",
                        amount = BigDecimal("120.0"),
                    )
                }
                item(key = "today") {
                    LedgerUnitExpenseSection(
                        title = "今天",
                        expenses = LedgerUnitExpenses.take(2),
                    )
                }
                item(key = "yesterday") {
                    LedgerUnitExpenseSection(
                        title = "昨天",
                        expenses = LedgerUnitExpenses.drop(2),
                    )
                }
            }
        }
    }
}

@Composable
private fun LedgerUnitExpenseSection(
    title: String,
    expenses: List<ExpenseCardUiModel>,
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
        expenses.forEach { expense ->
            ExpenseCard(
                expense = expense,
                icon = Icons.AutoMirrored.Rounded.ReceiptLong,
            )
        }
    }
}

@Preview(name = "子活动详情", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LedgerUnitScreenPreview() {
    SharedLedgerTheme {
        LedgerUnitScreen()
    }
}
