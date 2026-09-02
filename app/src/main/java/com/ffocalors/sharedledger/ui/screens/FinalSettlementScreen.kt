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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
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

data class FinalSettlementRequest(
    val activityId: String,
    val previewItemId: String,
    val fromParticipantId: String,
    val toParticipantId: String,
    val amount: BigDecimal,
    val currency: String,
    val ordinaryAmount: BigDecimal,
    val prepaymentReturnAmount: BigDecimal,
    val sourceFinancialVersion: Long,
)

/** Request contract shared by the demo host and a future create/execute RPC adapter. */
fun FinalSettlementRequest.isValid(): Boolean =
    activityId.isNotBlank() &&
        previewItemId.isNotBlank() &&
        fromParticipantId.isNotBlank() &&
        toParticipantId.isNotBlank() &&
        fromParticipantId != toParticipantId &&
        amount > BigDecimal.ZERO &&
        currency.length == 3 &&
        currency == currency.uppercase() &&
        ordinaryAmount >= BigDecimal.ZERO &&
        prepaymentReturnAmount >= BigDecimal.ZERO &&
        ordinaryAmount + prepaymentReturnAmount == amount &&
        sourceFinancialVersion >= 1L

private data class SettlementSuggestion(
    val id: String,
    val fromParticipantId: String,
    val toParticipantId: String,
    val from: ParticipantUiModel,
    val to: ParticipantUiModel,
    val amount: BigDecimal,
    val currency: String,
    val ordinaryAmount: BigDecimal,
    val prepaymentReturnAmount: BigDecimal,
    val sourceFinancialVersion: Long,
)

private fun SettlementSuggestion.toRequest(activityId: String): FinalSettlementRequest =
    FinalSettlementRequest(
        activityId = activityId,
        previewItemId = id,
        fromParticipantId = fromParticipantId,
        toParticipantId = toParticipantId,
        amount = amount,
        currency = currency,
        ordinaryAmount = ordinaryAmount,
        prepaymentReturnAmount = prepaymentReturnAmount,
        sourceFinancialVersion = sourceFinancialVersion,
    )

private val SettlementSuggestions = listOf(
    SettlementSuggestion(
        id = "zhang-san-wang-wu",
        fromParticipantId = "fake-alice",
        toParticipantId = "fake-bob",
        from = ParticipantUiModel("张三", IconContainerSage),
        to = ParticipantUiModel("王五"),
        amount = BigDecimal("320.0"),
        currency = "CNY",
        ordinaryAmount = BigDecimal("320.0"),
        prepaymentReturnAmount = BigDecimal.ZERO,
        sourceFinancialVersion = 12L,
    ),
    SettlementSuggestion(
        id = "li-si-zhao-liu",
        fromParticipantId = "fake-bob",
        toParticipantId = "fake-carol",
        from = ParticipantUiModel("李四", IconContainerOrange),
        to = ParticipantUiModel("赵六"),
        amount = BigDecimal("180.0"),
        currency = "CNY",
        ordinaryAmount = BigDecimal("180.0"),
        prepaymentReturnAmount = BigDecimal.ZERO,
        sourceFinancialVersion = 12L,
    ),
    SettlementSuggestion(
        id = "wang-wu-zhang-san",
        fromParticipantId = "fake-carol",
        toParticipantId = "fake-alice",
        from = ParticipantUiModel("王五"),
        to = ParticipantUiModel("张三", IconContainerSage),
        amount = BigDecimal("60.0"),
        currency = "CNY",
        ordinaryAmount = BigDecimal("60.0"),
        prepaymentReturnAmount = BigDecimal.ZERO,
        sourceFinancialVersion = 12L,
    ),
)

private val DepositReturn = SettlementSuggestion(
    id = "zhang-san-li-si-return",
    fromParticipantId = "fake-alice",
    toParticipantId = "fake-bob",
    from = ParticipantUiModel("张三", IconContainerSage),
    to = ParticipantUiModel("李四", IconContainerOrange),
    amount = BigDecimal("200.0"),
    currency = "CNY",
    ordinaryAmount = BigDecimal.ZERO,
    prepaymentReturnAmount = BigDecimal("200.0"),
    sourceFinancialVersion = 12L,
)

/**
 * Large-activity settlement review. Each execution emits a complete request; the host owns
 * persistence and can later replace the handler with the create/execute settlement RPC.
 */
@Composable
fun FinalSettlementScreen(
    activityId: String = "demo-large",
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onFinalize: ((FinalSettlementRequest) -> Unit)? = null,
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "共享账本",
                showBackButton = onBack != null,
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
                item(key = "demo-boundary") {
                    Text(
                        text = "演示 · 活动：$activityId",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                    SettlementSuggestionCard(
                        suggestion = suggestion,
                        onExecute = onFinalize?.let { callback -> { callback(suggestion.toRequest(activityId)) } },
                    )
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
                    SettlementSuggestionCard(
                        suggestion = DepositReturn,
                        onExecute = onFinalize?.let { callback -> { callback(DepositReturn.toRequest(activityId)) } },
                    )
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
    onExecute: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
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
            if (onExecute == null) {
                SuggestionBadge("演示建议")
            } else {
                TextButton(onClick = onExecute) { Text("执行") }
            }
        }
    }
}

@Composable
private fun SuggestionBadge(text: String) {
    Surface(
        shape = SharedLedgerRadius.Full,
        color = SurfaceWarmLow,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.Small),
            style = SharedLedgerTextStyles.Label,
        )
    }
}

@Preview(name = "大型活动最终结算", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun FinalSettlementScreenPreview() {
    SharedLedgerTheme {
        FinalSettlementScreen()
    }
}
