package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Flag
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Route
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.financial.FakeFinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponent
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.domain.financial.TransferDispute
import com.ffocalors.sharedledger.domain.financial.VoidMetadata
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.Cream
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import java.math.BigDecimal

enum class TransferDetailDirection { TRANSFER, RECEIVE }

/** Compatibility shell for existing callers; [record] is the canonical state. */
@Immutable
data class TransferDetailUiState(
    val transferId: String = "fake-final-001",
    val activityId: String = "fake-preview-activity",
    val ledgerUnitId: String? = null,
    val direction: TransferDetailDirection = TransferDetailDirection.TRANSFER,
    val payer: ParticipantUiModel = ParticipantUiModel("张三", IconContainerSage),
    val recipient: ParticipantUiModel = ParticipantUiModel("李四", IconContainerOrange),
    val flowLabel: String = "最终结算",
    val totalAmount: BigDecimal = BigDecimal("320.00"),
    val currencyCode: String = "CNY",
    val occurredAt: String = "2026-09-02 09:00",
    val recordedAt: String = "2026-09-02 09:01",
    val recordedBy: ParticipantUiModel = ParticipantUiModel("Fake 预览记录人", IconContainerSage),
    val recordMethod: String = "演示",
    val disputed: Boolean = false,
    val debtRepayment: BigDecimal = BigDecimal("200.00"),
    val newPrepayment: BigDecimal = BigDecimal("120.00"),
    val note: String? = null,
    val receiptCount: Int = 0,
    val receiptLabel: String = "",
    val record: FundRecord? = null,
    val errorMessage: String? = null,
    /** Resolved by the host from the authenticated member, never inferred as payer. */
    val currentParticipantId: String? = "legacy-from",
    val currentParticipantName: String? = null,
)

private fun TransferDetailUiState.toFundRecord(): FundRecord = record ?: run {
    val from = ParticipantInfo("legacy-from", payer.name)
    val to = ParticipantInfo("legacy-to", recipient.name)
    val recorder = RecorderInfo("legacy-recorder", recordedBy.name)
    val legacyType = FundRecordType.entries.firstOrNull { it.displayName == flowLabel } ?: FundRecordType.PREPAYMENT
    val components = when (legacyType) {
        FundRecordType.SETTLEMENT -> listOf(FundRecordComponent("legacy-component", FundRecordComponentType.SETTLEMENT, totalAmount))
        FundRecordType.PREPAYMENT -> listOfNotNull(
            debtRepayment.takeIf { it > BigDecimal.ZERO }?.let { FundRecordComponent("legacy-settlement", FundRecordComponentType.SETTLEMENT, it) },
            newPrepayment.takeIf { it > BigDecimal.ZERO }?.let { FundRecordComponent("legacy-prepayment", FundRecordComponentType.PREPAYMENT, it) },
        )
        FundRecordType.PREPAYMENT_RETURN -> listOf(FundRecordComponent("legacy-return", FundRecordComponentType.PREPAYMENT_RETURN, totalAmount))
        FundRecordType.FINAL_SETTLEMENT -> listOfNotNull(
            debtRepayment.takeIf { it > BigDecimal.ZERO }?.let { FundRecordComponent("legacy-final-settlement", FundRecordComponentType.SETTLEMENT, it) },
            newPrepayment.takeIf { it > BigDecimal.ZERO }?.let { FundRecordComponent("legacy-final-return", FundRecordComponentType.PREPAYMENT_RETURN, it) },
        )
    }
    FundRecord(
        transferId = transferId, activityId = activityId, from = from, to = to, type = legacyType,
        amount = totalAmount, currency = currencyCode, occurredAt = occurredAt, recordedAt = recordedAt,
        recordedBy = recorder, components = components, voidMetadata = null,
        disputes = if (disputed) listOf(
            TransferDispute("legacy-dispute", transferId, from, note ?: "请核对这笔资金记录", "2026-09-02 10:01", disputedBy = recorder),
        ) else emptyList(),
    )
}

/** Read-only financial facts plus explicit backend mutation callbacks. */
@Composable
fun TransferDetailScreen(
    uiState: TransferDetailUiState = TransferDetailUiState(),
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onMore: ((transferId: String) -> Unit)? = null,
    onAddDispute: ((transferId: String, note: String) -> Unit)? = null,
    onResolveDispute: ((disputeId: String) -> Unit)? = null,
    onVoid: ((transferId: String, reason: String) -> Unit)? = null,
    onRecreateCorrectRecord: ((transferId: String) -> Unit)? = null,
) {
    val record = uiState.toFundRecord()
    var dialog by remember { mutableStateOf<DetailDialog?>(null) }
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = Cream,
        topBar = {
            SharedLedgerTopBar(
                title = "资金记录",
                showBackButton = onBack != null,
                onBackClick = onBack,
                onMoreClick = { onMore?.invoke(record.transferId) },
                // The Stitch detail prototype keeps the overflow affordance visible;
                // the host may attach the real action when that menu is wired.
                showMoreButton = true,
                containerColor = Cream,
                titleStyle = SharedLedgerTextStyles.PageTitle,
                titleColor = MaterialTheme.colorScheme.primary,
            )
        },
        bottomBar = {
            DetailActions(
                record = record,
                currentParticipantName = uiState.currentParticipantName,
                onAddDispute = onAddDispute?.let { { dialog = DetailDialog.AddDispute } },
                onResolveDispute = onResolveDispute,
                onVoid = onVoid?.let { { dialog = DetailDialog.VoidRecord } },
                onRecreate = onRecreateCorrectRecord?.let { callback -> { callback(record.transferId) } },
            )
        },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding, vertical = SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Large),
        ) {
            uiState.errorMessage?.let { message ->
                Text("操作未完成：$message", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.error)
            }
            record.unresolvedDisputes.firstOrNull()?.let { dispute ->
                DisputeBanner(dispute, onResolveDispute)
            }
            RecordHero(record)
            ComponentsSection(record.components, record.currency)
            RecorderSection(record)
            record.voidMetadata?.let { VoidSection(it) }
            ResolvedDisputesSection(record.disputes.filter { it.isResolved })
            if (record.type == FundRecordType.FINAL_SETTLEMENT && record.finalSettlementPathSummaries.isNotEmpty()) {
                PathsSection(record)
            }
        }
    }
    when (dialog) {
        DetailDialog.VoidRecord -> ReasonDialog("作废这条记录？", "作废原因（必填）", "确认作废", { dialog = null }) { reason ->
            dialog = null
            onVoid?.invoke(record.transferId, reason)
        }
        DetailDialog.AddDispute -> ReasonDialog("添加争议", "争议说明（必填）", "提交争议", { dialog = null }) { note ->
            dialog = null
            onAddDispute?.invoke(record.transferId, note)
        }
        null -> Unit
    }
}

private sealed interface DetailDialog {
    data object VoidRecord : DetailDialog
    data object AddDispute : DetailDialog
}

@Composable
private fun DisputeBanner(dispute: TransferDispute, onResolve: ((String) -> Unit)?) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.error.copy(alpha = 0.18f)),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Icon(Icons.Rounded.Warning, contentDescription = "有争议", tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(20.dp))
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
                Text("该记录存在争议", style = SharedLedgerTextStyles.Label.copy(fontWeight = FontWeight.Bold))
                Text("争议仅用于提醒双方核对，不会改变当前账务结果", style = SharedLedgerTextStyles.BodySecondary)
                Text("说明：${dispute.note}", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.8f))
            }
            if (onResolve != null) {
                Surface(
                    modifier = Modifier.clickable { onResolve(dispute.disputeId) },
                    shape = SharedLedgerRadius.Full,
                    color = SurfaceWarmLowest.copy(alpha = 0.55f),
                    contentColor = MaterialTheme.colorScheme.error,
                ) {
                    Text("取消争议", style = SharedLedgerTextStyles.Label.copy(fontWeight = FontWeight.Bold), modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp))
                }
            }
        }
    }
}

@Composable
private fun RecordHero(record: FundRecord) {
    DetailSurface(shape = RoundedCornerShape(24.dp), padding = 24.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.weight(1f))
            StatusBadge(if (record.isVoided) "已作废" else "有效", if (record.isVoided) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            PersonWithName(record.from, IconContainerSage)
            Column(
                modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            ) {
                Text(componentFlowLabel(record), style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = "资金流向", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(24.dp))
            }
            PersonWithName(record.to, IconContainerOrange)
        }
        Column(
            modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Large),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        ) {
            Text("总金额 (${record.currency})", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
            AmountDisplay(
                amount = record.amount,
                currencyCode = record.currency,
                size = AmountSize.Large,
                emphasis = if (record.isVoided) AmountEmphasis.Muted else AmountEmphasis.Standard,
                fractionDigitsOverride = 2,
            )
        }
        HorizontalDivider(modifier = Modifier.padding(top = SharedLedgerSpacing.Medium), color = MaterialTheme.colorScheme.surfaceVariant)
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Medium),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Rounded.Schedule, contentDescription = "发生时间", tint = MaterialTheme.colorScheme.outline, modifier = Modifier.size(16.dp))
            Text(record.occurredAt, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.outline, modifier = Modifier.padding(start = SharedLedgerSpacing.Small))
        }
    }
}

@Composable
private fun PersonWithName(person: ParticipantInfo, backgroundColor: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        ParticipantAvatar(name = person.displayName, backgroundColor = backgroundColor, size = 56.dp)
        Text(person.displayName, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurface)
    }
}

private fun componentFlowLabel(record: FundRecord): String {
    val types = record.components.map { it.type }.distinct()
    return when {
        FundRecordType.PREPAYMENT == record.type && FundRecordComponentType.SETTLEMENT in types && FundRecordComponentType.PREPAYMENT in types -> "还款 + 预存"
        types.size == 1 -> types.single().displayName
        else -> record.type.displayName
    }
}

@Composable
private fun ComponentsSection(components: List<FundRecordComponent>, currency: String) {
    DetailSection("资金构成") {
        if (components.isEmpty()) {
            Text("暂无资金构成", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        components.forEachIndexed { index, component ->
            if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            Row(verticalAlignment = Alignment.CenterVertically) {
                val isPrepayment = component.type == FundRecordComponentType.PREPAYMENT
                Surface(
                    modifier = Modifier.size(40.dp),
                    shape = SharedLedgerRadius.Full,
                    color = if (isPrepayment) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = if (isPrepayment) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSecondaryContainer,
                ) {
                    Icon(
                        imageVector = if (isPrepayment) Icons.Rounded.AccountBalanceWallet else Icons.Rounded.History,
                        contentDescription = component.type.displayName,
                        modifier = Modifier.padding(8.dp),
                    )
                }
                Text(component.type.displayName, style = SharedLedgerTextStyles.Body, modifier = Modifier.weight(1f).padding(start = SharedLedgerSpacing.Small))
                AmountDisplay(component.amount, currencyCode = currency, size = AmountSize.Small, fractionDigitsOverride = 2)
            }
        }
    }
}

@Composable
private fun RecorderSection(record: FundRecord) {
    DetailSection("记录详情") {
        DetailRow("记录人", record.recordedBy.displayName)
        record.onBehalfOf?.let { DetailRow("代记对象", it.displayName) }
        DetailRow("记录方式", if (record.onBehalfOf == null) "本人记录" else "代他人记录")
        DetailRow("创建时间", record.recordedAt)
    }
}

@Composable
private fun VoidSection(metadata: VoidMetadata) {
    DetailSection("作废详情") {
        DetailRow("作废人", metadata.voidedBy.displayName)
        DetailRow("作废时间", metadata.voidedAt)
        DetailRow("原因", metadata.reason)
        Text("作废记录仍保留历史，但不参与当前余额。", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.error)
    }
}

@Composable
private fun ResolvedDisputesSection(disputes: List<TransferDispute>) {
    if (disputes.isEmpty()) return
    DetailSection("争议记录") {
        disputes.forEach { dispute ->
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                Icon(Icons.Rounded.Flag, contentDescription = "已解决争议", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
                    Text("已解决 · ${dispute.participant.displayName}", style = SharedLedgerTextStyles.Body)
                    Text(dispute.note, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    dispute.resolvedBy?.let { Text("解决人：${it.displayName}", style = SharedLedgerTextStyles.Label) }
                }
            }
        }
    }
}

@Composable
private fun PathsSection(record: FundRecord) {
    DetailSection("最终结算路径") {
        record.finalSettlementPathSummaries.forEach { path ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Route, contentDescription = "结算路径", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(22.dp))
                Column(modifier = Modifier.weight(1f).padding(start = SharedLedgerSpacing.Small)) {
                    Text("路径 ${path.pathNo}：${path.from.displayName} → ${path.to.displayName}", style = SharedLedgerTextStyles.Body)
                    Text("${path.hopCount} 跳 · ${path.componentType.displayName}", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                AmountDisplay(path.endpointAmount, currencyCode = record.currency, size = AmountSize.Small, fractionDigitsOverride = 2)
            }
        }
        Text("路径明细用于解释结算来源，不会重复计入总金额。", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun DetailActions(
    record: FundRecord,
    currentParticipantName: String?,
    onAddDispute: (() -> Unit)?,
    onResolveDispute: ((String) -> Unit)?,
    onVoid: (() -> Unit)?,
    onRecreate: (() -> Unit)?,
) {
    Column(
        modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = SharedLedgerDimens.PageHorizontalPadding, vertical = SharedLedgerSpacing.Small),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        if (record.isVoided) {
            onRecreate?.let { SharedLedgerButton("重新创建正确记录", it, tone = SharedLedgerButtonTone.SoftPrimary, icon = Icons.Rounded.Refresh) }
        } else if (record.hasUnresolvedDispute) {
            val dispute = record.unresolvedDisputes.first()
            onResolveDispute?.let { callback ->
                SharedLedgerButton("取消争议", { callback(dispute.disputeId) }, tone = SharedLedgerButtonTone.Success, icon = Icons.Rounded.Flag)
            }
        } else {
            if (currentParticipantName != null && onAddDispute != null) {
                SharedLedgerButton("添加争议", onAddDispute, tone = SharedLedgerButtonTone.WarmSecondary, icon = Icons.Rounded.Flag)
            }
            onVoid?.let { SharedLedgerButton("作废记录", it, tone = SharedLedgerButtonTone.Danger, outlined = true, icon = Icons.Rounded.Block) }
        }
    }
}

@Composable
private fun ReasonDialog(title: String, label: String, confirmLabel: String, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var value by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { OutlinedTextField(value, { value = it }, label = { Text(label) }, modifier = Modifier.fillMaxWidth(), minLines = 3) },
        confirmButton = { TextButton(onClick = { if (value.isNotBlank()) onConfirm(value.trim()) }, enabled = value.isNotBlank()) { Text(confirmLabel) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
private fun DetailSection(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) {
        Text(title, style = SharedLedgerTextStyles.SectionTitle, modifier = Modifier.padding(horizontal = 4.dp))
        DetailSurface(shape = RoundedCornerShape(20.dp), padding = 20.dp, content = content)
    }
}

@Composable
private fun DetailSurface(
    shape: RoundedCornerShape,
    padding: androidx.compose.ui.unit.Dp,
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = shape,
        color = SurfaceWarmLowest,
        shadowElevation = SharedLedgerElevation.Card,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)),
    ) {
        Column(modifier = Modifier.padding(padding), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) { content() }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = SharedLedgerTextStyles.BodySecondary, modifier = Modifier.weight(1f).padding(start = SharedLedgerSpacing.Medium), textAlign = TextAlign.End)
    }
}

@Composable
private fun StatusBadge(label: String, color: Color) {
    Surface(
        shape = SharedLedgerRadius.Full,
        color = if (label == "有效") MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
        contentColor = color,
    ) {
        Row(modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Icon(if (label == "有效") Icons.Rounded.CheckCircle else Icons.Rounded.Block, contentDescription = label, modifier = Modifier.size(14.dp))
            Text(label, style = SharedLedgerTextStyles.Label.copy(fontWeight = FontWeight.Bold))
        }
    }
}

@Preview(name = "资金详情 - Fake", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun TransferDetailPreview() {
    val fakeRecord = when (val result = FakeFinancialRecordRepository().get("fake-preview-activity", "fake-final-001")) {
        is FinancialReadResult.Success -> result.value
        is FinancialReadResult.Failure -> error(result.message)
    }
    SharedLedgerTheme { TransferDetailScreen(TransferDetailUiState(record = fakeRecord)) }
}
