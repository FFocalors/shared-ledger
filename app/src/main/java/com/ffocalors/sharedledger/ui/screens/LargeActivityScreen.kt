package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
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
import androidx.compose.material.icons.rounded.CurrencyExchange
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.AddSubActivityButton
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.QuickActionItem
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerActionItemsRow
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.SubActivityCard
import com.ffocalors.sharedledger.ui.components.SubActivityUiModel
import com.ffocalors.sharedledger.ui.components.isTerminalActivityError
import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.ui.demo.DemoData
import com.ffocalors.sharedledger.ui.theme.IconContainerNeutralTint
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconContainerTertiary
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SubActivityBreakfastContainer
import com.ffocalors.sharedledger.ui.theme.WarmBrown
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
 * Detail screen for a large activity. Activity data is supplied by the host;
 * callbacks carry navigation and write intents back to the host.
 */
@Composable
fun LargeActivityScreen(
    activityTitle: String = "",
    participants: List<ParticipantUiModel> = emptyList(),
    subActivities: List<SubActivityUiModel> = emptyList(),
    activity: ActivityDetail? = null,
    ledgerUnitAmounts: Map<String, BigDecimal> = emptyMap(),
    participantBound: Boolean? = null,
    isLoading: Boolean = false,
    errorMessage: String? = null,
    onRetry: () -> Unit = {},
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onSubActivityClick: (id: String) -> Unit = {},
    onAddSubActivity: (() -> Unit)? = {},
    onFinalSettlement: (() -> Unit)? = {},
    onTransfer: (() -> Unit)? = {},
    onRefund: (() -> Unit)? = {},
    onReceive: (() -> Unit)? = {},
    onFundRecords: () -> Unit = {},
    onShowPrepayment: (() -> Unit)? = null,
    onManageActivity: (() -> Unit)? = null,
) {
    val displayTitle = activity?.summary?.name ?: activityTitle
    val displayParticipants = activity?.participants?.map { participant ->
        ParticipantUiModel(
            name = participant.name,
            avatarBackground = if (participant.claimedUserId != null) AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
            else AvatarBackground.Unbound(participant.id),
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
    val actualConsumption = ledgerUnitAmounts.values.sumOf { it }
    val displaySubActivities = activity?.ledgerUnits?.mapIndexed { index, ledgerUnit ->
        val icon = when (ledgerUnit.type.lowercase()) {
            "meal", "breakfast", "dining" -> Icons.Rounded.Restaurant
            "hotel", "lodging" -> Icons.Rounded.Hotel
            else -> Icons.AutoMirrored.Rounded.ReceiptLong
        }
        SubActivityUiModel(
            name = ledgerUnit.name,
            amount = ledgerUnitAmounts[ledgerUnit.id] ?: BigDecimal.ZERO,
            participantCount = null,
            updatedAt = ledgerUnit.createdAt?.let(UiDateTimeFormatter::format) ?: "已创建",
            icon = icon,
            currencyCode = displayCurrency,
            iconContainerColor = if (index % 2 == 0) IconContainerSage else IconContainerTertiary,
            iconTint = if (index % 2 == 0) SageGreen else IconContainerNeutralTint,
            ledgerUnitId = ledgerUnit.id,
            amountAvailable = participantBound == true && ledgerUnitAmounts.containsKey(ledgerUnit.id),
        )
    } ?: subActivities
    val outstandingDebt = activity?.summary?.totalDebt?.toBigDecimalOrNull()
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
                onShowPrepayment?.let { BottomActionItem("预存", Icons.Rounded.AccountBalanceWallet, it) },
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
                    item(key = "summary") {
                        SettlementSummaryCard(
                            title = "实际消费",
                            primaryAmount = actualConsumption.takeIf { participantBound == true },
                            secondaryTitle = "待结算",
                            secondaryAmount = outstandingDebt,
                            currencyCode = displayCurrency,
                            statistics = listOf(
                                SettlementStatistic("包含", "${displaySubActivities.size} 项活动"),
                                SettlementStatistic("参与者", "${displayParticipants.size} 人"),
                            ),
                        )
                    }
                    item(key = "quick-actions") {
                        SharedLedgerActionItemsRow(
                            items = listOfNotNull(
                                onRefund?.let { callback ->
                                    QuickActionItem("退款", Icons.Rounded.CurrencyExchange, onClick = callback)
                                },
                                onFinalSettlement?.let { callback ->
                                    QuickActionItem("最终结算", Icons.Rounded.DoneAll, onClick = callback)
                                },
                                QuickActionItem("资金记录", Icons.Rounded.AccountBalanceWallet, onClick = onFundRecords),
                            ),
                            modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall),
                        )
                    }
                    item(key = "sub-activities-header") {
                        Text(
                            text = "子活动列表",
                            modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall, start = SharedLedgerSpacing.XSmall),
                            style = SharedLedgerTextStyles.SectionTitle,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                    }
                    if (displaySubActivities.isEmpty()) {
                        item(key = "sub-activities-empty") {
                            EmptyState(title = "暂无子活动")
                        }
                    } else {
                        items(displaySubActivities, key = { it.ledgerUnitId.ifBlank { it.name } }) { activity ->
                            SubActivityCard(
                                activity = activity,
                                onClick = { onSubActivityClick(activity.ledgerUnitId) },
                                modifier = Modifier.animateItem(),
                            )
                        }
                    }
                    onAddSubActivity?.let { callback ->
                        item(key = "add-sub-activity") {
                            AddSubActivityButton(onClick = callback)
                        }
                    }
                }
            }
        }
    }

}

@Preview(name = "大型活动详情页", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LargeActivityScreenPreview() {
    SharedLedgerTheme {
        LargeActivityScreen(
            activityTitle = "日本旅行",
            participants = LargeActivityParticipants,
            subActivities = LargeActivitySubActivities,
        )
    }
}
