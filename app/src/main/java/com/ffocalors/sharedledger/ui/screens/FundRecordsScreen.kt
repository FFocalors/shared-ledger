package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.ArrowForward
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Sort
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.data.financial.FakeFinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepository
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.Cream
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.ErrorContainer
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmContainer
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.TextSecondary
import com.ffocalors.sharedledger.ui.theme.WarmBrown
import java.math.BigDecimal

enum class FundRecordFilter(val label: String, val type: FundRecordType?) {
    ALL("全部记录", null),
    SETTLEMENT("结算转账", FundRecordType.SETTLEMENT),
    PREPAYMENT("预存资金", FundRecordType.PREPAYMENT),
    PREPAYMENT_RETURN("预存退回", FundRecordType.PREPAYMENT_RETURN),
    FINAL_SETTLEMENT("最终清算", FundRecordType.FINAL_SETTLEMENT),
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
    activityId: String = "fake-preview-activity",
    ledgerUnitId: String? = null,
    repository: FinancialRecordRepository = remember { FakeFinancialRecordRepository() },
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onRecordClick: ((transferId: String) -> Unit)? = null,
) {
    var selectedFilter by remember { mutableStateOf(FundRecordFilter.ALL) }
    var uiState by remember { mutableStateOf<FundRecordsUiState>(FundRecordsUiState.Loading) }
    var refreshToken by remember { mutableIntStateOf(0) }
    LaunchedEffect(activityId, repository, selectedFilter, refreshToken) {
        uiState = FundRecordsUiState.Loading
        uiState = when (val result = repository.list(activityId, selectedFilter.type)) {
            is FinancialReadResult.Success -> result.value.takeIf { it.isNotEmpty() }?.let(FundRecordsUiState::Content)
                ?: FundRecordsUiState.Empty
            is FinancialReadResult.Failure -> FundRecordsUiState.Error(result.message)
        }
    }
    FundRecordsScreen(
        uiState = uiState,
        selectedFilter = selectedFilter,
        modifier = modifier,
        dataSourceLabel = if (repository is FakeFinancialRecordRepository) "演示数据" else ledgerUnitId,
        onBack = onBack,
        onFilterSelected = { selectedFilter = it },
        onRetry = { refreshToken++ },
        onRefresh = { refreshToken++ },
        onRecordClick = onRecordClick,
    )
}

@Composable
fun FundRecordsScreen(
    uiState: FundRecordsUiState,
    selectedFilter: FundRecordFilter = FundRecordFilter.ALL,
    modifier: Modifier = Modifier,
    dataSourceLabel: String? = null,
    onBack: (() -> Unit)? = null,
    onFilterSelected: ((FundRecordFilter) -> Unit)? = null,
    onRetry: (() -> Unit)? = null,
    onRefresh: (() -> Unit)? = null,
    onRecordClick: ((transferId: String) -> Unit)? = null,
) {
    Scaffold(modifier = modifier.fillMaxSize(), containerColor = AppBackground) { paddingValues ->
        Column(
            modifier = Modifier.fillMaxSize().padding(paddingValues).widthIn(max = SharedLedgerDimens.ContentMaxWidth).fillMaxWidth(),
        ) {
            UnifiedTopBar(onBack = onBack, onMore = onRefresh)
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                contentPadding = PaddingValues(bottom = SharedLedgerSpacing.Large),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                item(key = "filters") { FilterSection(selectedFilter, onFilterSelected) }
                // Kept for the repository/ViewModel contract; the Stitch surface does not expose a source label.
                dataSourceLabel?.let { _ -> }
                when (uiState) {
                    FundRecordsUiState.Loading -> item(key = "loading") { LoadingState() }
                    is FundRecordsUiState.Content -> items(uiState.records, key = { it.transferId }) { RecordCard(it, onRecordClick) }
                    FundRecordsUiState.Empty -> item(key = "empty") { StateMessage(Icons.Rounded.AccountBalanceWallet, "暂无资金记录", "切换筛选条件，或刷新查看最新记录。", "刷新", onRefresh) }
                    is FundRecordsUiState.Error -> item(key = "error") { StateMessage(Icons.Rounded.ErrorOutline, "加载失败", uiState.message, "重试", onRetry) }
                }
            }
        }
    }
}

@Composable
private fun UnifiedTopBar(onBack: (() -> Unit)?, onMore: (() -> Unit)?) {
    Surface(modifier = Modifier.fillMaxWidth(), color = AppBackground) {
        Row(
            modifier = Modifier.fillMaxWidth().height(64.dp).padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            IconButton(onClick = { onBack?.invoke() }) {
                Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "返回", tint = TextSecondary)
            }
            Text("统一资金记录", style = SharedLedgerTextStyles.PageTitle, color = SageGreen)
            IconButton(onClick = { onMore?.invoke() }) {
                Icon(Icons.Rounded.MoreVert, contentDescription = "更多", tint = TextSecondary)
            }
        }
    }
}

@Composable
private fun FilterSection(selected: FundRecordFilter, onSelected: ((FundRecordFilter) -> Unit)?) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Small, bottom = SharedLedgerSpacing.Large),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            listOf(FundRecordFilter.ALL, FundRecordFilter.SETTLEMENT, FundRecordFilter.PREPAYMENT).forEach { filter ->
                FilterPill(filter, selected == filter, onSelected)
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(modifier = Modifier.weight(1f).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                listOf(FundRecordFilter.PREPAYMENT_RETURN, FundRecordFilter.FINAL_SETTLEMENT).forEach { filter ->
                    FilterPill(filter, selected == filter, onSelected)
                }
            }
            IconButton(onClick = {}) { Icon(Icons.Rounded.Sort, contentDescription = "排序", tint = TextSecondary, modifier = Modifier.size(18.dp)) }
        }
    }
}

@Composable
private fun FilterPill(filter: FundRecordFilter, selected: Boolean, onSelected: ((FundRecordFilter) -> Unit)?) {
    Surface(
        modifier = Modifier.clickable(enabled = onSelected != null) { onSelected?.invoke(filter) },
        shape = SharedLedgerRadius.Full,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else SurfaceWarmContainer,
        contentColor = if (selected) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Text(filter.label, style = SharedLedgerTextStyles.Label, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
    }
}

@Composable
private fun RecordCard(record: FundRecord, onRecordClick: ((String) -> Unit)?) {
    val voided = record.isVoided
    val disputed = record.hasUnresolvedDispute
    val interaction = onRecordClick?.let { callback -> Modifier.clickable(role = Role.Button) { callback(record.transferId) }.semantics { role = Role.Button } } ?: Modifier
    Surface(
        modifier = Modifier.fillMaxWidth().then(interaction),
        shape = RoundedCornerShape(16.dp),
        color = if (voided) SurfaceWarmLowest.copy(alpha = 0.5f) else SurfaceWarmLowest,
        shadowElevation = if (voided) 0.dp else SharedLedgerElevation.Card,
        border = BorderStroke(1.dp, AppOutlineVariant.copy(alpha = if (voided) 0.2f else 0.3f)),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Row(modifier = Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Surface(modifier = Modifier.size(8.dp), shape = SharedLedgerRadius.Full, color = typeColor(record.type, voided)) {}
                    Text(record.type.displayName, style = SharedLedgerTextStyles.Label, color = TextSecondary)
                }
                StatusPill(record, disputed)
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(record.from.displayName, style = SharedLedgerTextStyles.CardTitle.copy(textDecoration = if (voided) TextDecoration.LineThrough else TextDecoration.None), color = if (voided) TextSecondary.copy(alpha = 0.5f) else DeepCharcoal)
                Icon(Icons.Rounded.ArrowForward, contentDescription = "资金流向", tint = MaterialTheme.colorScheme.outline, modifier = Modifier.size(16.dp))
                Text(record.to.displayName, style = SharedLedgerTextStyles.CardTitle.copy(textDecoration = if (voided) TextDecoration.LineThrough else TextDecoration.None), color = if (voided) TextSecondary.copy(alpha = 0.5f) else DeepCharcoal)
            }
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
                Text(record.occurredAt, style = SmallMetaStyle, color = TextSecondary)
                Spacer(Modifier.weight(1f))
                AmountDisplay(record.amount, currencyCode = record.currency, size = AmountSize.Small, emphasis = if (voided) AmountEmphasis.Muted else if (record.type == FundRecordType.PREPAYMENT) AmountEmphasis.Warning else AmountEmphasis.Primary, fractionDigitsOverride = 2)
            }
            Text(componentSummary(record), style = SmallMetaStyle, color = TextSecondary.copy(alpha = 0.7f), modifier = Modifier.fillMaxWidth().padding(top = 2.dp))
            HorizontalDivider(color = AppOutlineVariant.copy(alpha = 0.2f))
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(if (record.onBehalfOf == null) "记录人：${record.recordedBy.displayName}" else "${record.onBehalfOf.displayName} 代记", style = SmallMetaStyle, color = TextSecondary.copy(alpha = 0.5f), modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (!voided && onRecordClick != null) Icon(Icons.Rounded.ChevronRight, contentDescription = "查看详情", tint = TextSecondary.copy(alpha = 0.5f), modifier = Modifier.size(16.dp))
            }
            if (voided) {
                record.voidMetadata?.let { Text("作废原因：${it.reason}", style = SmallMetaStyle, color = TextSecondary.copy(alpha = 0.5f)) }
            }
        }
    }
}

private val SmallMetaStyle = TextStyle(fontSize = 13.sp, lineHeight = 20.sp, fontWeight = FontWeight.Normal)

private fun typeColor(type: FundRecordType, voided: Boolean): Color = when {
    voided -> MaterialThemeColor.outline
    type == FundRecordType.PREPAYMENT || type == FundRecordType.PREPAYMENT_RETURN -> WarmBrown
    else -> SageGreen
}

// MaterialTheme is unavailable outside composition; this constant only backs the voided dot.
private object MaterialThemeColor { val outline = Color(0xFF75786E) }

@Composable
private fun StatusPill(record: FundRecord, disputed: Boolean) {
    val (label, background, foreground) = when {
        record.isVoided -> Triple("已作废", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
        disputed -> Triple("存在争议", ErrorContainer.copy(alpha = 0.5f), ErrorRed)
        else -> Triple("有效", MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f), MaterialTheme.colorScheme.onPrimaryContainer)
    }
    Surface(shape = RoundedCornerShape(4.dp), color = background, contentColor = foreground) {
        Text(label, style = SharedLedgerTextStyles.Label, modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp))
    }
}

private fun componentSummary(record: FundRecord): String = when {
    record.isVoided -> record.voidMetadata?.let { "作废原因：${it.reason}" } ?: "已作废"
    record.components.isEmpty() -> "暂无资金构成"
    else -> record.components.joinToString(" + ") { component -> "${component.type.displayName} ¥${component.amount.setScale(2).toPlainString()}" }
}

@Composable
private fun LoadingState() {
    Box(Modifier.fillMaxWidth().height(220.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            Text("正在加载资金记录…", style = SharedLedgerTextStyles.BodySecondary)
        }
    }
}

@Composable
private fun StateMessage(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, message: String, actionLabel: String, onAction: (() -> Unit)?) {
    Box(Modifier.fillMaxWidth().height(260.dp), contentAlignment = Alignment.Center) {
        Column(modifier = Modifier.padding(SharedLedgerSpacing.Large), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(48.dp), tint = MaterialTheme.colorScheme.primary)
            Text(title, style = SharedLedgerTextStyles.SectionTitle)
            Text(message, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
            onAction?.let { SharedLedgerButton(actionLabel, it, tone = SharedLedgerButtonTone.SoftPrimary, icon = Icons.Rounded.Refresh) }
        }
    }
}
