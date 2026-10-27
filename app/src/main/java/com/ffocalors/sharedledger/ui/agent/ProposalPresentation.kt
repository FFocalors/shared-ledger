package com.ffocalors.sharedledger.ui.agent

import com.ffocalors.sharedledger.data.agent.AmountField
import com.ffocalors.sharedledger.data.agent.CanonicalEqualSplit
import com.ffocalors.sharedledger.data.agent.CanonicalManualSplit
import com.ffocalors.sharedledger.data.agent.CanonicalPayment
import com.ffocalors.sharedledger.data.agent.CanonicalSplit
import com.ffocalors.sharedledger.data.agent.ExpenseAmountChange
import com.ffocalors.sharedledger.data.agent.ExpenseChange
import com.ffocalors.sharedledger.data.agent.ExpenseCurrencyChange
import com.ffocalors.sharedledger.data.agent.ExpenseFxChange
import com.ffocalors.sharedledger.data.agent.ExpenseIconChange
import com.ffocalors.sharedledger.data.agent.ExpenseLedgerUnitChange
import com.ffocalors.sharedledger.data.agent.ExpenseNoteChange
import com.ffocalors.sharedledger.data.agent.ExpenseOccurredAtChange
import com.ffocalors.sharedledger.data.agent.ExpensePaymentsChange
import com.ffocalors.sharedledger.data.agent.ExpensePreview
import com.ffocalors.sharedledger.data.agent.ExpenseSplitChange
import com.ffocalors.sharedledger.data.agent.ExpenseTitleChange
import com.ffocalors.sharedledger.data.agent.FinalSettlementPreview
import com.ffocalors.sharedledger.data.agent.FxSnapshot
import com.ffocalors.sharedledger.data.agent.ManagementPreview
import com.ffocalors.sharedledger.data.agent.NegativeAdjustmentPreview
import com.ffocalors.sharedledger.data.agent.PrepaymentPreview
import com.ffocalors.sharedledger.data.agent.PrepaymentReturnPreview
import com.ffocalors.sharedledger.data.agent.ProposalOperation
import com.ffocalors.sharedledger.data.agent.ProposalPreview
import com.ffocalors.sharedledger.data.agent.ProposalStatus
import com.ffocalors.sharedledger.data.agent.RefundPreview
import com.ffocalors.sharedledger.data.agent.RepaymentPreview
import com.ffocalors.sharedledger.data.agent.TransferVoidPreview
import com.ffocalors.sharedledger.data.agent.TurnState
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter

/** One change row in a draft: a Chinese field label and the value (`before → after` when updating). */
data class DraftRow(val label: String, val before: String?, val after: String)

/**
 * What a draft card body shows, whichever preview kind arrived. [fallback] is true for a preview kind
 * this client does not know yet; the body then shows only the server's own summary.
 */
data class PreviewView(
    val title: String,
    val amount: String?,
    val rows: List<DraftRow>,
    val note: String?,
    val fallback: Boolean = false,
)

object ProposalPresentation {
    const val SIMULATION_NOTICE = "演示数据，不会记账"
    const val SIMULATION_CONFIRM_NOTE = "演示数据只用于预览，不会写入账本。"
    const val CONFIRM_LABEL = "确认记账"
    const val CONFIRMING_LABEL = "确认中…"
    const val CONFIRM_NOTE = "确认后会立即记入账本。"
    const val EXECUTION_UNAVAILABLE = "执行暂不可用"
    const val RECEIPT_PREFIX = "已提交执行 · 回执"
    const val EXECUTING_LABEL = "执行中"
    const val RECONCILING_LABEL = "正在核对结果"

    fun operationTitle(operation: ProposalOperation): String = when (operation) {
        ProposalOperation.EXPENSE_CREATE -> "新增账目草稿"
        ProposalOperation.EXPENSE_UPDATE -> "修改账目草稿"
        ProposalOperation.EXPENSE_PRESENTATION_UPDATE -> "修改账目显示草稿"
        ProposalOperation.EXPENSE_DELETE -> "删除账目草稿"
        ProposalOperation.SETTLEMENT_REPAYMENT -> "还款草稿"
        ProposalOperation.TRANSFER_VOID -> "作废转账草稿"
        ProposalOperation.PREPAYMENT_CREATE -> "预存草稿"
        ProposalOperation.PREPAYMENT_RETURN -> "预存返还草稿"
        ProposalOperation.SETTLEMENT_FINAL -> "最终结算草稿"
        ProposalOperation.EXPENSE_REFUND -> "退款草稿"
        ProposalOperation.EXPENSE_NEGATIVE_ADJUSTMENT -> "负数调整草稿"
        ProposalOperation.ACTIVITY_CREATE -> "新建活动草稿"
        ProposalOperation.ACTIVITY_JOIN -> "加入活动草稿"
        ProposalOperation.PARTICIPANT_CREATE -> "添加参与人草稿"
        ProposalOperation.PARTICIPANT_DELETE -> "移除参与人草稿"
        ProposalOperation.PARTICIPANT_CLAIM -> "认领参与人草稿"
        ProposalOperation.PARTICIPANT_UNCLAIM -> "取消认领草稿"
        ProposalOperation.SUBACTIVITY_CREATE -> "新建子活动草稿"
        ProposalOperation.SUBACTIVITY_DELETE -> "删除子活动草稿"
        ProposalOperation.SUBACTIVITY_RESTORE -> "恢复子活动草稿"
        ProposalOperation.ACTIVITY_MEMBER_REMOVE -> "移除成员草稿"
        ProposalOperation.ACTIVITY_CREATOR_TRANSFER -> "转移创建者草稿"
        ProposalOperation.ACTIVITY_ARCHIVE -> "归档活动草稿"
        ProposalOperation.ACTIVITY_UNARCHIVE -> "取消归档草稿"
        ProposalOperation.ACTIVITY_DELETE -> "删除活动草稿"
        ProposalOperation.UNKNOWN -> "变更草稿"
    }

    /** One plain sentence about what the operation will do; used where the preview has little to show. */
    fun operationSummary(operation: ProposalOperation): String = when (operation) {
        ProposalOperation.EXPENSE_CREATE -> "在账本里新增一笔支出。"
        ProposalOperation.EXPENSE_UPDATE -> "修改这笔支出的内容。"
        ProposalOperation.EXPENSE_PRESENTATION_UPDATE -> "只改这笔支出的显示方式，账面金额不变。"
        ProposalOperation.EXPENSE_DELETE -> "把这笔账目标记为已删除，相关分摊随之调整。"
        ProposalOperation.SETTLEMENT_REPAYMENT -> "记录一笔还款，并按服务端给出的方案冲抵欠款。"
        ProposalOperation.TRANSFER_VOID -> "作废这笔转账，原记录保留为已作废。"
        ProposalOperation.PREPAYMENT_CREATE -> "登记一笔预存，之后的消费按次抵扣。"
        ProposalOperation.PREPAYMENT_RETURN -> "把还没用完的预存退还给所有人。"
        ProposalOperation.SETTLEMENT_FINAL -> "按服务端给出的完整方案完成本次活动结算。"
        ProposalOperation.EXPENSE_REFUND -> "为原账目登记一笔退款，原账目金额不变。"
        ProposalOperation.EXPENSE_NEGATIVE_ADJUSTMENT -> "登记一笔负数调整，用于冲减账目。"
        ProposalOperation.ACTIVITY_CREATE -> "创建一个新活动并生成加入码。"
        ProposalOperation.ACTIVITY_JOIN -> "用加入码加入一个活动。"
        ProposalOperation.PARTICIPANT_CREATE -> "在活动里新增一位参与人。"
        ProposalOperation.PARTICIPANT_DELETE -> "把一位参与人移出活动。"
        ProposalOperation.PARTICIPANT_CLAIM -> "把活动里某位参与人认领为自己。"
        ProposalOperation.PARTICIPANT_UNCLAIM -> "取消此前对参与人的认领。"
        ProposalOperation.SUBACTIVITY_CREATE -> "在活动下新建一个子活动。"
        ProposalOperation.SUBACTIVITY_DELETE -> "删除子活动，历史记录保留。"
        ProposalOperation.SUBACTIVITY_RESTORE -> "恢复此前删除的子活动。"
        ProposalOperation.ACTIVITY_MEMBER_REMOVE -> "把成员移出活动。"
        ProposalOperation.ACTIVITY_CREATOR_TRANSFER -> "把活动创建者转给另一位成员。"
        ProposalOperation.ACTIVITY_ARCHIVE -> "归档活动，归档期间不能继续记账。"
        ProposalOperation.ACTIVITY_UNARCHIVE -> "把活动从归档中恢复。"
        ProposalOperation.ACTIVITY_DELETE -> "删除活动，这一步不可恢复。"
        ProposalOperation.UNKNOWN -> "服务端返回了一种当前版本还不认识的变更。"
    }

    const val UNKNOWN_PREVIEW_TITLE = "变更预览"
    const val UNKNOWN_PREVIEW_NOTE = "这张草稿的内容类型当前版本还不能完整展示，请以服务端摘要为准。"
    const val UNKNOWN_OPERATION_LABEL = "操作"

    /**
     * Renders any preview kind into title/amount/rows. Every kind has an explicit branch so a new api
     * version cannot leave the card blank; [ProposalPreview] unknown kinds use the summary fallback.
     */
    fun previewView(
        preview: ProposalPreview,
        operation: ProposalOperation,
        names: AgentNameResolver,
    ): PreviewView = when (preview) {
        is ExpensePreview -> PreviewView(
            title = preview.after.title,
            amount = amountText(preview),
            rows = rows(preview, names),
            note = null,
        )
        is ManagementPreview -> managementView(preview, operation, names)
        is RefundPreview -> PreviewView(
            title = preview.refundTitle,
            amount = "${preview.refundAmount} ${preview.currency}",
            rows = listOf(
                DraftRow("原账目", null, preview.originalTitle),
                DraftRow("原金额", null, "${preview.originalAmount} ${preview.currency}"),
                DraftRow("已退金额", null, "${preview.refundedAmount} ${preview.currency}"),
                DraftRow("退款后剩余", null, "${preview.remainingAmount} ${preview.currency}"),
            ),
            note = null,
        )
        is PrepaymentPreview -> PreviewView(
            title = operationTitle(operation),
            amount = "${preview.amount} ${preview.currency}",
            rows = listOf(
                DraftRow("所有人", null, names.participant(preview.ownerParticipantId)),
                DraftRow("保管人", null, names.participant(preview.custodianParticipantId)),
                DraftRow("结算金额", null, "${preview.settlementAmount} ${preview.currency}"),
                DraftRow("预存金额", null, "${preview.prepaymentAmount} ${preview.currency}"),
                DraftRow("预存后余额", null, "${preview.newBalance} ${preview.currency}"),
            ),
            note = null,
        )
        is PrepaymentReturnPreview -> PreviewView(
            title = operationTitle(operation),
            amount = "${preview.amount} ${preview.currency}",
            rows = buildList {
                add(DraftRow("所有人", null, names.participant(preview.ownerParticipantId)))
                add(DraftRow("保管人", null, names.participant(preview.custodianParticipantId)))
                add(DraftRow("当前余额", null, "${preview.currentBalance} ${preview.currency}"))
                preview.postBalanceNote?.takeIf(String::isNotBlank)?.let { add(DraftRow("余额说明", null, it)) }
            },
            note = null,
        )
        is NegativeAdjustmentPreview -> PreviewView(
            title = preview.title,
            amount = "${preview.amount} ${preview.currency}",
            rows = emptyList(),
            note = operationSummary(operation),
        )
        is RepaymentPreview -> PreviewView(
            title = operationTitle(operation),
            amount = "${preview.amount} ${preview.currency}",
            rows = buildList {
                add(DraftRow("付款人", null, names.participant(preview.fromParticipantId)))
                add(DraftRow("收款人", null, names.participant(preview.toParticipantId)))
                add(DraftRow("冲抵方式", null, repaymentModeLabel(preview.mode)))
                if (preview.allocations.isNotEmpty()) add(DraftRow("冲抵账目", null, "${preview.allocations.size} 笔"))
            },
            note = null,
        )
        is TransferVoidPreview -> PreviewView(
            title = operationTitle(operation),
            amount = "${preview.amount} ${preview.currency}",
            rows = listOf(
                DraftRow("转账类型", null, transferTypeLabel(preview.transferType)),
                DraftRow("从", null, names.participant(preview.fromParticipantId)),
                DraftRow("到", null, names.participant(preview.toParticipantId)),
                DraftRow("状态", null, if (preview.isVoided) "已作废" else "未作废"),
                DraftRow("原因", null, preview.voidReason),
            ),
            note = null,
        )
        is FinalSettlementPreview -> PreviewView(
            title = operationTitle(operation),
            amount = "${preview.amount} ${preview.currency}",
            rows = buildList {
                add(DraftRow("从", null, names.participant(preview.fromParticipantId)))
                add(DraftRow("到", null, names.participant(preview.toParticipantId)))
                add(DraftRow("结算方式", null, settlementModeLabel(preview.mode)))
                add(DraftRow("普通金额", null, "${preview.ordinaryAmount} ${preview.currency}"))
                add(DraftRow("预存返还", null, "${preview.prepaymentReturnAmount} ${preview.currency}"))
                preview.plan.take(MAX_PLAN_ROWS).forEach { item ->
                    add(
                        DraftRow(
                            "计划",
                            null,
                            "${names.participant(item.fromParticipantId)} → ${names.participant(item.toParticipantId)}" +
                                " ${item.amount} ${item.currency}",
                        ),
                    )
                }
                if (preview.plan.size > MAX_PLAN_ROWS) add(DraftRow("计划", null, "另有 ${preview.plan.size - MAX_PLAN_ROWS} 笔"))
            },
            note = null,
        )
        else -> PreviewView(
            title = UNKNOWN_PREVIEW_TITLE,
            amount = null,
            rows = emptyList(),
            note = preview.summary.takeIf(String::isNotBlank) ?: UNKNOWN_PREVIEW_NOTE,
            fallback = true,
        )
    }

    private fun managementView(
        preview: ManagementPreview,
        operation: ProposalOperation,
        names: AgentNameResolver,
    ): PreviewView {
        val rows = buildList {
            preview.activityName?.takeIf(String::isNotBlank)?.let { add(DraftRow("活动", null, it)) }
            preview.activityType?.let { add(DraftRow("类型", null, activityTypeLabel(it))) }
            preview.baseCurrency?.takeIf(String::isNotBlank)?.let { add(DraftRow("基准币种", null, it)) }
            preview.joinCode?.takeIf(String::isNotBlank)?.let { add(DraftRow("加入码", null, it)) }
            preview.multiCurrencyEnabled?.let { add(DraftRow("多币种", null, if (it) "已启用" else "未启用")) }
            preview.subActivityName?.takeIf(String::isNotBlank)?.let { add(DraftRow("子活动", null, it)) }
            preview.participantName?.takeIf(String::isNotBlank)?.let { add(DraftRow("参与人", null, it)) }
            if (preview.participantNames.isNotEmpty()) {
                add(DraftRow("成员", null, preview.participantNames.joinToString("、")))
            }
            preview.participantOrder?.let { add(DraftRow("顺序", null, "第 $it 位")) }
            preview.unsettled?.let { add(DraftRow("未结清", null, if (it) "是" else "否")) }
            preview.financialSummary?.takeIf(String::isNotBlank)?.let { add(DraftRow("账务", null, it)) }
        }
        val title = rows.firstOrNull()?.after
            ?: names.participant(preview.participantId.orEmpty()).takeIf { preview.participantId != null }
            ?: operationTitle(if (preview.operation == ProposalOperation.UNKNOWN) operation else preview.operation)
        return PreviewView(
            title = title,
            amount = null,
            rows = rows,
            note = operationSummary(if (preview.operation == ProposalOperation.UNKNOWN) operation else preview.operation),
        )
    }

    private fun activityTypeLabel(raw: String): String = when (raw) {
        "normal" -> "普通活动"
        "large" -> "大型活动"
        else -> raw
    }

    private fun repaymentModeLabel(raw: String): String = when (raw.uppercase()) {
        "FIFO" -> "按先后顺序冲抵"
        "TARGETED" -> "指定账目冲抵"
        else -> raw
    }

    private fun transferTypeLabel(raw: String): String = when (raw) {
        "settlement" -> "结算转账"
        "prepayment" -> "预存"
        "prepayment_return" -> "预存返还"
        "final_settlement" -> "最终结算"
        else -> raw
    }

    private fun settlementModeLabel(raw: String): String = when (raw) {
        "base_unified" -> "统一基准币种"
        "original_currency" -> "按原币结算"
        else -> raw
    }

    private const val MAX_PLAN_ROWS = 5

    fun statusLabel(status: ProposalStatus): String = when (status) {
        ProposalStatus.SUPERSEDED -> "已被新草稿替代"
        ProposalStatus.CANCELLED -> "已取消"
        ProposalStatus.EXPIRED -> "已过期"
        ProposalStatus.CONFIRMED -> "已确认"
        ProposalStatus.REJECTED -> "已拒绝"
        ProposalStatus.CLOSED -> "已关闭"
        ProposalStatus.PENDING, ProposalStatus.UNKNOWN -> "已失效"
    }

    fun amountText(preview: ExpensePreview): String =
        "${preview.after.originalAmount} ${preview.after.originalCurrency}"

    /** Short, human-scannable form of an execution id; the full id is never shown. */
    fun shortExecutionId(executionId: String): String =
        executionId.filter { it != '-' }.take(8)

    fun receiptLine(receipt: ExecutionReceiptItem): String {
        val base = "${RECEIPT_PREFIX} ${shortExecutionId(receipt.executionId)}"
        return when {
            receipt.reconciling -> "$base · $RECONCILING_LABEL"
            receipt.state == TurnState.EXECUTING -> "$base · $EXECUTING_LABEL"
            else -> base
        }
    }

    fun splitText(split: CanonicalSplit, names: AgentNameResolver): String = when (split) {
        is CanonicalEqualSplit -> "${split.participantIds.size} 人平分"
        is CanonicalManualSplit ->
            names.participantAmounts(split.allocations.map { it.participantId to it.amount })
        else -> "未知分摊方式"
    }

    fun paymentsText(payments: List<CanonicalPayment>, names: AgentNameResolver): String =
        names.participantAmounts(payments.map { it.participantId to it.amount })

    private fun fxText(fx: FxSnapshot?): String =
        if (fx == null) "无" else "1 ${fx.originalCurrency} = ${fx.rate} ${fx.baseCurrency}"

    private fun optional(value: String?): String = value?.takeIf { it.isNotBlank() } ?: "无"

    fun rows(preview: ExpensePreview, names: AgentNameResolver): List<DraftRow> {
        val isCreate = preview.before == null
        return preview.changes.mapNotNull { change -> row(change, names, isCreate) }
    }

    private fun row(change: ExpenseChange, names: AgentNameResolver, isCreate: Boolean): DraftRow? = when (change) {
        // On create the header already shows the title and amount.
        is ExpenseTitleChange ->
            if (isCreate) null else DraftRow("标题", change.before?.let(::optional), optional(change.after))
        is ExpenseAmountChange -> when {
            change.amountField == AmountField.ORIGINAL_AMOUNT && isCreate -> null
            change.amountField == AmountField.ORIGINAL_AMOUNT -> DraftRow("金额", change.before, change.after)
            change.amountField == AmountField.BASE_AMOUNT -> DraftRow("记账金额", change.before, change.after)
            else -> null
        }
        is ExpenseCurrencyChange -> DraftRow("币种", change.before, change.after)
        is ExpenseLedgerUnitChange ->
            DraftRow("账本", change.before?.let(names::ledgerUnit), names.ledgerUnit(change.after))
        is ExpensePaymentsChange -> DraftRow(
            "付款",
            change.before?.let { paymentsText(it, names) },
            paymentsText(change.after, names),
        )
        is ExpenseSplitChange -> DraftRow(
            "分摊",
            change.before?.let { splitText(it, names) },
            splitText(change.after, names),
        )
        is ExpenseNoteChange -> DraftRow("备注", change.before?.let(::optional), optional(change.after))
        is ExpenseOccurredAtChange -> DraftRow(
            "时间",
            change.before?.let { UiDateTimeFormatter.format(it) },
            change.after?.let { UiDateTimeFormatter.format(it) } ?: "无",
        )
        is ExpenseIconChange -> DraftRow("图标", change.before?.let(::optional), optional(change.after))
        is ExpenseFxChange -> DraftRow("汇率", change.before?.let { fxText(it) }, fxText(change.after))
        else -> null
    }
}
