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
import androidx.compose.foundation.lazy.LazyRow
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
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
    val onBehalfOfParticipantId: String? = null,
)

/** Request contract passed from the settlement form to the host write flow. */
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
        sourceFinancialVersion >= 0L

data class FinalSettlementSuggestionUi(
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
    val onBehalfOptions: List<FinalSettlementParticipantOption> = emptyList(),
    val onBehalfRequired: Boolean = false,
)

data class FinalSettlementParticipantOption(
    val participantId: String,
    val participantName: String,
)

private fun FinalSettlementSuggestionUi.toRequest(activityId: String, onBehalfOfParticipantId: String?): FinalSettlementRequest =
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
        onBehalfOfParticipantId = onBehalfOfParticipantId,
    )

private val SettlementSuggestions = listOf(
    FinalSettlementSuggestionUi(
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
    FinalSettlementSuggestionUi(
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
    FinalSettlementSuggestionUi(
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

private val DepositReturn = FinalSettlementSuggestionUi(
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
 * Large-activity settlement review. Each execution emits a complete request;
 * the host owns persistence and the final-settlement write flow.
 */
@Composable
fun FinalSettlementScreen(
    activityId: String = "",
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onFinalize: ((FinalSettlementRequest) -> Unit)? = null,
    suggestions: List<FinalSettlementSuggestionUi> = emptyList(),
    isLoading: Boolean = false,
    errorMessage: String? = null,
    onRetry: (() -> Unit)? = null,
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
                when {
                    isLoading -> item(key = "loading") { Text("正在读取最新结算方案…", style = SharedLedgerTextStyles.BodySecondary) }
                    errorMessage != null -> item(key = "error") {
                        Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                            Text(errorMessage, color = MaterialTheme.colorScheme.error)
                            onRetry?.let { SharedLedgerButton("重新读取方案", it, tone = SharedLedgerButtonTone.SoftPrimary) }
                        }
                    }
                    suggestions.isEmpty() -> item(key = "empty") { Text("当前没有待执行的结算项", style = SharedLedgerTextStyles.BodySecondary) }
                    else -> {
                        item(key = "suggested-header") { SettlementSectionHeader("建议转账 (${suggestions.size}笔)", "待处理") }
                        items(suggestions, key = { it.id }) { suggestion ->
                            SettlementSuggestionCard(suggestion, onFinalize?.let { callback -> { behalfId -> callback(suggestion.toRequest(activityId, behalfId)) } })
                        }
                    }
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
    suggestion: FinalSettlementSuggestionUi,
    onExecute: ((String?) -> Unit)?,
    modifier: Modifier = Modifier,
) {
    var selectedOnBehalfId by remember(suggestion.id) {
        mutableStateOf(suggestion.onBehalfOptions.firstOrNull()?.participantId.takeIf { suggestion.onBehalfRequired })
    }
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
            Column(
                modifier = Modifier.weight(1f),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                ) {
                    ParticipantAvatar(name = suggestion.from.name, backgroundColor = SurfaceWarmHigh, size = SharedLedgerDimens.AvatarMedium)
                    Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = "转给", modifier = Modifier.size(SharedLedgerDimens.IconSmall), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    ParticipantAvatar(name = suggestion.to.name, backgroundColor = SurfaceWarmHigh, size = SharedLedgerDimens.AvatarMedium)
                    Column(horizontalAlignment = Alignment.End, modifier = Modifier.padding(start = SharedLedgerSpacing.XSmall)) {
                        AmountDisplay(amount = suggestion.amount, currencyCode = suggestion.currency, fractionDigitsOverride = 1, size = AmountSize.Small)
                        Text("账务版本 v${suggestion.sourceFinancialVersion}", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                if (suggestion.onBehalfOptions.isNotEmpty()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
                        item(key = "on-behalf-label") { Text("代记", style = SharedLedgerTextStyles.Label) }
                        items(suggestion.onBehalfOptions, key = { it.participantId }) { option ->
                            TextButton(onClick = { selectedOnBehalfId = option.participantId }) {
                                Text(if (selectedOnBehalfId == option.participantId) "✓ ${option.participantName}" else option.participantName)
                            }
                        }
                    }
                }
            }
            if (onExecute == null) {
                SuggestionBadge("只读方案 · v${suggestion.sourceFinancialVersion}")
            } else {
                TextButton(onClick = { onExecute(selectedOnBehalfId) }) { Text("执行") }
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
        FinalSettlementScreen(
            activityId = "preview-large",
            suggestions = SettlementSuggestions + DepositReturn,
        )
    }
}
