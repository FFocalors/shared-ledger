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
import androidx.compose.foundation.layout.statusBarsPadding
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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.AddSubActivityButton
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.QuickActionItem
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerActionItemsRow
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerSecondaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.SubActivityCard
import com.ffocalors.sharedledger.ui.components.SubActivityUiModel
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
import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import java.math.BigDecimal

private const val BreakfastId = "demo-breakfast"
private const val TicketId = "demo-ticket"
private const val HotelId = "demo-hotel"

private val LargeActivityParticipants = listOf(
    ParticipantUiModel("林"),
    ParticipantUiModel("周"),
    ParticipantUiModel("陈"),
    ParticipantUiModel("赵"),
    ParticipantUiModel("王"),
    ParticipantUiModel("李"),
)

private val LargeActivitySubActivities = listOf(
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

/**
 * Detail screen for a large activity. The callbacks intentionally contain no
 * navigation or accounting logic, keeping this screen reusable for the V0.1
 * static prototype and ready for the host Navigation graph to wire up.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LargeActivityScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onSubActivityClick: (id: String) -> Unit = {},
    onFinalSettlement: () -> Unit = {},
    onTransfer: () -> Unit = {},
    onReceive: () -> Unit = {},
    onShowPrepayment: () -> Unit = {},
) {
    var showPrepaymentSheet by remember { mutableStateOf(false) }
    val prepaymentSheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "日本旅行",
                showBackButton = true,
                onBackClick = onBack,
                modifier = Modifier.statusBarsPadding(),
                businessAction = {
                    ParticipantAvatarGroup(
                        participants = LargeActivityParticipants,
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
                        BottomActionItem(
                            "预存",
                            Icons.Rounded.AccountBalanceWallet,
                            onClick = {
                                onShowPrepayment()
                                showPrepaymentSheet = true
                            },
                        ),
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
                            QuickActionItem("最终结算", Icons.Rounded.DoneAll, onClick = onFinalSettlement),
                            QuickActionItem(
                                "预存记录",
                                Icons.Rounded.History,
                                onClick = {
                                    onShowPrepayment()
                                    showPrepaymentSheet = true
                                },
                            ),
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
                items(LargeActivitySubActivities, key = { it.name }) { activity ->
                    SubActivityCard(
                        activity = activity,
                        onClick = {
                            onSubActivityClick(
                                when (activity.name) {
                                    "早餐" -> BreakfastId
                                    "门票" -> TicketId
                                    else -> HotelId
                                },
                            )
                        },
                    )
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

    if (showPrepaymentSheet) {
        ModalBottomSheet(
            onDismissRequest = { showPrepaymentSheet = false },
            sheetState = prepaymentSheetState,
        ) {
            PrepaymentSheetContent()
        }
    }
}

@Composable
private fun PrepaymentSheetContent() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(
                start = SharedLedgerDimens.PageHorizontalPadding,
                end = SharedLedgerDimens.PageHorizontalPadding,
                bottom = SharedLedgerSpacing.Large,
            ),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Text(
            text = "预存记录",
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius.Large,
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
        ) {
            Row(
                modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "当前预存",
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    AmountDisplay(
                        amount = BigDecimal("700.0"),
                        size = AmountSize.Medium,
                        emphasis = AmountEmphasis.Primary,
                    )
                }
                Text(
                    text = "张三",
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        SharedLedgerSecondaryButton(
            text = "追加预存",
            onClick = {},
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Preview(name = "大型活动详情页", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LargeActivityScreenPreview() {
    SharedLedgerTheme {
        LargeActivityScreen()
    }
}
