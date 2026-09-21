package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
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
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLow
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.data.financial.FinalSettlementMode
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
    val mode: FinalSettlementMode = FinalSettlementMode.BASE_UNIFIED,
    val planNo: Int? = null,
    val pathNo: Int? = null,
    val hopNo: Int? = null,
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
        sourceFinancialVersion >= 0L &&
        mode.databaseValue.isNotBlank()

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
    val mode: FinalSettlementMode = FinalSettlementMode.BASE_UNIFIED,
    val planNo: Int? = null,
    val pathNo: Int? = null,
    val hopNo: Int? = null,
)

data class FinalSettlementParticipantOption(
    val participantId: String,
    val participantName: String,
)

internal const val FinalSettlementPlanExplanation =
    "系统已汇总全部未结账目，并按每位参与人的净应收、净应付生成转账方案。"

internal fun FinalSettlementSuggestionUi.directionLabel(): String =
    "${from.name} → ${to.name}"

internal fun FinalSettlementSuggestionUi.paymentInstruction(): String =
    "${from.name} 向 ${to.name} 转账"

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
        mode = mode,
        planNo = planNo,
        pathNo = pathNo,
        hopNo = hopNo,
    )

private val SettlementSuggestions = listOf(
    FinalSettlementSuggestionUi(
        id = "zhang-san-wang-wu",
        fromParticipantId = "fake-alice",
        toParticipantId = "fake-bob",
        from = ParticipantUiModel("张三", AvatarBackground.Bound("sage")),
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
        from = ParticipantUiModel("李四", AvatarBackground.Bound("terracotta")),
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
        to = ParticipantUiModel("张三", AvatarBackground.Bound("sage")),
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
    from = ParticipantUiModel("张三", AvatarBackground.Bound("sage")),
    to = ParticipantUiModel("李四", AvatarBackground.Bound("terracotta")),
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
    mode: FinalSettlementMode = FinalSettlementMode.BASE_UNIFIED,
    onModeChange: ((FinalSettlementMode) -> Unit)? = null,
) {
    val hazeState = rememberSharedLedgerHazeState()
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "共享账本",
                showBackButton = onBack != null,
                onBackClick = onBack,
                hazeState = hazeState,
                containerColor = MaterialTheme.colorScheme.background,
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
            LazyColumn(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxSize()
                    .sharedLedgerHazeSource(hazeState),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Large,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.XLarge,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
            ) {
                item(key = "header") {
                    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                        Text(
                            text = "最终结算",
                            style = SharedLedgerTextStyles.PageTitle,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = FinalSettlementPlanExplanation,
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (onModeChange != null) {
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                                items(FinalSettlementMode.entries, key = { it.databaseValue }) { option ->
                                    Surface(
                                        onClick = { onModeChange(option) },
                                        shape = SharedLedgerRadius.Full,
                                        color = if (option == mode) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLowest,
                                        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
                                    ) {
                                        Text(
                                            text = if (option == FinalSettlementMode.BASE_UNIFIED) "统一基础币" else "按原币种",
                                            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.Small),
                                            style = SharedLedgerTextStyles.Label,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
                when {
                    isLoading -> item(key = "loading") { LoadingState(message = "正在读取最新结算方案…") }
                    errorMessage != null -> item(key = "error") {
                        ErrorState(message = errorMessage, onRetry = onRetry, retryLabel = "重新读取方案")
                    }
                    suggestions.isEmpty() -> item(key = "empty") { EmptyState(title = "当前没有待执行的结算项") }
                    else -> {
                        val groups = suggestions.groupBy { "${it.fromParticipantId}->${it.toParticipantId}:${it.currency}" }
                        groups.entries.forEach { (groupKey, group) ->
                            item(key = "suggested-header:$groupKey") {
                                SettlementSectionHeader(
                                    "${group.first().directionLabel()} · ${group.first().currency} (${group.size}笔)",
                                    "待处理",
                                    modifier = Modifier.padding(top = SharedLedgerSpacing.MediumSmall),
                                )
                            }
                            items(group, key = { it.id }) { suggestion ->
                                SettlementSuggestionCard(suggestion, onFinalize?.let { callback -> { behalfId -> callback(suggestion.toRequest(activityId, behalfId)) } })
                            }
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
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                ) {
                    Text(
                        text = suggestion.directionLabel(),
                        style = SharedLedgerTextStyles.CardTitle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = suggestion.paymentInstruction(),
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    AmountDisplay(
                        amount = suggestion.amount,
                        currencyCode = suggestion.currency,
                        fractionDigitsOverride = 1,
                        size = AmountSize.Medium,
                    )
                    SuggestionBadge("待转账")
                }
            }
            if (suggestion.onBehalfOptions.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
                    Text(
                        "选择代记人（不会改变上方转账双方）",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                        items(suggestion.onBehalfOptions, key = { it.participantId }) { option ->
                            OnBehalfChip(
                                label = option.participantName,
                                selected = selectedOnBehalfId == option.participantId,
                                onClick = { selectedOnBehalfId = option.participantId },
                            )
                        }
                    }
                }
            }
            if (onExecute == null) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    SuggestionBadge("只读方案 · v${suggestion.sourceFinancialVersion}")
                }
            } else {
                SharedLedgerButton(
                    text = "记录已转账",
                    onClick = { onExecute(selectedOnBehalfId) },
                    tone = SharedLedgerButtonTone.SoftPrimary,
                )
            }
        }
    }
}

@Composable
private fun OnBehalfChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        onClick = onClick,
        shape = SharedLedgerRadius.Full,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmLowest,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Box(
            modifier = Modifier
                .defaultMinSize(minHeight = SharedLedgerDimens.TopBarActionSize)
                .padding(horizontal = SharedLedgerSpacing.Medium),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = if (selected) "✓ $label" else label,
                style = SharedLedgerTextStyles.Label,
            )
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
