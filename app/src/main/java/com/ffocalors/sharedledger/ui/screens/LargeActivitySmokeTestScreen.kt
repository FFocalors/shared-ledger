package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.Analytics
import androidx.compose.material.icons.rounded.DoneAll
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Hotel
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.QuickActionItem
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerActionItemsRow
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.SubActivityCard
import com.ffocalors.sharedledger.ui.components.SubActivityUiModel
import com.ffocalors.sharedledger.ui.components.AddSubActivityButton
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconContainerNeutralTint
import com.ffocalors.sharedledger.ui.theme.IconContainerTertiary
import com.ffocalors.sharedledger.ui.theme.SubActivityBreakfastContainer
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.WarmBrown
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import java.math.BigDecimal

private val SmokeTestParticipants = listOf(
    ParticipantUiModel("林"),
    ParticipantUiModel("周"),
    ParticipantUiModel("陈"),
    ParticipantUiModel("赵"),
    ParticipantUiModel("王"),
    ParticipantUiModel("李"),
)

private val SmokeTestSubActivities = listOf(
    SubActivityUiModel(
        name = "早餐",
        amount = BigDecimal("320.0"),
        participantCount = 5,
        updatedAt = "已更新",
        icon = Icons.Rounded.Restaurant,
        iconContainerColor = SubActivityBreakfastContainer,
        iconTint = WarmBrown,
    ),
    SubActivityUiModel(
        name = "门票",
        amount = BigDecimal("300"),
        participantCount = 6,
        updatedAt = "今天 09:30",
        icon = Icons.AutoMirrored.Rounded.ReceiptLong,
        currencyCode = "EUR",
        fractionDigitsOverride = 0,
        iconContainerColor = IconContainerSage,
        iconTint = SageGreen,
    ),
    SubActivityUiModel(
        name = "酒店",
        amount = BigDecimal("3200.0"),
        participantCount = 4,
        updatedAt = "昨天",
        icon = Icons.Rounded.Hotel,
        iconContainerColor = IconContainerTertiary,
        iconTint = IconContainerNeutralTint,
    ),
)

@Composable
fun LargeActivitySmokeTestScreen(
    modifier: Modifier = Modifier,
    onBackClick: () -> Unit = {},
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "日本旅行",
                showBackButton = true,
                onBackClick = onBackClick,
                containerColor = MaterialTheme.colorScheme.background,
                businessAction = {
                    ParticipantAvatarGroup(
                        participants = SmokeTestParticipants,
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
                        start = SharedLedgerSpacing.Medium,
                        top = SharedLedgerSpacing.Medium,
                        end = SharedLedgerSpacing.Medium,
                        bottom = SharedLedgerSpacing.Large,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerBottomActionBar(
                    actions = listOf(
                        BottomActionItem("转账", Icons.Rounded.SwapHoriz, {}),
                        BottomActionItem("预存", Icons.Rounded.AccountBalanceWallet, {}),
                        BottomActionItem("收款", Icons.Rounded.RequestQuote, {}),
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
                    .fillMaxWidth()
                    .fillMaxHeight(),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding(),
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
            item(key = "summary") {
                SettlementSummaryCard(
                    title = "当前待结算",
                    primaryAmount = BigDecimal("2480.0"),
                    statistics = listOf(
                        SettlementStatistic("总消费", MoneyFormatter.format(BigDecimal("5980.0"))),
                        SettlementStatistic("包含", "3 项活动"),
                        SettlementStatistic("参与者", "6 人"),
                    ),
                )
            }
            item(key = "quick-actions") {
                SharedLedgerActionItemsRow(
                    items = listOf(
                        QuickActionItem("查看总体结算", Icons.Rounded.Analytics),
                        QuickActionItem("最终结算", Icons.Rounded.DoneAll),
                        QuickActionItem("预存记录", Icons.Rounded.History),
                    ),
                    modifier = Modifier.padding(top = SharedLedgerSpacing.Medium),
                )
            }
            item(key = "sub-activities-header") {
                Text(
                    text = "子活动列表",
                    modifier = Modifier.padding(top = SharedLedgerSpacing.Large, start = SharedLedgerSpacing.XSmall),
                    style = SharedLedgerTextStyles.SectionTitle,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            items(SmokeTestSubActivities, key = { it.name }) { activity ->
                SubActivityCard(activity = activity, onClick = {})
            }
            item(key = "add-sub-activity") {
                AddSubActivityButton(
                    onClick = {},
                    modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                )
            }
            }
        }
    }
}

@Preview(name = "大型活动详情页", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LargeActivitySmokeTestScreenPreview() {
    SharedLedgerTheme {
        LargeActivitySmokeTestScreen()
    }
}
