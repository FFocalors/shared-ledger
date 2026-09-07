package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.material.icons.rounded.Hotel
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.Restaurant
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
import com.ffocalors.sharedledger.ui.components.AddSubActivityButton
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
import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.ui.demo.DemoData
import com.ffocalors.sharedledger.ui.theme.IconContainerNeutralTint
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconContainerTertiary
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SubActivityBreakfastContainer
import com.ffocalors.sharedledger.ui.theme.WarmBrown
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter
import java.math.BigDecimal

private const val BreakfastId = "demo-breakfast"
private const val TicketId = "demo-ticket"
private const val HotelId = "demo-hotel"

private val LargeActivityParticipants = DemoData.japanTravel.participants

private val LargeActivitySubActivities = listOf(
    SubActivityUiModel(
        name = "早餐",
        amount = BigDecimal("320.0"),
        participantCount = 5,
        updatedAt = "已更新",
        icon = Icons.Rounded.Restaurant,
        iconContainerColor = SubActivityBreakfastContainer,
        iconTint = WarmBrown,
        ledgerUnitId = BreakfastId,
    ),
    SubActivityUiModel(
        name = "门票",
        amount = BigDecimal("300"),
        participantCount = 6,
        updatedAt = "今天 09:30",
        icon = Icons.AutoMirrored.Rounded.ReceiptLong,
        currencyCode = "EUR",
        iconContainerColor = IconContainerSage,
        iconTint = SageGreen,
        ledgerUnitId = TicketId,
    ),
    SubActivityUiModel(
        name = "酒店",
        amount = BigDecimal("3200.0"),
        participantCount = 4,
        updatedAt = "昨天",
        icon = Icons.Rounded.Hotel,
        iconContainerColor = IconContainerTertiary,
        iconTint = IconContainerNeutralTint,
        ledgerUnitId = HotelId,
    ),
)

/**
 * Detail screen for a large activity. The callbacks intentionally contain no
 * navigation or accounting logic, keeping this screen reusable for the V0.1
 * static prototype and ready for the host Navigation graph to wire up.
 */
@Composable
fun LargeActivityScreen(
    activityTitle: String = "日本旅行",
    participants: List<ParticipantUiModel> = LargeActivityParticipants,
    subActivities: List<SubActivityUiModel> = LargeActivitySubActivities,
    activity: ActivityDetail? = null,
    ledgerUnitAmounts: Map<String, BigDecimal> = emptyMap(),
    participantBound: Boolean? = null,
    isLoading: Boolean = false,
    errorMessage: String? = null,
    onRetry: () -> Unit = {},
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onSubActivityClick: (id: String) -> Unit = {},
    onAddSubActivity: () -> Unit = {},
    onFinalSettlement: () -> Unit = {},
    onTransfer: () -> Unit = {},
    onReceive: () -> Unit = {},
    onFundRecords: () -> Unit = {},
    onShowPrepayment: (() -> Unit)? = null,
    onManageActivity: (() -> Unit)? = null,
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
    val displaySubActivities = activity?.ledgerUnits?.mapIndexed { index, ledgerUnit ->
        val icon = when (ledgerUnit.type.lowercase()) {
            "meal", "breakfast", "dining" -> Icons.Rounded.Restaurant
            "hotel", "lodging" -> Icons.Rounded.Hotel
            else -> Icons.AutoMirrored.Rounded.ReceiptLong
        }
        SubActivityUiModel(
            name = ledgerUnit.name,
            amount = ledgerUnitAmounts[ledgerUnit.id] ?: BigDecimal.ZERO,
            participantCount = displayParticipants.size,
            updatedAt = ledgerUnit.createdAt?.let(UiDateTimeFormatter::format) ?: "已创建",
            icon = icon,
            currencyCode = displayCurrency,
            iconContainerColor = if (index % 2 == 0) IconContainerSage else IconContainerTertiary,
            iconTint = if (index % 2 == 0) SageGreen else IconContainerNeutralTint,
            ledgerUnitId = ledgerUnit.id,
            amountAvailable = participantBound ?: false,
        )
    } ?: subActivities
    val outstandingDebt = activity?.summary?.totalDebt?.toBigDecimalOrNull() ?: BigDecimal("2480.0")

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
                        start = SharedLedgerSpacing.Medium,
                        top = SharedLedgerSpacing.Medium,
                        end = SharedLedgerSpacing.Medium,
                        bottom = SharedLedgerSpacing.Large,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerBottomActionBar(
                    actions = listOf(
                        BottomActionItem("转账", Icons.Rounded.SwapHoriz, onTransfer),
                        BottomActionItem("预存", Icons.Rounded.AccountBalanceWallet, onShowPrepayment ?: {}),
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
                if (isLoading || errorMessage != null) {
                    item(key = "activity-state") {
                        LargeActivityStateMessage(
                            isLoading = isLoading,
                            errorMessage = errorMessage,
                            onRetry = onRetry,
                        )
                    }
                } else {
                    item(key = "summary") {
                        SettlementSummaryCard(
                            title = "当前待结算",
                            primaryAmount = outstandingDebt,
                            currencyCode = displayCurrency,
                            statistics = listOf(
                                SettlementStatistic("包含", "${displaySubActivities.size} 项活动"),
                                SettlementStatistic("参与者", "${displayParticipants.size} 人"),
                            ),
                        )
                    }
                    item(key = "quick-actions") {
                        SharedLedgerActionItemsRow(
                            items = listOf(
                                QuickActionItem("查看总体结算", Icons.Rounded.Analytics, onClick = onFinalSettlement),
                                QuickActionItem("最终结算", Icons.Rounded.DoneAll, onClick = onFinalSettlement),
                                QuickActionItem("资金记录", Icons.Rounded.AccountBalanceWallet, onClick = onFundRecords),
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
                    items(displaySubActivities, key = { it.ledgerUnitId.ifBlank { it.name } }) { activity ->
                        SubActivityCard(
                            activity = activity,
                            onClick = { onSubActivityClick(activity.ledgerUnitId) },
                        )
                    }
                    item(key = "add-sub-activity") {
                        AddSubActivityButton(
                            onClick = onAddSubActivity,
                            modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                        )
                    }
                }
            }
        }
    }

}

@Composable
private fun LargeActivityStateMessage(
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
            com.ffocalors.sharedledger.ui.components.SharedLedgerButton(
                text = "重试",
                onClick = onRetry,
                tone = com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Preview(name = "大型活动详情页", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LargeActivityScreenPreview() {
    SharedLedgerTheme {
        LargeActivityScreen()
    }
}
