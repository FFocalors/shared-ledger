package com.ffocalors.sharedledger.ui.screens


import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.CurrencyExchange
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.Payments
import androidx.compose.material.icons.rounded.PieChart
import androidx.compose.material.icons.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.R
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmHigh
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.WarmBrown
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.util.MoneyFormatter

/** The state needed to render one expense. [expenseId] is the stable identity used by callbacks. */
@Immutable
data class ExpenseDetailUiState(
    val expenseId: String = "",
    val title: String = "",
    val merchant: String = "",
    val amount: String = "",
    val currencyCode: String = "",
    val originalAmount: String = "",
    val originalCurrencyCode: String = "",
    val occurredAt: String = "",
    val ledgerUnit: String = "",
    val note: String = "",
    val payments: List<ExpensePaymentUiState> = emptyList(),
    val splitMethod: ExpenseSplitMethodUi = ExpenseSplitMethodUi.Aa,
    val splits: List<ExpenseSplitUiState> = emptyList(),
    val attachments: List<ExpenseAttachmentUiState> = emptyList(),
    val status: ExpenseDetailStatus = ExpenseDetailStatus.Deleted,
    val actionMessage: String? = null,
    val attachmentMessage: String? = null,
)

@Immutable
data class ExpensePaymentUiState(
    val participant: String,
    val amount: String,
    val isCurrentUser: Boolean = false,
)

@Immutable
data class ExpenseSplitUiState(
    val participant: String,
    val owedAmount: String,
    val settlement: ExpenseSettlement = ExpenseSettlement.Pending,
    val paidAmount: String? = null,
    val netAdvance: String? = null,
    val isCurrentUser: Boolean = false,
    val isPayer: Boolean = false,
)

enum class ExpenseSplitMethodUi {
    Aa,
    Manual,
}

@Immutable
data class ExpenseAttachmentUiState(
    val attachmentId: String,
    val fileName: String,
    val label: String = fileName,
    val sizeLabel: String = "",
    val status: ExpenseAttachmentStatus = ExpenseAttachmentStatus.Ready,
    val errorMessage: String? = null,
    val canDelete: Boolean = true,
)

enum class ExpenseAttachmentStatus {
    Uploading,
    Ready,
    Failed,
}

enum class ExpenseDetailStatus {
    Active,
    Deleted,
}

enum class ExpenseSettlement {
    Pending,
    Paid,
}

private fun previewExpenseSplits() = listOf(
    ExpenseSplitUiState(participant = "Bob", owedAmount = "150", settlement = ExpenseSettlement.Pending),
    ExpenseSplitUiState(participant = "Carol", owedAmount = "150", settlement = ExpenseSettlement.Paid),
    ExpenseSplitUiState(
        participant = "Alice",
        owedAmount = "150",
        paidAmount = "450",
        netAdvance = "300",
        isPayer = true,
    ),
)

private val PreviewExpenseDetail = ExpenseDetailUiState(
    expenseId = "expense-demo-dinner-20231024",
    title = "晚餐",
    merchant = "新光天地",
    amount = "450.00",
    currencyCode = "CNY",
    originalAmount = "450.00",
    originalCurrencyCode = "CNY",
    occurredAt = "2023年10月24日 19:30",
    ledgerUnit = "周末聚餐",
    note = "庆祝项目上线聚餐",
    payments = listOf(ExpensePaymentUiState("Alice", "450", isCurrentUser = true)),
    splitMethod = ExpenseSplitMethodUi.Aa,
    splits = previewExpenseSplits(),
)

/**
 * 账单详情页。页面只拥有底部操作抽屉的展示状态，业务状态由 [uiState] 提供，
 * 所有业务操作都通过稳定的 [ExpenseDetailUiState.expenseId] 回调给宿主。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseDetailScreen(
    uiState: ExpenseDetailUiState,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    onEdit: ((expenseId: String) -> Unit)? = null,
    onVoid: ((expenseId: String) -> Unit)? = null,
    onRestore: ((expenseId: String) -> Unit)? = null,
    onAddRefund: ((expenseId: String) -> Unit)? = null,
    onRefreshConfirmation: (() -> Unit)? = null,
    onAttachmentClick: ((expenseId: String, attachmentId: String) -> Unit)? = null,
    onAttachmentDelete: ((expenseId: String, attachmentId: String) -> Unit)? = null,
) {
    var sheetVisible by rememberSaveable(uiState.expenseId) { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val snackbarHostState = androidx.compose.runtime.remember(uiState.expenseId) { SnackbarHostState() }

    LaunchedEffect(uiState.actionMessage) {
        uiState.actionMessage?.let { snackbarHostState.showSnackbar(it) }
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            SharedLedgerTopBar(
                title = "账单详情",
                showBackButton = onBack != null,
                onBackClick = onBack,
                containerColor = AppBackground,
                titleStyle = SharedLedgerTextStyles.PageTitle,
                titleColor = MaterialTheme.colorScheme.primary,
                showMoreButton = false,
                 actionIcon = Icons.Rounded.Edit.takeIf { uiState.status == ExpenseDetailStatus.Active && onEdit != null },
                 actionContentDescription = "编辑账单".takeIf { uiState.status == ExpenseDetailStatus.Active && onEdit != null },
                 onActionClick = onEdit?.let { callback -> { callback(uiState.expenseId) } }
                     .takeIf { uiState.status == ExpenseDetailStatus.Active },
            )
        },
        bottomBar = {
            val primaryAction = if (uiState.status == ExpenseDetailStatus.Deleted) {
                onRestore?.let { callback -> { callback(uiState.expenseId) } }
            } else {
                onVoid?.let { callback -> { callback(uiState.expenseId) } }
            }
            val hasMoreActions = if (uiState.status == ExpenseDetailStatus.Active) {
                onEdit != null || onAddRefund != null || onVoid != null
            } else {
                onAddRefund != null
            }
            if (primaryAction != null || hasMoreActions) {
                ExpenseDetailBottomBar(
                    status = uiState.status,
                    onPrimaryAction = primaryAction,
                    onMore = { sheetVisible = true }.takeIf { hasMoreActions },
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
                    .fillMaxWidth()
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding() + 24.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
            ) {
                onRefreshConfirmation?.let { callback ->
                    item(key = "refresh-confirmation") {
                        Card(
                            modifier = Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                        ) {
                            Column(
                                modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                            ) {
                                Text("账单写入状态待确认", style = SharedLedgerTextStyles.CardTitle)
                                Text(
                                    "请先刷新账单详情，确认后才能继续提交操作。",
                                    style = SharedLedgerTextStyles.BodySecondary,
                                )
                                SharedLedgerButton(
                                    "刷新确认",
                                    callback,
                                    tone = SharedLedgerButtonTone.SoftPrimary,
                                    icon = Icons.Rounded.Refresh,
                                )
                            }
                        }
                    }
                }
                item(key = "hero") {
                    ExpenseHeroCard(uiState = uiState)
                }
                item(key = "payment") {
                    ExpenseSection(title = "付款信息", icon = Icons.Rounded.Payments) {
                        PaymentCard(uiState = uiState)
                    }
                }
                item(key = "split") {
                    ExpenseSection(
                        title = "分摊详情",
                        icon = Icons.Rounded.PieChart,
                        badge = when (uiState.splitMethod) {
                            ExpenseSplitMethodUi.Aa -> "AA 平摊"
                            ExpenseSplitMethodUi.Manual -> "手动分摊"
                        },
                    ) {
                        SplitCard(splits = uiState.splits, currencyCode = uiState.currencyCode)
                    }
                }
                item(key = "attachments") {
                    ExpenseSection(title = "消费凭证", icon = Icons.Rounded.ReceiptLong) {
                        AttachmentsRow(
                            attachments = uiState.attachments,
                            onAttachmentClick = onAttachmentClick?.let { callback ->
                                { attachmentId -> callback(uiState.expenseId, attachmentId) }
                            },
                            onAttachmentDelete = onAttachmentDelete?.let { callback ->
                                { attachmentId -> callback(uiState.expenseId, attachmentId) }
                            },
                        )
                        uiState.attachmentMessage?.let {
                            Text(it, style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
        }
    }

    if (sheetVisible) {
        ModalBottomSheet(
            onDismissRequest = { sheetVisible = false },
            sheetState = sheetState,
            containerColor = SurfaceWarmLowest,
        ) {
            ExpenseActionSheet(
                status = uiState.status,
                 onEdit = onEdit?.let { callback -> {
                     sheetVisible = false
                     callback(uiState.expenseId)
                 } },
                 onVoid = onVoid?.let { callback -> {
                     sheetVisible = false
                     callback(uiState.expenseId)
                 } },
                 onAddRefund = onAddRefund?.let { callback -> {
                     sheetVisible = false
                     callback(uiState.expenseId)
                 } },
            )
        }
    }

}

@Composable
private fun ExpenseHeroCard(uiState: ExpenseDetailUiState) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
            .padding(SharedLedgerSpacing.Large),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (uiState.status == ExpenseDetailStatus.Deleted) {
                Surface(
                    shape = SharedLedgerRadius.Full,
                    color = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                ) {
                    Text(
                        text = "已删除",
                        style = SharedLedgerTextStyles.Label,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
                Spacer(Modifier.height(12.dp))
            }
            Surface(
                modifier = Modifier.size(48.dp),
                shape = CircleShape,
                color = MaterialTheme.colorScheme.primaryContainer,
                contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(Icons.Rounded.Restaurant, contentDescription = "餐饮", modifier = Modifier.size(32.dp))
                }
            }
            Spacer(Modifier.height(16.dp))
            Text(
                text = if (uiState.merchant.isBlank()) uiState.title else "${uiState.title} (${uiState.merchant})",
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = formatExpenseDetailAmount(uiState.amount, uiState.currencyCode),
                modifier = Modifier.padding(top = 2.dp),
                style = SharedLedgerTextStyles.AmountLarge,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                text = "基础币: ${formatExpenseDetailAmount(uiState.amount, uiState.currencyCode)} | 原币: ${formatExpenseDetailAmount(uiState.originalAmount, uiState.originalCurrencyCode)}",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Rounded.Schedule, contentDescription = "消费时间", modifier = Modifier.size(16.dp))
                Text(uiState.occurredAt, style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (uiState.note.isNotBlank()) {
                Text(
                    text = "\"${uiState.note}\"",
                    modifier = Modifier.padding(top = 8.dp),
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ExpenseSection(
    title: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    badge: String? = null,
    content: @Composable () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(bottom = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
            Text(title, style = SharedLedgerTextStyles.SectionTitle, color = MaterialTheme.colorScheme.primary)
            if (badge != null) {
                Surface(shape = RoundedCornerShape(4.dp), color = WarmOrangeContainer) {
                    Text(
                        badge,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                        style = SharedLedgerTextStyles.Label,
                        color = WarmBrown,
                    )
                }
            }
        }
        content()
    }
}

private fun expenseAvatarRes(name: String, isPayer: Boolean = false): Int = when {
    name == "Alice" && isPayer -> R.drawable.alice_split_avatar
    name == "Alice" -> R.drawable.alice_avatar
    name == "Bob" -> R.drawable.bob_avatar
    name == "Carol" -> R.drawable.carol_avatar
    else -> R.drawable.alice_avatar
}

@Composable
private fun PaymentCard(uiState: ExpenseDetailUiState) {
    DetailCard {
        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            uiState.payments.forEachIndexed { index, payment ->
                if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ParticipantAvatar(
                        name = payment.participant,
                        image = painterResource(expenseAvatarRes(payment.participant, isPayer = true)),
                        size = SharedLedgerDimens.AvatarMedium,
                    )
                    Column(modifier = Modifier.padding(start = 12.dp).weight(1f)) {
                        Text(
                            text = payment.participant + if (payment.isCurrentUser) "（我）" else "",
                            style = SharedLedgerTextStyles.Body,
                            fontWeight = FontWeight.Medium,
                        )
                        Text("垫付方", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(
                        formatExpenseDetailAmount(payment.amount, uiState.currencyCode),
                        style = SharedLedgerTextStyles.Body,
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
        }
    }
}

internal fun formatExpenseDetailAmount(amount: String, currencyCode: String): String {
    val normalizedCode = currencyCode.trim().uppercase()
    val decimal = amount.toBigDecimalOrNull()
    return if (decimal != null) {
        MoneyFormatter.format(decimal, normalizedCode)
    } else {
        "$normalizedCode $amount".trim()
    }
}

@Composable
private fun SplitCard(splits: List<ExpenseSplitUiState>, currencyCode: String) {
    DetailCard {
        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            splits.forEachIndexed { index, split ->
                if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                SplitRow(split, currencyCode)
            }
        }
    }
}

@Composable
private fun SplitRow(split: ExpenseSplitUiState, currencyCode: String) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ParticipantAvatar(
                name = split.participant,
                image = painterResource(expenseAvatarRes(split.participant, split.isPayer)),
                size = SharedLedgerDimens.AvatarMedium,
            )
            Row(
                modifier = Modifier.padding(start = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(split.participant + if (split.isCurrentUser) "（我）" else "", style = SharedLedgerTextStyles.Body, fontWeight = FontWeight.Medium)
                if (split.isPayer) {
                    Surface(shape = RoundedCornerShape(4.dp), color = SurfaceWarmHigh) {
                        Text("垫付方", modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp), style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        val statusText = when (split.settlement) {
            ExpenseSettlement.Pending -> "当前未结清"
            ExpenseSettlement.Paid -> "已结清"
        }
        val statusColor = if (split.settlement == ExpenseSettlement.Pending) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary
        val detail = buildAnnotatedString {
            append("应承担 ${formatExpenseDetailAmount(split.owedAmount, currencyCode)}")
            if (split.paidAmount != null) append("，实际支付 ${formatExpenseDetailAmount(split.paidAmount, currencyCode)}")
            if (split.netAdvance != null) append("，净垫付 ${formatExpenseDetailAmount(split.netAdvance, currencyCode)}")
            append("，")
            pushStyle(SpanStyle(color = statusColor, fontWeight = FontWeight.Medium))
            append(statusText)
            pop()
            append("。")
        }
        Text(
            text = detail,
            modifier = Modifier.padding(start = 52.dp),
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun AttachmentsRow(
    attachments: List<ExpenseAttachmentUiState>,
    onAttachmentClick: ((attachmentId: String) -> Unit)?,
    onAttachmentDelete: ((attachmentId: String) -> Unit)?,
) {
    if (attachments.isEmpty()) {
        Text("暂无附件", style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
    } else {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            attachments.forEach { attachment ->
                AttachmentCard(
                    attachment = attachment,
                    onClick = onAttachmentClick?.let { callback -> { callback(attachment.attachmentId) } },
                    onDelete = onAttachmentDelete?.takeIf { attachment.canDelete }?.let { callback -> { callback(attachment.attachmentId) } },
                )
            }
        }
    }
}

@Composable
private fun AttachmentCard(
    attachment: ExpenseAttachmentUiState,
    onClick: (() -> Unit)?,
    onDelete: (() -> Unit)?,
) {
    Surface(
        modifier = Modifier
            .width(180.dp)
            .height(116.dp)
            .clip(SharedLedgerRadius.Medium)
            .then(onClick?.let { callback -> Modifier.clickable(onClick = callback) } ?: Modifier)
            .then(onClick?.let { Modifier.semantics { contentDescription = "查看${attachment.label}" } } ?: Modifier),
        shape = SharedLedgerRadius.Medium,
        color = Color(0xFFF1E8D9),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier.fillMaxSize().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Image, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Text(attachment.fileName, modifier = Modifier.weight(1f), maxLines = 1, style = SharedLedgerTextStyles.Label)
                onDelete?.let { callback ->
                    IconButton(onClick = callback, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Rounded.Delete, contentDescription = "删除${attachment.fileName}", modifier = Modifier.size(18.dp))
                    }
                }
            }
            val statusText = when (attachment.status) {
                ExpenseAttachmentStatus.Uploading -> "上传中…"
                ExpenseAttachmentStatus.Ready -> attachment.sizeLabel.ifBlank { "已上传" }
                ExpenseAttachmentStatus.Failed -> attachment.errorMessage ?: "加载失败"
            }
            Text(statusText, style = SharedLedgerTextStyles.Label, color = if (attachment.status == ExpenseAttachmentStatus.Failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            Text("点击查看附件", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun DetailCard(content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(SharedLedgerElevation.Card),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            content()
        }
    }
}

@Composable
private fun ExpenseDetailBottomBar(
    status: ExpenseDetailStatus,
    onPrimaryAction: (() -> Unit)?,
    onMore: (() -> Unit)?,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = com.ffocalors.sharedledger.ui.theme.SurfaceWarmContainer.copy(alpha = 0.9f),
        shadowElevation = 8.dp,
        shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
        border = BorderStroke(
            width = SharedLedgerDimens.OutlineWidth,
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.75f),
        ),
    ) {
        Row(
            modifier = Modifier
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(start = 16.dp, top = 12.dp, end = 16.dp, bottom = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            onPrimaryAction?.let { callback ->
                SharedLedgerButton(
                    text = if (status == ExpenseDetailStatus.Deleted) "恢复账单" else "作废账单",
                    onClick = callback,
                    modifier = Modifier.weight(1f),
                    tone = if (status == ExpenseDetailStatus.Deleted) {
                        SharedLedgerButtonTone.SoftPrimary
                    } else {
                        SharedLedgerButtonTone.Danger
                    },
                    icon = if (status == ExpenseDetailStatus.Deleted) Icons.Rounded.Refresh else Icons.Rounded.Delete,
                )
            }
            onMore?.let { callback ->
                IconButton(
                    onClick = callback,
                    modifier = Modifier
                        .size(52.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant, CircleShape)
                        .semantics { contentDescription = "更多账单操作" },
                ) {
                    Icon(Icons.Rounded.MoreVert, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

@Composable
private fun ExpenseActionSheet(
    status: ExpenseDetailStatus,
    onEdit: (() -> Unit)?,
    onVoid: (() -> Unit)?,
    onAddRefund: (() -> Unit)?,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 24.dp, end = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            modifier = Modifier
                .align(Alignment.CenterHorizontally)
                .size(width = 48.dp, height = 6.dp)
                .background(MaterialTheme.colorScheme.outlineVariant, CircleShape),
        )
        Spacer(Modifier.height(8.dp))
        if (status == ExpenseDetailStatus.Active) {
            onEdit?.let { callback -> ActionSheetButton(Icons.Rounded.Edit, "编辑账单", SharedLedgerButtonTone.Neutral, outlined = true, onClick = callback) }
            onAddRefund?.let { callback -> ActionSheetButton(Icons.Rounded.CurrencyExchange, "添加退款", SharedLedgerButtonTone.WarmSecondary, onClick = callback) }
            onVoid?.let { callback -> ActionSheetButton(Icons.Rounded.Delete, "作废账单", SharedLedgerButtonTone.Danger, onClick = callback) }
        } else {
            onAddRefund?.let { callback -> ActionSheetButton(Icons.Rounded.CurrencyExchange, "添加退款", SharedLedgerButtonTone.WarmSecondary, onClick = callback) }
        }
    }
}

@Composable
private fun ActionSheetButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    tone: SharedLedgerButtonTone,
    outlined: Boolean = false,
    onClick: () -> Unit,
) {
    SharedLedgerButton(
        text = label,
        onClick = onClick,
        tone = tone,
        icon = icon,
        outlined = outlined,
    )
}

@Preview(showBackground = true, widthDp = 480, heightDp = 900)
@Composable
private fun ExpenseDetailScreenPreview() {
    SharedLedgerTheme {
        ExpenseDetailScreen(uiState = PreviewExpenseDetail)
    }
}

@Preview(showBackground = true, widthDp = 480, heightDp = 900)
@Composable
private fun ActiveExpenseDetailScreenPreview() {
    SharedLedgerTheme {
        ExpenseDetailScreen(
            uiState = PreviewExpenseDetail.copy(status = ExpenseDetailStatus.Active),
        )
    }
}
