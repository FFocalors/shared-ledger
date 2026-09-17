package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import com.ffocalors.sharedledger.ui.components.SharedLedgerIcons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Sort
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepositoryFactory
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.financial.FinancialReadViewModel
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.ErrorContainer
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmContainer
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.TextSecondary
import com.ffocalors.sharedledger.ui.theme.WarmBrown
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter
import java.time.Instant

enum class FundRecordSortOrder(val label: String, val nextActionLabel: String) {
    NEWEST_FIRST("时间：新到旧", "切换为时间从旧到新"),
    OLDEST_FIRST("时间：旧到新", "切换为时间从新到旧"),
    ;

    fun toggled(): FundRecordSortOrder = when (this) {
        NEWEST_FIRST -> OLDEST_FIRST
        OLDEST_FIRST -> NEWEST_FIRST
    }
}

internal fun sortFundRecords(records: List<FundRecord>, order: FundRecordSortOrder): List<FundRecord> {
    val parsed = records.map { record -> record to runCatching { Instant.parse(record.occurredAt) }.getOrNull() }
    return if (parsed.all { it.second != null }) {
        val comparator = compareBy<Pair<FundRecord, Instant?>> { it.second }.thenBy { it.first.transferId }
        parsed.sortedWith(if (order == FundRecordSortOrder.NEWEST_FIRST) comparator.reversed() else comparator).map { it.first }
    } else {
        val comparator = compareBy<FundRecord> { it.occurredAt }.thenBy { it.transferId }
        if (order == FundRecordSortOrder.NEWEST_FIRST) records.sortedWith(comparator.reversed()) else records.sortedWith(comparator)
    }
}

enum class FundRecordFilter(val label: String, val type: FundRecordType?) {
    ALL("全部记录", null),
    SETTLEMENT("结算转账", FundRecordType.SETTLEMENT),
    PREPAYMENT("预存资金", FundRecordType.PREPAYMENT),
    PREPAYMENT_RETURN("预存退回", FundRecordType.PREPAYMENT_RETURN),
    FINAL_SETTLEMENT("最终清算", FundRecordType.FINAL_SETTLEMENT),
    AUTO_PREPAYMENT_USAGE("预存自动扣款", FundRecordType.AUTO_PREPAYMENT_USAGE),
    REFUND("退款", FundRecordType.REFUND),
}

@Immutable
sealed interface FundRecordsUiState {
    data object Loading : FundRecordsUiState
    data class Content(val records: List<FundRecord>) : FundRecordsUiState
    data object Empty : FundRecordsUiState
    data class Error(val message: String) : FundRecordsUiState
}

@Composable
fun FundRecordsScreen(
    activityId: String = "",
    ledgerUnitId: String? = null,
    externalRefreshToken: Long = 0L,
    financialViewModel: FinancialReadViewModel? = null,
    repository: FinancialRecordRepository = remember { FinancialRecordRepositoryFactory.create() },
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onRecordClick: ((record: FundRecord) -> Unit)? = null,
    onPrepayment: (() -> Unit)? = null,
    onPrepaymentReturn: (() -> Unit)? = null,
) {
    var selectedFilter by remember { mutableStateOf(FundRecordFilter.ALL) }
    var sortOrder by remember(activityId) { mutableStateOf(FundRecordSortOrder.NEWEST_FIRST) }
    var uiState by remember { mutableStateOf<FundRecordsUiState>(FundRecordsUiState.Loading) }
    var refreshToken by remember { mutableIntStateOf(0) }
    val financialState = financialViewModel?.let { it.recordsState(activityId).collectAsState().value }
    LaunchedEffect(activityId, financialViewModel, selectedFilter, refreshToken, externalRefreshToken) {
        if (financialViewModel != null) {
            financialViewModel.loadRecords(activityId, force = refreshToken > 0 || externalRefreshToken > 0)
        } else {
            uiState = FundRecordsUiState.Loading
            uiState = when (val result = repository.list(activityId, selectedFilter.type)) {
                is FinancialReadResult.Success -> result.value.takeIf { it.isNotEmpty() }?.let(FundRecordsUiState::Content)
                    ?: FundRecordsUiState.Empty
                is FinancialReadResult.Failure -> FundRecordsUiState.Error(result.message)
            }
        }
    }
    val resolvedUiState = financialState?.let { state ->
        when {
            state.data != null -> state.data.filter { selectedFilter.type == null || it.type == selectedFilter.type }
                .takeIf { it.isNotEmpty() }?.let(FundRecordsUiState::Content) ?: FundRecordsUiState.Empty
            state.isLoading -> FundRecordsUiState.Loading
            state.errorMessage != null -> FundRecordsUiState.Error(state.errorMessage)
            else -> FundRecordsUiState.Empty
        }
    } ?: uiState
    FundRecordsScreen(
        uiState = resolvedUiState,
        selectedFilter = selectedFilter,
        sortOrder = sortOrder,
        modifier = modifier,
        dataSourceLabel = ledgerUnitId,
        onBack = onBack,
        onFilterSelected = { selectedFilter = it },
        onSortOrderChanged = { sortOrder = it },
        onRetry = { refreshToken++ },
        onRefresh = { refreshToken++ },
        onRecordClick = onRecordClick,
        onPrepayment = onPrepayment,
        onPrepaymentReturn = onPrepaymentReturn,
    )
}

@Composable
fun FundRecordsScreen(
    uiState: FundRecordsUiState,
    selectedFilter: FundRecordFilter = FundRecordFilter.ALL,
    sortOrder: FundRecordSortOrder = FundRecordSortOrder.NEWEST_FIRST,
    modifier: Modifier = Modifier,
    dataSourceLabel: String? = null,
    onBack: (() -> Unit)? = null,
    onFilterSelected: ((FundRecordFilter) -> Unit)? = null,
    onSortOrderChanged: ((FundRecordSortOrder) -> Unit)? = null,
    onRetry: (() -> Unit)? = null,
    onRefresh: (() -> Unit)? = null,
    onRecordClick: ((record: FundRecord) -> Unit)? = null,
    onPrepayment: (() -> Unit)? = null,
    onPrepaymentReturn: (() -> Unit)? = null,
) {
    val hazeState = rememberSharedLedgerHazeState()
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            SharedLedgerTopBar(
                title = "统一资金记录",
                containerColor = AppBackground,
                titleStyle = SharedLedgerTextStyles.PageTitle,
                titleColor = SageGreen,
                showBackButton = onBack != null,
                onBackClick = onBack,
                showMoreButton = onRefresh != null,
                onMoreClick = onRefresh,
                hazeState = hazeState,
            )
        },
    ) { paddingValues ->
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
                    top = paddingValues.calculateTopPadding(),
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = paddingValues.calculateBottomPadding() + SharedLedgerSpacing.Large,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
            ) {
                item(key = "filters") {
                    FilterSection(selectedFilter, onFilterSelected, sortOrder, onSortOrderChanged)
                }
                if (onPrepayment != null || onPrepaymentReturn != null) {
                    item(key = "prepayment-actions") {
                        Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                            onPrepayment?.let { callback ->
                                SharedLedgerButton("新增预存", callback, modifier = Modifier.weight(1f), tone = SharedLedgerButtonTone.WarmSecondary, icon = Icons.Rounded.AccountBalanceWallet)
                            }
                            onPrepaymentReturn?.let { callback ->
                                SharedLedgerButton("返还预存", callback, modifier = Modifier.weight(1f), tone = SharedLedgerButtonTone.Neutral, icon = SharedLedgerIcons.FundRecords)
                            }
                        }
                    }
                }
                // Kept for the repository/ViewModel contract; the Stitch surface does not expose a source label.
                dataSourceLabel?.let { _ -> }
                when (uiState) {
                    FundRecordsUiState.Loading -> item(key = "loading") { LoadingState(message = "正在加载资金记录…") }
                    is FundRecordsUiState.Content -> items(
                        sortFundRecords(uiState.records, sortOrder),
                        key = { it.transferId },
                    ) { RecordCard(it, onRecordClick) }
                    FundRecordsUiState.Empty -> item(key = "empty") {
                        EmptyState(
                            title = "暂无资金记录",
                            icon = Icons.Rounded.AccountBalanceWallet,
                            description = "切换筛选条件，或刷新查看最新记录。",
                            actionLabel = if (onRefresh != null) "刷新" else null,
                            onAction = onRefresh,
                        )
                    }
                    is FundRecordsUiState.Error -> item(key = "error") {
                        ErrorState(message = uiState.message, onRetry = onRetry)
                    }
                }
            }
        }
    }
}

@Composable
private fun FilterSection(
    selected: FundRecordFilter,
    onSelected: ((FundRecordFilter) -> Unit)?,
    sortOrder: FundRecordSortOrder,
    onSortOrderChanged: ((FundRecordSortOrder) -> Unit)?,
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Small),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        ) {
            FundRecordFilter.entries.forEach { filter ->
                FilterPill(filter, selected == filter, onSelected)
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
        ) {
            Surface(
                onClick = { onSortOrderChanged?.invoke(sortOrder.toggled()) },
                enabled = onSortOrderChanged != null,
                shape = SharedLedgerRadius.Full,
                color = Color.Transparent,
                modifier = Modifier.semantics { stateDescription = sortOrder.label },
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Small, vertical = SharedLedgerSpacing.XSmall),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                ) {
                    Text(sortOrder.label, style = SharedLedgerTextStyles.Label, color = TextSecondary)
                    Icon(
                        Icons.Rounded.Sort,
                        contentDescription = "${sortOrder.label}，${sortOrder.nextActionLabel}",
                        tint = TextSecondary,
                        modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                    )
                }
            }
        }
    }
}

@Composable
private fun FilterPill(filter: FundRecordFilter, selected: Boolean, onSelected: ((FundRecordFilter) -> Unit)?) {
    Surface(
        onClick = { onSelected?.invoke(filter) },
        enabled = onSelected != null,
        shape = SharedLedgerRadius.Full,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmContainer,
        contentColor = if (selected) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Box(
            modifier = Modifier
                .heightIn(min = SharedLedgerDimens.ActionIconContainer)
                .padding(horizontal = SharedLedgerSpacing.Medium),
            contentAlignment = Alignment.Center,
        ) {
            Text(filter.label, style = SharedLedgerTextStyles.Label)
        }
    }
}

@Composable
private fun RecordCard(record: FundRecord, onRecordClick: ((FundRecord) -> Unit)?) {
    val voided = record.isVoided
    val cardColor = if (voided) SurfaceWarmLowest.copy(alpha = 0.5f) else SurfaceWarmLowest
    val cardBorder = BorderStroke(
        SharedLedgerDimens.OutlineWidth,
        AppOutlineVariant.copy(alpha = if (voided) 0.2f else SharedLedgerDimens.CardBorderAlpha),
    )
    val cardElevation = if (voided) SharedLedgerElevation.Flat else SharedLedgerElevation.Card
    if (onRecordClick != null) {
        Surface(
            onClick = { onRecordClick(record) },
            modifier = Modifier.fillMaxWidth(),
            shape = SharedLedgerRadius.Large,
            color = cardColor,
            shadowElevation = cardElevation,
            border = cardBorder,
        ) {
            RecordCardContent(record, voided, showChevron = !voided)
        }
    } else {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = SharedLedgerRadius.Large,
            color = cardColor,
            shadowElevation = cardElevation,
            border = cardBorder,
        ) {
            RecordCardContent(record, voided, showChevron = false)
        }
    }
}

@Composable
private fun RecordCardContent(record: FundRecord, voided: Boolean, showChevron: Boolean) {
    val disputed = record.hasUnresolvedDispute
    Column(modifier = Modifier.padding(SharedLedgerDimens.CardPadding), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Row(modifier = Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                Surface(modifier = Modifier.size(SharedLedgerSpacing.Small), shape = SharedLedgerRadius.Full, color = typeColor(record.type, voided)) {}
                Text(record.type.displayName, style = SharedLedgerTextStyles.Label, color = TextSecondary)
            }
            StatusPill(record, disputed)
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            Text(
                record.from.displayName,
                modifier = Modifier.weight(1f, fill = false),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = SharedLedgerTextStyles.CardTitle.copy(textDecoration = if (voided) TextDecoration.LineThrough else TextDecoration.None),
                color = if (voided) TextSecondary.copy(alpha = 0.5f) else DeepCharcoal,
            )
            Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = "资金流向", tint = MaterialTheme.colorScheme.outline, modifier = Modifier.size(SharedLedgerDimens.IconSmall))
            Text(
                record.to.displayName,
                modifier = Modifier.weight(1f, fill = false),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = SharedLedgerTextStyles.CardTitle.copy(textDecoration = if (voided) TextDecoration.LineThrough else TextDecoration.None),
                color = if (voided) TextSecondary.copy(alpha = 0.5f) else DeepCharcoal,
            )
        }
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
            Text(UiDateTimeFormatter.format(record.occurredAt), style = SmallMetaStyle, color = TextSecondary)
            Spacer(Modifier.weight(1f))
            AmountDisplay(record.amount, currencyCode = record.currency, size = AmountSize.Small, emphasis = if (voided) AmountEmphasis.Muted else if (record.type == FundRecordType.PREPAYMENT) AmountEmphasis.Warning else AmountEmphasis.Primary)
        }
        Text(componentSummary(record), style = SmallMetaStyle, color = TextSecondary.copy(alpha = 0.7f), modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.XSmall))
        HorizontalDivider(color = AppOutlineVariant.copy(alpha = 0.2f))
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(if (record.onBehalfOf == null) "记录人：${record.recordedBy.displayName}" else "${record.onBehalfOf.displayName} 代记", style = SmallMetaStyle, color = TextSecondary.copy(alpha = 0.5f), modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (showChevron) Icon(Icons.Rounded.ChevronRight, contentDescription = "查看详情", tint = TextSecondary.copy(alpha = 0.5f), modifier = Modifier.size(SharedLedgerDimens.IconSmall))
        }
        if (voided && record.source == com.ffocalors.sharedledger.domain.financial.FundRecordSource.REFUND_EXPENSE) {
            record.voidMetadata?.let {
                Text("删除状态：${it.reason}", style = SmallMetaStyle, color = TextSecondary.copy(alpha = 0.5f))
            }
        }
    }
}

private val SmallMetaStyle = TextStyle(fontSize = 13.sp, lineHeight = 20.sp, fontWeight = FontWeight.Normal)

private fun typeColor(type: FundRecordType, voided: Boolean): Color = when {
    voided -> MaterialThemeColor.outline
    type == FundRecordType.PREPAYMENT || type == FundRecordType.PREPAYMENT_RETURN -> WarmBrown
    type == FundRecordType.AUTO_PREPAYMENT_USAGE -> SageGreen
    else -> SageGreen
}

// MaterialTheme is unavailable outside composition; this constant only backs the voided dot.
private object MaterialThemeColor { val outline = Color(0xFF75786E) }

@Composable
private fun StatusPill(record: FundRecord, disputed: Boolean) {
    val (label, background, foreground) = when {
        record.isVoided -> Triple(if (record.source == com.ffocalors.sharedledger.domain.financial.FundRecordSource.REFUND_EXPENSE) "已删除" else "已作废", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
        disputed -> Triple("存在争议", ErrorContainer.copy(alpha = 0.5f), ErrorRed)
        else -> Triple("有效", MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f), MaterialTheme.colorScheme.onPrimaryContainer)
    }
    Surface(shape = SharedLedgerRadius.Small, color = background, contentColor = foreground) {
        Text(label, style = SharedLedgerTextStyles.Label, modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Small, vertical = SharedLedgerSpacing.XSmall))
    }
}

private fun componentSummary(record: FundRecord): String = when {
    record.type == FundRecordType.AUTO_PREPAYMENT_USAGE -> "预存自动扣款 · 来源账单：${record.sourceExpenseTitle ?: record.sourceExpenseId ?: "未知账单"}"
    record.type == FundRecordType.REFUND -> record.sourceExpenseTitle?.let { "原账单：$it" } ?: "独立退款"
    record.isVoided -> record.voidMetadata?.let { "作废原因：${it.reason}" } ?: "已作废"
    record.components.isEmpty() -> "暂无资金构成"
    else -> record.components.joinToString(" + ") { component -> "${component.type.displayName} ${com.ffocalors.sharedledger.ui.util.MoneyFormatter.format(component.amount, record.currency)}" }
}
