package com.ffocalors.sharedledger.ui.expense

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.expense.CreateExpenseInput
import com.ffocalors.sharedledger.data.expense.Expense
import com.ffocalors.sharedledger.data.expense.ExpenseDetail
import com.ffocalors.sharedledger.data.expense.ExpenseErrorMapper
import com.ffocalors.sharedledger.data.expense.ExpenseOperationException
import com.ffocalors.sharedledger.data.expense.ExpenseRepository
import com.ffocalors.sharedledger.data.expense.ExpenseRepositoryFactory
import com.ffocalors.sharedledger.data.expense.ExpenseWriteResult
import com.ffocalors.sharedledger.data.expense.ExpenseWriteState
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepository
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepositoryFactory
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareSnapshot
import com.ffocalors.sharedledger.data.expense.ExpenseSplitMethod
import com.ffocalors.sharedledger.data.expense.ManualSplitInput
import com.ffocalors.sharedledger.data.expense.PaymentInput
import com.ffocalors.sharedledger.data.expense.RefundExpenseInput
import com.ffocalors.sharedledger.data.expense.UpdateExpenseInput
import com.ffocalors.sharedledger.ui.components.ExpenseCardUiModel
import com.ffocalors.sharedledger.ui.screens.ExpenseDetailStatus
import com.ffocalors.sharedledger.ui.screens.ExpenseDetailUiState
import com.ffocalors.sharedledger.ui.screens.ExpenseSettlement
import com.ffocalors.sharedledger.ui.screens.ExpenseSplitUiState
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.math.BigDecimal
import java.time.Instant

enum class ExpenseFormMode { Create, Edit, Refund }

data class ExpenseFormParticipant(val id: String, val name: String)

data class ExpenseFormDraft(
    val ledgerUnitId: String,
    val originalExpenseId: String? = null,
    val title: String,
    val amount: String,
    val currency: String,
    val fxRate: String,
    val payerIds: List<String>,
    val payerAmounts: Map<String, String>,
    val splitMethod: ExpenseSplitMethod,
    val manualSplitAmounts: Map<String, String>,
    val aaParticipantIds: List<String>,
    val occurredAt: String,
    val note: String,
)

data class ExpenseListUiState(
    val isLoading: Boolean = true,
    val expenses: List<ExpenseCardUiModel> = emptyList(),
    val totalBaseAmount: BigDecimal = BigDecimal.ZERO,
    val participantBound: Boolean = false,
    val ledgerUnitTotals: Map<String, BigDecimal> = emptyMap(),
    val currencyCode: String = "CNY",
    val errorMessage: String? = null,
)

data class ExpenseDetailRouteState(
    val isLoading: Boolean = true,
    val detail: ExpenseDetail? = null,
    val errorMessage: String? = null,
    val actionMessage: String? = null,
)

data class ExpenseFormUiState(
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val submissionBlocked: Boolean = false,
    val writeState: ExpenseWriteState? = null,
)

class ExpenseViewModel(
    private val repository: ExpenseRepository,
    val currentUserId: String,
    private val shareRepository: ParticipantExpenseShareRepository = ParticipantExpenseShareRepositoryFactory.create(),
) : ViewModel() {
    private val listStates = mutableMapOf<String, MutableStateFlow<ExpenseListUiState>>()
    private val detailStates = mutableMapOf<String, MutableStateFlow<ExpenseDetailRouteState>>()
    private val _form = MutableStateFlow(ExpenseFormUiState())
    val form: StateFlow<ExpenseFormUiState> = _form.asStateFlow()

    fun listState(scopeKey: String): StateFlow<ExpenseListUiState> =
        listStates.getOrPut(scopeKey) { MutableStateFlow(ExpenseListUiState()) }.asStateFlow()

    fun detailState(expenseId: String): StateFlow<ExpenseDetailRouteState> =
        detailStates.getOrPut(expenseId) { MutableStateFlow(ExpenseDetailRouteState()) }.asStateFlow()

    fun loadByActivity(activityId: String, force: Boolean = false, baseCurrency: String = "CNY") {
        val key = activityKey(activityId)
        val state = listStates.getOrPut(key) { MutableStateFlow(ExpenseListUiState()) }
        if (!force && !state.value.isLoading && state.value.errorMessage == null) return
        loadList(
            key = key,
            expenseBlock = { repository.listByActivity(activityId, includeDeleted = true) },
            shareBlock = { shareRepository.getForActivity(activityId, currentUserId) },
            currencyCode = baseCurrency,
        )
    }

    fun loadByLedgerUnit(ledgerUnitId: String, force: Boolean = false) {
        loadByLedgerUnit("", ledgerUnitId, force, "CNY")
    }

    fun loadByLedgerUnit(
        activityId: String,
        ledgerUnitId: String,
        force: Boolean = false,
        baseCurrency: String = "CNY",
    ) {
        val key = ledgerKey(ledgerUnitId)
        val state = listStates.getOrPut(key) { MutableStateFlow(ExpenseListUiState()) }
        if (!force && !state.value.isLoading && state.value.errorMessage == null) return
        loadList(
            key = key,
            expenseBlock = { repository.listByLedgerUnit(ledgerUnitId, includeDeleted = true) },
            shareBlock = { shareRepository.getForLedgerUnit(activityId, ledgerUnitId, currentUserId) },
            currencyCode = baseCurrency,
        )
    }

    fun loadDetail(expenseId: String, force: Boolean = false) {
        val state = detailStates.getOrPut(expenseId) { MutableStateFlow(ExpenseDetailRouteState()) }
        if (!force && !state.value.isLoading && state.value.detail != null && state.value.errorMessage == null) return
        viewModelScope.launch {
            state.value = state.value.copy(isLoading = true, errorMessage = null)
            val actionMessage = state.value.actionMessage
            repository.getDetail(expenseId).fold(
                onSuccess = { state.value = ExpenseDetailRouteState(isLoading = false, detail = it, actionMessage = actionMessage) },
                onFailure = { state.value = ExpenseDetailRouteState(false, state.value.detail, userMessage(it)) },
            )
        }
    }

    fun submit(
        mode: ExpenseFormMode,
        expenseId: String?,
        activityId: String,
        draft: ExpenseFormDraft,
        onSuccess: (String) -> Unit = {},
    ) {
        if (_form.value.isSubmitting || _form.value.submissionBlocked) return
        val validation = validate(draft, mode)
        if (validation != null) {
            _form.value = ExpenseFormUiState(errorMessage = validation)
            return
        }
        val input = draft.toInputs()
        _form.value = ExpenseFormUiState(isSubmitting = true)
        viewModelScope.launch {
            val result = when (mode) {
                ExpenseFormMode.Create -> repository.createWrite(input.create)
                ExpenseFormMode.Edit -> repository.updateWrite(
                    UpdateExpenseInput(
                        expenseId = requireNotNull(expenseId),
                        ledgerUnitId = input.create.ledgerUnitId,
                        title = input.create.title,
                        originalAmount = input.create.originalAmount,
                        originalCurrency = input.create.originalCurrency,
                        fxRate = input.create.fxRate,
                        splitMethod = input.create.splitMethod,
                        payments = input.create.payments,
                        manualSplits = input.create.manualSplits,
                        aaParticipantIds = input.create.aaParticipantIds,
                        occurredAt = input.create.occurredAt,
                        note = input.create.note,
                        originalExpenseId = input.create.originalExpenseId,
                    ),
                )
                ExpenseFormMode.Refund -> repository.refundWrite(
                    RefundExpenseInput(
                        ledgerUnitId = input.create.ledgerUnitId,
                        title = input.create.title,
                        amount = input.create.originalAmount,
                        originalCurrency = input.create.originalCurrency,
                        fxRate = input.create.fxRate,
                        splitMethod = input.create.splitMethod,
                        payments = input.create.payments,
                        manualSplits = input.create.manualSplits,
                        aaParticipantIds = input.create.aaParticipantIds,
                        occurredAt = input.create.occurredAt,
                        note = input.create.note,
                        originalExpenseId = input.create.originalExpenseId,
                    ),
                )
            }
            when {
                result.isSuccess && result.value != null -> {
                    val mutation = result.value
                    _form.value = ExpenseFormUiState()
                    refreshAfterMutation(activityId, input.create.ledgerUnitId, expenseId ?: mutation.expenseId)
                    onSuccess(mutation.expenseId)
                }
                result.isCommitted && result.value != null -> {
                    // The RPC committed and returned the authoritative expense id. A failed
                    // follow-up read must not discard that id or block attachment upload.
                    val mutation = result.value
                    _form.value = ExpenseFormUiState(
                        errorMessage = result.errorMessage
                            ?: "账单已保存，但最新详情暂时无法刷新，请稍后刷新确认",
                        writeState = result.state,
                    )
                    refreshAfterMutation(activityId, input.create.ledgerUnitId, mutation.expenseId)
                    onSuccess(mutation.expenseId)
                }
                else -> _form.value = ExpenseFormUiState(
                    errorMessage = result.errorMessage ?: "账单写入失败",
                    submissionBlocked = result.isUnknown,
                    writeState = result.state,
                )
            }
        }
    }

    fun delete(expenseId: String) = mutateDetail(expenseId, "账单已作废") { repository.deleteWrite(expenseId) }

    fun restore(expenseId: String) = mutateDetail(expenseId, "账单已恢复") { repository.restoreWrite(expenseId) }

    fun clearFormError() { _form.value = ExpenseFormUiState() }

    /** Clears an ambiguous-write guard only after the caller has explicitly refreshed/confirmed. */
    fun recoverFromUnknownWrite(
        activityId: String,
        ledgerUnitId: String,
        expenseId: String? = null,
        onConfirmed: () -> Unit = {},
    ) {
        if (_form.value.writeState != ExpenseWriteState.UNKNOWN) return
        viewModelScope.launch {
            val confirmed = if (expenseId != null) {
                repository.getDetail(expenseId).isSuccess
            } else {
                repository.listByActivity(activityId, includeDeleted = true).isSuccess &&
                    repository.listByLedgerUnit(ledgerUnitId, includeDeleted = true).isSuccess
            }
            if (!confirmed) {
                _form.value = _form.value.copy(errorMessage = "刷新账单失败，请重试")
                return@launch
            }
            clearFormError()
            onConfirmed()
            if (expenseId != null) refreshAfterMutation(activityId, ledgerUnitId, expenseId)
            else {
                loadByActivity(activityId, force = true)
                loadByLedgerUnit(activityId, ledgerUnitId, force = true)
            }
        }
    }

    private fun mutateDetail(
        expenseId: String,
        successMessage: String,
        action: suspend () -> ExpenseWriteResult<com.ffocalors.sharedledger.data.expense.ExpenseMutationResult>,
    ) {
        if (_form.value.isSubmitting || _form.value.submissionBlocked) return
        _form.value = ExpenseFormUiState(isSubmitting = true)
        viewModelScope.launch {
            val result = action()
            if (result.isSuccess || (result.isCommitted && result.value != null)) {
                    val committed = result.isCommitted
                    _form.value = if (committed) {
                        ExpenseFormUiState(
                            errorMessage = result.errorMessage
                                ?: "账单已保存，但最新详情暂时无法刷新，请稍后刷新确认",
                            writeState = result.state,
                        )
                    } else {
                        ExpenseFormUiState()
                    }
                    val current = detailStates[expenseId]?.value?.detail
                    if (current != null) refreshAfterMutation(current.ledgerUnit.activityId, current.expense.ledgerUnitId, expenseId)
                    detailStates.getOrPut(expenseId) { MutableStateFlow(ExpenseDetailRouteState()) }.value =
                        detailStates[expenseId]!!.value.copy(
                            actionMessage = if (committed) {
                                result.errorMessage ?: "账单已保存，但最新详情暂时无法刷新，请稍后刷新确认"
                            } else {
                                successMessage
                            },
                        )
                    loadDetail(expenseId, force = true)
            } else {
                    _form.value = ExpenseFormUiState(
                        errorMessage = result.errorMessage ?: "账单操作失败",
                        submissionBlocked = result.isUnknown,
                        writeState = result.state,
                    )
                    detailStates.getOrPut(expenseId) { MutableStateFlow(ExpenseDetailRouteState()) }.value =
                        detailStates[expenseId]!!.value.copy(actionMessage = result.errorMessage ?: "账单操作失败")
            }
        }
    }

    private fun refreshAfterMutation(activityId: String, ledgerUnitId: String, expenseId: String) {
        val currencyCode = listStates[activityKey(activityId)]?.value?.currencyCode ?: "CNY"
        loadByActivity(activityId, force = true, baseCurrency = currencyCode)
        loadByLedgerUnit(activityId, ledgerUnitId, force = true, baseCurrency = currencyCode)
        detailStates[expenseId]?.let { loadDetail(expenseId, force = true) }
    }

    private fun loadList(
        key: String,
        expenseBlock: suspend () -> Result<List<Expense>>,
        shareBlock: suspend () -> Result<ParticipantExpenseShareSnapshot>,
        currencyCode: String,
    ) {
        val state = listStates[key] ?: return
        viewModelScope.launch {
            state.value = state.value.copy(isLoading = true, errorMessage = null)
            val expensesResult = expenseBlock()
            val sharesResult = shareBlock()
            val expenses = expensesResult.getOrElse {
                state.value = state.value.copy(isLoading = false, errorMessage = userMessage(it))
                return@launch
            }
            val shares = sharesResult.getOrElse {
                state.value = state.value.copy(isLoading = false, errorMessage = userMessage(it))
                return@launch
            }
            state.value = expenses.toListUiState(shares, currencyCode)
        }
    }

    private fun List<Expense>.toListUiState(
        shares: ParticipantExpenseShareSnapshot,
        currencyCode: String,
    ) = ExpenseListUiState(
        isLoading = false,
        expenses = map { expense ->
            expense.toExpenseCardUiModel(
                amount = shares.expenseTotals[expense.id] ?: BigDecimal.ZERO,
                currencyCode = currencyCode,
                amountAvailable = shares.isBound,
            )
        },
        totalBaseAmount = shares.activityTotalBaseAmount ?: BigDecimal.ZERO,
        participantBound = shares.isBound,
        ledgerUnitTotals = shares.ledgerUnitTotals,
        currencyCode = currencyCode,
    )

    private fun validate(draft: ExpenseFormDraft, mode: ExpenseFormMode): String? {
        if (draft.title.isBlank()) return "请输入消费名称"
        val amount = draft.amount.toDecimal() ?: return "请输入有效金额"
        if (amount <= BigDecimal.ZERO) return "金额必须大于 0"
        if (!draft.currency.matches(Regex("[A-Za-z]{3}"))) return "请输入 3 位币种代码"
        val fxRate = draft.fxRate.toDecimal() ?: return "请输入有效汇率"
        if (fxRate <= BigDecimal.ZERO) return "汇率必须大于 0"
        if (!runCatching { Instant.parse(draft.occurredAt.trim()) }.isSuccess) return "发生时间必须是有效的 ISO-8601 时间"
        if (draft.payerIds.isEmpty()) return "请选择至少一位付款人"
        val payerValues = draft.payerIds.map { draft.payerAmounts[it]?.toDecimal() }
        if (payerValues.any { it == null || it <= BigDecimal.ZERO }) return "每位付款人的金额必须大于 0"
        val payerTotal = payerValues.filterNotNull().sumOf { it }
        if (payerTotal.compareTo(amount) != 0) return "付款合计必须等于总金额"
        when (draft.splitMethod) {
            ExpenseSplitMethod.Manual -> {
                val invalidValue = draft.manualSplitAmounts.values.any { value ->
                    val parsed = value.toDecimal()
                    value.isNotBlank() && (parsed == null || parsed < BigDecimal.ZERO)
                }
                if (invalidValue) return "手动分摊金额必须为正数"
                val positiveSplits = draft.manualSplitAmounts.values.mapNotNull { it.toDecimal() }.filter { it > BigDecimal.ZERO }
                if (positiveSplits.isEmpty()) return "至少填写一项大于 0 的手动分摊"
                val splitTotal = positiveSplits.sumOf { it }
                if (splitTotal.compareTo(amount) != 0) return "手动分摊合计必须等于总金额"
            }
            ExpenseSplitMethod.Aa -> if (draft.aaParticipantIds.isEmpty()) return "请选择 AA 参与人"
        }
        return null
    }

    private data class Inputs(val create: CreateExpenseInput)

    private fun ExpenseFormDraft.toInputs(): Inputs {
        val amount = amount.toDecimal() ?: BigDecimal.ZERO
        val currency = currency.trim().uppercase()
        val fxRate = fxRate.toDecimal() ?: BigDecimal.ONE
        return Inputs(
            CreateExpenseInput(
                ledgerUnitId = ledgerUnitId,
                title = title.trim(),
                originalAmount = amount,
                originalCurrency = currency,
                fxRate = fxRate,
                splitMethod = splitMethod,
                payments = payerIds.mapNotNull { participantId ->
                    payerAmounts[participantId]?.toDecimal()?.takeIf { it > BigDecimal.ZERO }
                        ?.let { PaymentInput(participantId, it) }
                },
                manualSplits = if (splitMethod == ExpenseSplitMethod.Manual) {
                    manualSplitAmounts.mapNotNull { (participantId, value) ->
                        value.toDecimal()?.takeIf { it > BigDecimal.ZERO }
                            ?.let { ManualSplitInput(participantId, it) }
                    }
                } else {
                    emptyList()
                },
                aaParticipantIds = if (splitMethod == ExpenseSplitMethod.Aa) aaParticipantIds else emptyList(),
                occurredAt = occurredAt.trim(),
                note = note.trim().ifBlank { null },
                originalExpenseId = originalExpenseId,
            ),
        )
    }

    private fun String.toDecimal(): BigDecimal? = trim().toBigDecimalOrNull()
    private fun activityKey(id: String) = "activity:$id"
    private fun ledgerKey(id: String) = "ledger:$id"

    private fun userMessage(error: Throwable): String =
        (error as? ExpenseOperationException)?.userMessage ?: ExpenseErrorMapper.toUserMessage(error)

    class Factory(
        private val repository: ExpenseRepository = ExpenseRepositoryFactory.create(),
        private val shareRepository: ParticipantExpenseShareRepository = ParticipantExpenseShareRepositoryFactory.create(),
        private val currentUserId: String,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            ExpenseViewModel(repository, currentUserId, shareRepository) as T
    }
}

fun ExpenseDetail.toFormDraft(mode: ExpenseFormMode): ExpenseFormDraft {
    val payerAmounts = payments
        .groupingBy { it.participantId }
        .fold(BigDecimal.ZERO) { total, payment -> total + payment.amount }
        .mapValues { (_, amount) -> amount.abs() }
        .filterValues { it > BigDecimal.ZERO }
    val payerIds = payerAmounts.keys.toList()
    val splitAmounts = splits
        .associate { it.participantId to it.amount.abs() }
        .filterValues { it > BigDecimal.ZERO }
    return ExpenseFormDraft(
        ledgerUnitId = expense.ledgerUnitId,
        originalExpenseId = when (mode) {
            ExpenseFormMode.Edit -> expense.originalExpenseId
            ExpenseFormMode.Refund -> expense.id
            ExpenseFormMode.Create -> null
        },
        title = if (mode == ExpenseFormMode.Refund) "退款-${expense.title}" else expense.title,
        amount = expense.originalAmount.abs().toPlainString(),
        currency = expense.originalCurrency,
        fxRate = expense.fxRate.toPlainString(),
        payerIds = payerIds,
        payerAmounts = payerAmounts.mapValues { it.value.toPlainString() },
        splitMethod = expense.splitMethod,
        manualSplitAmounts = splitAmounts.mapValues { it.value.toPlainString() },
        aaParticipantIds = splitAmounts.keys.toList(),
        occurredAt = if (mode == ExpenseFormMode.Refund) Instant.now().toString() else expense.occurredAt,
        note = expense.note.orEmpty(),
    )
}

internal fun Expense.toExpenseCardUiModel(
    amount: BigDecimal = originalAmount.abs(),
    currencyCode: String = originalCurrency,
    amountAvailable: Boolean = true,
) = ExpenseCardUiModel(
    name = title,
    amount = amount,
    currencyCode = currencyCode,
    payerName = "已记录付款",
    participantCount = 0,
    time = UiDateTimeFormatter.format(occurredAt),
    expenseId = id,
    amountAvailable = amountAvailable,
    isDeleted = isDeleted,
)

fun ExpenseDetail.toUiState(): ExpenseDetailUiState {
    val names = participants.associateBy { it.id }
    val payerNames = payments.mapNotNull { names[it.participantId]?.name }.distinct()
    return ExpenseDetailUiState(
        expenseId = expense.id,
        title = expense.title,
        merchant = "",
        amount = expense.baseAmount.toPlainString(),
        currencyCode = baseCurrency,
        originalAmount = expense.originalAmount.abs().toPlainString(),
        originalCurrencyCode = expense.originalCurrency,
        occurredAt = UiDateTimeFormatter.format(expense.occurredAt),
        ledgerUnit = ledgerUnit.name,
        note = expense.note.orEmpty(),
        payer = payerNames.ifEmpty { listOf("未知付款人") }.joinToString("、"),
        payerIsCurrentUser = false,
        splits = splits.map { split ->
            val remainingDebt = debtSettlements
                .filter { it.debtorParticipantId == split.participantId }
                .fold(BigDecimal.ZERO) { total, debt -> total + debt.remainingAmount }
            ExpenseSplitUiState(
                participant = names[split.participantId]?.name ?: split.participantId,
                owedAmount = split.amount.abs().toPlainString(),
                settlement = if (remainingDebt <= BigDecimal.ZERO) ExpenseSettlement.Paid else ExpenseSettlement.Pending,
                paidAmount = null,
                netAdvance = null,
                isPayer = payments.any { it.participantId == split.participantId },
            )
        },
        attachments = emptyList(),
        status = if (expense.isDeleted) ExpenseDetailStatus.Deleted else ExpenseDetailStatus.Active,
    )
}
