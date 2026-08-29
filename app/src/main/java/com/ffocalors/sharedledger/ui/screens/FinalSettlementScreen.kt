package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SharedLedgerSecondaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.WarningCard
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmHigh
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLow
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.WarmBrown
import java.math.BigDecimal

private data class SettlementSuggestion(
    val id: String,
    val from: ParticipantUiModel,
    val to: ParticipantUiModel,
    val amount: BigDecimal,
    val actionLabel: String,
    val filledAction: Boolean = true,
)

private val SettlementSuggestions = listOf(
    SettlementSuggestion(
        id = "zhang-san-wang-wu",
        from = ParticipantUiModel("张三", IconContainerSage),
        to = ParticipantUiModel("王五"),
        amount = BigDecimal("320.0"),
        actionLabel = "记录已支付",
    ),
    SettlementSuggestion(
        id = "li-si-zhao-liu",
        from = ParticipantUiModel("李四", IconContainerOrange),
        to = ParticipantUiModel("赵六"),
        amount = BigDecimal("180.0"),
        actionLabel = "记录已支付",
    ),
    SettlementSuggestion(
        id = "wang-wu-zhang-san",
        from = ParticipantUiModel("王五"),
        to = ParticipantUiModel("张三", IconContainerSage),
        amount = BigDecimal("60.0"),
        actionLabel = "记录已支付",
    ),
)

private val DepositReturn = SettlementSuggestion(
    id = "zhang-san-li-si-return",
    from = ParticipantUiModel("张三", IconContainerSage),
    to = ParticipantUiModel("李四", IconContainerOrange),
    amount = BigDecimal("200.0"),
    actionLabel = "记录返还",
    filledAction = false,
)

/**
 * Large-activity settlement review. This is a local UI demo: recording an item only changes its
 * button state and never creates a real transfer or calculates a settlement.
 */
@Composable
fun FinalSettlementScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "共享账本",
                showBackButton = true,
                onBackClick = onBack,
                containerColor = MaterialTheme.colorScheme.background,
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .navigationBarsPadding()
                .imePadding()
                .padding(innerPadding),
            contentAlignment = Alignment.TopCenter,
        ) {
            LazyColumn(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = SharedLedgerSpacing.Large,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = SharedLedgerSpacing.XLarge,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                item(key = "header") {
                    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                        Text(
                            text = "最终结算",
                            style = SharedLedgerTextStyles.PageTitle,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = "根据当前全部未结账目计算",
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                item(key = "warning") {
                    WarningCard(
                        title = "请仔细核对",
                        text = "当前存在 1 条有争议的转账记录，请在结算前仔细核对。",
                    )
                }
                item(key = "suggested-header") {
                    SettlementSectionHeader(
                        title = "建议转账 (3笔)",
                        status = "待处理",
                    )
                }
                items(
                    items = SettlementSuggestions,
                    key = { it.id },
                ) { suggestion ->
                    SettlementSuggestionCard(suggestion = suggestion)
                }
                item(key = "returns-header") {
                    Text(
                        text = "预存返还",
                        style = SharedLedgerTextStyles.CardTitle,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                    )
                }
                item(key = DepositReturn.id) {
                    SettlementSuggestionCard(suggestion = DepositReturn)
                }
            }
        }
    }
}

@Composable
private fun SettlementSectionHeader(
    title: String,
    status: String,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = title,
            style = SharedLedgerTextStyles.CardTitle,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Surface(
            shape = SharedLedgerRadius.Full,
            color = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
        ) {
            Text(
                text = status,
                modifier = Modifier.padding(
                    horizontal = SharedLedgerSpacing.MediumSmall,
                    vertical = SharedLedgerSpacing.XSmall,
                ),
                style = SharedLedgerTextStyles.Label,
            )
        }
    }
}

@Composable
private fun SettlementSuggestionCard(
    suggestion: SettlementSuggestion,
    modifier: Modifier = Modifier,
) {
    var recorded by rememberSaveable { mutableStateOf(false) }
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        color = SurfaceWarmLowest,
        shadowElevation = SharedLedgerElevation.Card,
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant,
        ),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Row(
                modifier = Modifier.weight(1f),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            ) {
                ParticipantAvatar(
                    name = suggestion.from.name,
                    backgroundColor = SurfaceWarmHigh,
                    size = SharedLedgerDimens.AvatarMedium,
                )
                Icon(
                    imageVector = Icons.AutoMirrored.Rounded.ArrowForward,
                    contentDescription = "转给",
                    modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                ParticipantAvatar(
                    name = suggestion.to.name,
                    backgroundColor = SurfaceWarmHigh,
                    size = SharedLedgerDimens.AvatarMedium,
                )
                AmountDisplay(
                    amount = suggestion.amount,
                    currencyCode = "CNY",
                    fractionDigitsOverride = 1,
                    size = AmountSize.Small,
                    modifier = Modifier.padding(start = SharedLedgerSpacing.XSmall),
                )
            }
            if (recorded) {
                Surface(
                    shape = SharedLedgerRadius.Full,
                    color = SurfaceWarmLow,
                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                ) {
                    Text(
                        text = "已记录",
                        modifier = Modifier.padding(
                            horizontal = SharedLedgerSpacing.MediumSmall,
                            vertical = SharedLedgerSpacing.Small,
                        ),
                        style = SharedLedgerTextStyles.Label,
                    )
                }
            } else if (suggestion.filledAction) {
                Button(
                    onClick = { recorded = true },
                    modifier = Modifier.width(104.dp),
                    shape = SharedLedgerRadius.Full,
                    contentPadding = PaddingValues(horizontal = SharedLedgerSpacing.Small),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = MaterialTheme.colorScheme.onPrimary,
                    ),
                ) {
                    Text(text = suggestion.actionLabel, style = SharedLedgerTextStyles.Label)
                }
            } else {
                SharedLedgerSecondaryButton(
                    text = suggestion.actionLabel,
                    onClick = { recorded = true },
                    modifier = Modifier.width(104.dp),
                )
            }
        }
    }
}

@Preview(name = "大型活动最终结算", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun FinalSettlementScreenPreview() {
    SharedLedgerTheme {
        FinalSettlementScreen()
    }
}
