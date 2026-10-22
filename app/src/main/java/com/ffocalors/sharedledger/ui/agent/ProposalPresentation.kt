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
import com.ffocalors.sharedledger.data.agent.FxSnapshot
import com.ffocalors.sharedledger.data.agent.ProposalOperation
import com.ffocalors.sharedledger.data.agent.ProposalStatus
import com.ffocalors.sharedledger.data.agent.TurnState
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter

/** One change row in a draft: a Chinese field label and the value (`before → after` when updating). */
data class DraftRow(val label: String, val before: String?, val after: String)

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
        ProposalOperation.UNKNOWN -> "账目草稿"
    }

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
