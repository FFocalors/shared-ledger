package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.CurrencyExchange
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.BottomActionItem
import com.ffocalors.sharedledger.ui.components.ExpenseCard
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.components.ExpenseActionSheet
import com.ffocalors.sharedledger.ui.components.PaymentStatusCard
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.SettlementStatistic
import com.ffocalors.sharedledger.ui.components.SettlementSummaryCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerBottomActionBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.Cream
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import java.math.BigDecimal
import com.ffocalors.sharedledger.data.activity.ActivityDetail

data class LedgerAttachmentUiState(
    val attachmentId: String,
    val fileName: String,
    val sizeLabel: String = "",
    val status: LedgerAttachmentStatus = LedgerAttachmentStatus.Ready,
    val errorMessage: String? = null,
    val canDelete: Boolean = true,
)

enum class LedgerAttachmentStatus {
    Uploading,
    Ready,
    Failed,
}

private val PreviewLedgerUnitParticipants = listOf(
    ParticipantUiModel("张三", IconContainerSage),
    ParticipantUiModel("李四", WarmOrangeContainer),
    ParticipantUiModel("王五"),
)

private val PreviewTicketLedgerUnitExpenses = listOf(
    ExpenseCardUiModel(
        name = "东京塔门票",
        amount = BigDecimal("120.0"),
        payerName = "张三",
        participantCount = 3,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.TICKET_EXPENSE,
    ),
    ExpenseCardUiModel(
        name = "浅草寺导览",
        amount = BigDecimal("850.0"),
        payerName = "李四",
        participantCount = 3,
        participants = PreviewLedgerUnitParticipants,
        currencyCode = "CNY",
        expenseId = "demo-expense-asakusa",
        isDeleted = true,
    ),
    ExpenseCardUiModel(
        name = "迪士尼快速通票",
        amount = BigDecimal("1200.0"),
        payerName = "我",
        participantCount = 2,
        participants = listOf(PreviewLedgerUnitParticipants[0], PreviewLedgerUnitParticipants[2]),
        currencyCode = "CNY",
        expenseId = "demo-expense-disney",
    ),
)

/**
 * 大型活动中的独立 Ledger，页面内容由 [ledgerUnitId] 选择，导航意图通过回调交给宿主处理。
 */
@Composable
fun LedgerUnitScreen(
    activityId: String = "",
    ledgerUnitId: String = "",
    ledgerUnitTitle: String? = null,
    activity: ActivityDetail? = null,
    isLoading: Boolean = false,
    errorMessage: String? = null,
    expenses: List<ExpenseCardUiModel> = emptyList(),
    totalBaseAmount: BigDecimal? = null,
    participantBound: Boolean = false,
    expenseLoading: Boolean = false,
    expenseErrorMessage: String? = null,
    onExpenseRetry: () -> Unit = {},
    onRetry: () -> Unit = {},
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onTransfer: (() -> Unit)? = {},
    onNewExpense: (() -> Unit)? = {},
    onRefund: (() -> Unit)? = {},
    onReceive: (() -> Unit)? = {},
    onFundRecords: () -> Unit = {},
    onExpenseClick: (String) -> Unit = {},
    attachments: List<LedgerAttachmentUiState> = emptyList(),
    onAddAttachment: (() -> Unit)? = null,
    onAttachmentClick: ((attachmentId: String) -> Unit)? = null,
    onDeleteAttachment: ((attachmentId: String) -> Unit)? = null,
    onRetryAttachment: ((attachmentId: String) -> Unit)? = null,
    attachmentMessage: String? = null,
) {
    val displayTitle = ledgerUnitTitle?.takeIf { it.isNotBlank() }
        ?: activity?.ledgerUnits?.firstOrNull { it.id == ledgerUnitId }?.name
        ?: "子活动"
    val displayTotal = totalBaseAmount
    val displayUsers = activity?.members?.mapIndexed { index, member ->
        ParticipantUiModel(
            name = member.displayName,
            backgroundColor = if (index % 2 == 0) IconContainerSage else WarmOrangeContainer,
        )
    } ?: emptyList()
    var expenseActionSheetVisible by remember { mutableStateOf(false) }
    Scaffold(
        modifier = modifier.fillMaxSize(),
        // Stitch’s LedgerUnit frame uses the warm cream layer outside the cards.
        containerColor = Cream,
        topBar = {
            SharedLedgerTopBar(
                title = displayTitle,
                showBackButton = true,
                onBackClick = onBack,
                containerColor = Cream,
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
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        top = SharedLedgerSpacing.Medium,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = SharedLedgerSpacing.Large,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerBottomActionBar(
                    actions = listOf(
                        onTransfer?.let { BottomActionItem("转账", Icons.Rounded.SwapHoriz, it) },
                        if (onNewExpense != null || onRefund != null) {
                            BottomActionItem("记一笔", Icons.Rounded.Add) {
                                expenseActionSheetVisible = true
                            }
                        } else null,
                        onReceive?.let { BottomActionItem("收款", Icons.Rounded.RequestQuote, it) },
                    ).filterNotNull(),
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
                    .fillMaxWidth(),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Medium,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                if (isLoading || errorMessage != null || expenseLoading || expenseErrorMessage != null) {
                    item(key = "ledger-state") {
                        LedgerUnitStateMessage(
                            isLoading = isLoading || expenseLoading,
                            errorMessage = errorMessage ?: expenseErrorMessage,
                            onRetry = if (errorMessage != null) onRetry else onExpenseRetry,
                        )
                    }
                } else {
                    item(key = "overview") {
                        Column(
                            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            SettlementSummaryCard(
                                title = "实际消费",
                                primaryAmount = displayTotal?.takeIf { participantBound },
                                secondaryTitle = "待结算",
                                secondaryAmount = activity?.summary?.totalDebt?.toBigDecimalOrNull() ?: BigDecimal.ZERO,
                                currencyCode = activity?.summary?.baseCurrency ?: "CNY",
                                statistics = listOf(
                                    SettlementStatistic(
                                        "参与人",
                                        "${activity?.participants?.size ?: 0} 人",
                                    ),
                                ),
                            )
                            SharedLedgerButton(
                                text = "资金记录",
                                onClick = onFundRecords,
                                tone = SharedLedgerButtonTone.Neutral,
                                icon = Icons.Rounded.History,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            LedgerUnitAttachments(
                                attachments = attachments,
                                onAddAttachment = onAddAttachment,
                                onAttachmentClick = onAttachmentClick,
                                onDeleteAttachment = onDeleteAttachment,
                                onRetryAttachment = onRetryAttachment,
                            )
                            attachmentMessage?.let {
                                Text(it, style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                    item(key = "today") {
                        LedgerUnitExpenseSection(
                            title = "今天",
                            expenses = expenses,
                            onExpenseClick = onExpenseClick,
                        )
                    }
                }
            }
        }
    }
    if (expenseActionSheetVisible) {
        ExpenseActionSheet(
            onDismiss = { expenseActionSheetVisible = false },
            onNewExpense = onNewExpense,
            onRefund = onRefund,
        )
    }
}

@Composable
private fun LedgerUnitAttachments(
    attachments: List<LedgerAttachmentUiState>,
    onAddAttachment: (() -> Unit)?,
    onAttachmentClick: ((String) -> Unit)?,
    onDeleteAttachment: ((String) -> Unit)?,
    onRetryAttachment: ((String) -> Unit)?,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("附件 (${attachments.size}/10)", modifier = Modifier.weight(1f), style = SharedLedgerTextStyles.SectionTitle)
            onAddAttachment?.let { callback ->
                androidx.compose.material3.TextButton(
                    onClick = callback,
                    enabled = attachments.size < 10,
                ) {
                    Icon(Icons.Rounded.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                    Text("添加")
                }
            }
        }
        if (attachments.isEmpty()) {
            Text("暂无附件", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            attachments.forEach { attachment ->
                LedgerAttachmentRow(
                    attachment = attachment,
                    onClick = onAttachmentClick?.let { callback -> { callback(attachment.attachmentId) } },
                    onDelete = onDeleteAttachment?.takeIf { attachment.canDelete }?.let { callback -> { callback(attachment.attachmentId) } },
                    onRetry = onRetryAttachment?.let { callback -> { callback(attachment.attachmentId) } },
                )
            }
        }
    }
}

@Composable
private fun LedgerAttachmentRow(
    attachment: LedgerAttachmentUiState,
    onClick: (() -> Unit)?,
    onDelete: (() -> Unit)?,
    onRetry: (() -> Unit)?,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .then(onClick?.let { Modifier.clickable(onClick = it) } ?: Modifier),
        shape = com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius.Medium,
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Icon(Icons.Rounded.Image, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Column(modifier = Modifier.weight(1f)) {
                Text(attachment.fileName, style = SharedLedgerTextStyles.BodySecondary)
                val statusText = when (attachment.status) {
                    LedgerAttachmentStatus.Uploading -> "上传中…"
                    LedgerAttachmentStatus.Ready -> attachment.sizeLabel.ifBlank { "已上传" }
                    LedgerAttachmentStatus.Failed -> attachment.errorMessage ?: "上传失败"
                }
                Text(statusText, style = SharedLedgerTextStyles.Label, color = if (attachment.status == LedgerAttachmentStatus.Failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (attachment.status == LedgerAttachmentStatus.Failed) {
                onRetry?.let { callback ->
                    IconButton(onClick = callback, modifier = Modifier.size(36.dp)) {
                        Icon(Icons.Rounded.Refresh, contentDescription = "重试上传${attachment.fileName}", modifier = Modifier.size(18.dp))
                    }
                }
            }
            onDelete?.let { callback ->
                IconButton(onClick = callback, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Rounded.Delete, contentDescription = "删除${attachment.fileName}", modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}

@Composable
private fun LedgerUnitStateMessage(
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
            Text("正在加载子活动…", style = SharedLedgerTextStyles.BodySecondary)
        } else {
            Text(errorMessage ?: "子活动加载失败", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.error)
            SharedLedgerButton(
                text = "重试",
                onClick = onRetry,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Composable
private fun LedgerUnitExpenseSection(
    title: String,
    expenses: List<ExpenseCardUiModel>,
    onExpenseClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Text(
            text = title,
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onBackground,
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.XSmall),
        )
        if (expenses.isEmpty()) {
            Text("暂无账单", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            expenses.forEach { expense ->
                ExpenseCard(
                    expense = expense,
                    icon = Icons.AutoMirrored.Rounded.ReceiptLong,
                    onClick = { onExpenseClick(expense.expenseId) },
                )
            }
        }
    }
}

@Preview(name = "子活动详情", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun LedgerUnitScreenPreview() {
    SharedLedgerTheme {
        LedgerUnitScreen(
            activityId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.LARGE_ACTIVITY,
            ledgerUnitId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.TICKET_LEDGER,
            ledgerUnitTitle = "门票",
            expenses = PreviewTicketLedgerUnitExpenses,
            totalBaseAmount = PreviewTicketLedgerUnitExpenses.sumOf { it.amount },
            participantBound = true,
        )
    }
}
