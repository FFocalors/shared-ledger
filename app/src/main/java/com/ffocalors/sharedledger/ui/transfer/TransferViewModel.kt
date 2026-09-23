package com.ffocalors.sharedledger.ui.transfer

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.InMemoryTransferRequestStore
import com.ffocalors.sharedledger.data.transfer.PendingTransferRequest
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementCandidateKind
import com.ffocalors.sharedledger.data.transfer.SettlementAllocationMode
import com.ffocalors.sharedledger.data.transfer.SettlementCurrencyOption
import com.ffocalors.sharedledger.data.transfer.SettlementExpenseOption
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.data.transfer.SettlementTransferResult
import com.ffocalors.sharedledger.data.transfer.SettlementPreview
import com.ffocalors.sharedledger.data.transfer.PreviewSettlementInput
import com.ffocalors.sharedledger.data.transfer.SettlementParticipant
import com.ffocalors.sharedledger.data.transfer.TransferErrorMapper
import com.ffocalors.sharedledger.data.transfer.TransferRepository
import com.ffocalors.sharedledger.data.transfer.TransferRepositoryFactory
import com.ffocalors.sharedledger.data.transfer.TransferRequestStore
import com.ffocalors.sharedledger.data.transfer.PreferencesTransferRequestStore
import com.ffocalors.sharedledger.data.transfer.TransferWriteState
import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.data.common.readFailureKind
import com.ffocalors.sharedledger.data.common.shouldRemoveCachedRead
import com.ffocalors.sharedledger.ui.screens.TransferDraft
import com.ffocalors.sharedledger.ui.cache.QueryCacheKey
import com.ffocalors.sharedledger.ui.cache.QueryCacheState
import com.ffocalors.sharedledger.ui.cache.SessionQueryCache
import java.math.BigDecimal
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class TransferCandidateUi(
    val participantId: String,
    val participantName: String,
    val amount: BigDecimal,
    val fromParticipantId: String,
    val fromParticipantName: String,
    val toParticipantId: String,
    val toParticipantName: String,
    val kind: SettlementCandidateKind = SettlementCandidateKind.PERSONAL,
    val onBehalfOptions: List<SettlementParticipant> = emptyList(),
    val currencyOptions: List<SettlementCurrencyOption> = emptyList(),
    val expenseOptions: List<SettlementExpenseOption> = emptyList(),
    val candidateKey: String = "${kind.name}:$fromParticipantId->$toParticipantId",
    val claimedUserId: String? = null,
    val avatarStyle: String? = null,
)

data class TransferUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val baseCurrency: String = "CNY",
    val multiCurrencyEnabled: Boolean = false,
    val currentParticipantId: String? = null,
    val canActOnBehalf: Boolean = false,
    val candidates: List<TransferCandidateUi> = emptyList(),
    val onBehalfCandidates: List<TransferCandidateUi> = emptyList(),
    val errorMessage: String? = null,
    val emptyMessage: String? = null,
    val isSubmitting: Boolean = false,
    val submissionBlocked: Boolean = false,
    val writeState: TransferWriteState? = null,
    val failureKind: ReadFailureKind? = null,
    val pendingRequest: PendingTransferRequest? = null,
    val isPreviewing: Boolean = false,
    val preview: SettlementPreview? = null,
    val previewErrorMessage: String? = null,
    val previewRequired: Boolean = false,
)

class TransferViewModel(
    private val repository: TransferRepository,
    private val queryCache: SessionQueryCache = SessionQueryCache(),
    private val currentUserId: String = "",
    private val requestStore: TransferRequestStore = InMemoryTransferRequestStore(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(TransferUiState())
    val uiState: StateFlow<TransferUiState> = _uiState.asStateFlow()
    private var loadedActivityId: String? = null
    private var loadedDirection: SettlementDirection? = null
    private var previewGeneration = 0L

    fun load(activityId: String, direction: SettlementDirection, force: Boolean = false) {
        previewGeneration += 1
        val key = contextKey(activityId, direction)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            _uiState.value = toUiState(cached.value, direction)
            loadedActivityId = activityId
            loadedDirection = direction
            viewModelScope.launch {
                _uiState.value = _uiState.value.copy(
                    pendingRequest = readPendingRequest(activityId, direction),
                )
                enrichExpenseOptions(cached.value)
            }
            return
        }
        loadedActivityId = activityId
        loadedDirection = direction
        val existing = cached.value
        viewModelScope.launch {
            _uiState.value = existing?.let { toUiState(it, direction).copy(isRefreshing = true) }
                ?: TransferUiState(isLoading = true)
            queryCache.getOrLoad(key, forceRefresh = true) {
                repository.loadContext(activityId, direction)
            }.fold(
                onSuccess = {
                    _uiState.value = toUiState(it, direction).copy(
                        pendingRequest = readPendingRequest(activityId, direction),
                    )
                    enrichExpenseOptions(it)
                },
                onFailure = { error ->
                    val kind = error.readFailureKind()
                    if (kind.shouldRemoveCachedRead()) queryCache.remove(key)
                    _uiState.value = if (kind.shouldRemoveCachedRead()) {
                        TransferUiState(
                            isLoading = false,
                            isRefreshing = false,
                            errorMessage = messageFor(error),
                            failureKind = kind,
                        )
                    } else {
                        (existing?.let { toUiState(it, direction) } ?: TransferUiState()).copy(
                            isLoading = false,
                            isRefreshing = false,
                            errorMessage = messageFor(error),
                            failureKind = kind,
                        )
                    }
                },
            )
        }
    }

    fun submit(draft: TransferDraft, onSuccess: (SettlementTransferResult) -> Unit = {}) {
        val state = _uiState.value
        if (state.isSubmitting) return
        val amount = draft.amount.toBigDecimalOrNull()
        val allCandidates = state.candidates + state.onBehalfCandidates
        val candidate = draft.candidateKey?.let { key ->
            allCandidates.firstOrNull { it.candidateKey == key }
        } ?: allCandidates.singleOrNull { it.participantId == draft.participantId }
        val currency = draft.currency.trim().uppercase().ifBlank { state.baseCurrency }
        val selectedExpenses = candidate?.expenseOptions.orEmpty().filter { it.expenseId in draft.targetExpenseIds }
        val selectedExpenseCap = selectedExpenses.sumOf {
            if (currency == state.baseCurrency) it.remainingBaseAmount else it.remainingOriginalAmount
        }
        val selectedAmountCap = candidate?.let {
            selectedCurrencyOption(it, currency, state.baseCurrency)?.amount ?: it.amount
        } ?: BigDecimal.ZERO
        val targetedCap = minOf(selectedExpenseCap, selectedAmountCap)
        val previewMatches = !state.previewRequired || state.preview?.let { preview ->
                preview.activityId == draft.activityId &&
                    preview.fromParticipantId == candidate?.fromParticipantId &&
                    preview.toParticipantId == candidate?.toParticipantId &&
                    preview.allocationMode == draft.allocationMode &&
                    preview.currency == currency &&
                    preview.requestedAmount.compareTo(amount ?: BigDecimal.ZERO) == 0 &&
                    preview.targetExpenseIds.toSet() == draft.targetExpenseIds.toSet() &&
                    (draft.expectedFinancialVersion == null || preview.financialVersion == draft.expectedFinancialVersion)
            } == true
        when {
            state.currentParticipantId.isNullOrBlank() && draft.onBehalfOfParticipantId == null ->
                setError("当前用户尚未绑定参与人，请先选择代记参与人")
            candidate == null -> setError("请选择当前仍有债务的参与人")
            amount == null || amount <= BigDecimal.ZERO -> setError("请输入大于 0 的金额")
            selectedCurrencyOption(candidate, draft.currency, state.baseCurrency)?.let { option ->
                amount > option.amount
            } != false -> setError(
                "金额不能超过当前债务 ${selectedCurrencyOption(candidate, draft.currency, state.baseCurrency)?.amount?.toPlainString() ?: candidate.amount.toPlainString()}"
            )
            draft.allocationMode == SettlementAllocationMode.TARGETED &&
                (draft.targetExpenseIds.isEmpty() || selectedExpenses.size != draft.targetExpenseIds.distinct().size) ->
                setError("请选择当前仍可抵扣的账单")
            draft.allocationMode == SettlementAllocationMode.TARGETED && amount > targetedCap ->
                setError("金额不能超过所选账单的可抵扣金额 ${targetedCap.toPlainString()}")
            !previewMatches ->
                setError("账单抵扣预览已过期，请等待刷新后再提交")
            !isValidActingParty(state, candidate, draft.onBehalfOfParticipantId) -> setError("请选择有效的代记参与人")
            else -> {
                _uiState.value = state.copy(isSubmitting = true, errorMessage = null)
                viewModelScope.launch {
                    val currency = draft.currency.ifBlank { state.baseCurrency }.trim().uppercase()
                    val direction = loadedDirection ?: when (draft.mode) {
                        com.ffocalors.sharedledger.ui.screens.TransferMode.TRANSFER -> SettlementDirection.TRANSFER
                        com.ffocalors.sharedledger.ui.screens.TransferMode.RECEIVE -> SettlementDirection.RECEIVE
                    }
                    val pending = try {
                        resolvePendingRequest(
                            draft = draft,
                            candidate = candidate,
                            amount = amount,
                            currency = currency,
                            direction = direction,
                        )
                    } catch (_: Throwable) {
                        _uiState.value = _uiState.value.copy(
                            isSubmitting = false,
                            errorMessage = "无法保存转账重试凭据，请稍后重试",
                            writeState = TransferWriteState.FAILED,
                        )
                        return@launch
                    }
                    _uiState.value = _uiState.value.copy(pendingRequest = pending)
                    val input = CreateSettlementTransferInput(
                        activityId = draft.activityId,
                        fromParticipantId = pending.fromParticipantId,
                        toParticipantId = pending.toParticipantId,
                        amount = amount,
                        occurredAt = pending.occurredAt,
                        onBehalfOfParticipantId = pending.onBehalfOfParticipantId,
                        currency = pending.currency,
                        requestId = pending.requestId,
                        allocationMode = pending.allocationMode,
                        targetExpenseIds = pending.targetExpenseIds,
                        expectedFinancialVersion = pending.expectedFinancialVersion,
                    )
                    val result = repository.createSettlementWrite(input)
                    if (result.isSuccess && result.value != null) {
                        removePendingRequest(pending)
                        queryCache.invalidatePrefix("transfer-query:${draft.activityId}:")
                        invalidateFinancialReadCaches(draft.activityId)
                        _uiState.value = _uiState.value.copy(isSubmitting = false, pendingRequest = null)
                        onSuccess(result.value)
                    } else {
                        if (!result.isUnknown) removePendingRequest(pending)
                        if (result.isUnknown) {
                            queryCache.invalidatePrefix("transfer-query:${draft.activityId}:")
                            invalidateFinancialReadCaches(draft.activityId)
                        }
                        _uiState.value = _uiState.value.copy(
                            isSubmitting = false,
                            errorMessage = result.errorMessage ?: "转账失败",
                            submissionBlocked = false,
                            writeState = result.state,
                            pendingRequest = pending.takeIf { result.isUnknown },
                        )
                    }
                }
            }
        }
    }

    fun retry(onSuccess: (SettlementTransferResult) -> Unit = {}) {
        val pending = _uiState.value.pendingRequest
        if (_uiState.value.writeState == TransferWriteState.UNKNOWN && pending != null) {
            retryPending(pending, onSuccess)
            return
        }
        val activityId = loadedActivityId ?: return
        val direction = loadedDirection ?: return
        load(activityId, direction, force = true)
    }

    fun preview(draft: TransferDraft) {
        val state = _uiState.value
        val amount = draft.amount.toBigDecimalOrNull()
        val allCandidates = state.candidates + state.onBehalfCandidates
        val candidate = draft.candidateKey?.let { key -> allCandidates.firstOrNull { it.candidateKey == key } }
            ?: allCandidates.singleOrNull { it.participantId == draft.participantId }
            ?: run {
                previewGeneration += 1
                _uiState.value = state.copy(preview = null, isPreviewing = false, previewErrorMessage = null, previewRequired = true)
                return
            }
        val currency = draft.currency.trim().uppercase().ifBlank { state.baseCurrency }
        if (amount == null || amount <= BigDecimal.ZERO) {
            previewGeneration += 1
            _uiState.value = state.copy(preview = null, isPreviewing = false, previewErrorMessage = null, previewRequired = true)
            return
        }
        if (draft.allocationMode == SettlementAllocationMode.TARGETED && draft.targetExpenseIds.isEmpty()) {
            previewGeneration += 1
            _uiState.value = state.copy(preview = null, previewErrorMessage = null, isPreviewing = false, previewRequired = true)
            return
        }
        val input = PreviewSettlementInput(
            activityId = draft.activityId,
            fromParticipantId = candidate.fromParticipantId,
            toParticipantId = candidate.toParticipantId,
            amount = amount,
            currency = currency,
            allocationMode = draft.allocationMode,
            targetExpenseIds = draft.targetExpenseIds,
            expectedFinancialVersion = draft.expectedFinancialVersion,
        )
        val generation = ++previewGeneration
        _uiState.value = state.copy(isPreviewing = true, preview = null, previewErrorMessage = null, previewRequired = true)
        viewModelScope.launch {
            repository.previewSettlement(input).fold(
                onSuccess = { preview ->
                    if (generation == previewGeneration) {
                        _uiState.value = _uiState.value.copy(
                            isPreviewing = false,
                            preview = preview,
                            previewErrorMessage = null,
                        )
                    }
                },
                onFailure = { error ->
                    if (generation == previewGeneration) {
                        _uiState.value = _uiState.value.copy(
                            isPreviewing = false,
                            preview = null,
                            previewErrorMessage = messageFor(error),
                        )
                    }
                },
            )
        }
    }

    private fun retryPending(
        pending: PendingTransferRequest,
        onSuccess: (SettlementTransferResult) -> Unit = {},
    ) {
        if (_uiState.value.isSubmitting) return
        val amount = pending.amount.toBigDecimalOrNull() ?: return
        _uiState.value = _uiState.value.copy(isSubmitting = true, errorMessage = null)
        viewModelScope.launch {
            val input = CreateSettlementTransferInput(
                activityId = pending.activityId,
                fromParticipantId = pending.fromParticipantId,
                toParticipantId = pending.toParticipantId,
                amount = amount,
                occurredAt = pending.occurredAt,
                onBehalfOfParticipantId = pending.onBehalfOfParticipantId,
                currency = pending.currency,
                requestId = pending.requestId,
                allocationMode = pending.allocationMode,
                targetExpenseIds = pending.targetExpenseIds,
                expectedFinancialVersion = pending.expectedFinancialVersion,
            )
            val result = repository.createSettlementWrite(input)
            if (result.isSuccess && result.value != null) {
                removePendingRequest(pending)
                queryCache.invalidatePrefix("transfer-query:${pending.activityId}:")
                invalidateFinancialReadCaches(pending.activityId)
                _uiState.value = _uiState.value.copy(
                    isSubmitting = false,
                    pendingRequest = null,
                    writeState = TransferWriteState.SUCCEEDED,
                )
                onSuccess(result.value)
            } else {
                _uiState.value = _uiState.value.copy(
                    isSubmitting = false,
                    errorMessage = result.errorMessage ?: "转账失败",
                    writeState = result.state,
                    pendingRequest = pending,
                )
            }
        }
    }

    /** Called by Realtime or after an external financial write. */
    fun invalidateActivity(activityId: String? = null) {
        if (activityId.isNullOrBlank()) {
            queryCache.invalidatePrefix("transfer-query:")
            queryCache.invalidatePrefix("financial-query:")
        } else {
            queryCache.invalidatePrefix("transfer-query:$activityId:")
            queryCache.invalidatePrefix("financial-query:list:$activityId")
            queryCache.invalidatePrefix("financial-query:detail:$activityId:")
            queryCache.invalidatePrefix("financial-query:context:$activityId")
            queryCache.invalidatePrefix("financial-query:preview:$activityId")
        }
    }

    private suspend fun enrichExpenseOptions(
        context: com.ffocalors.sharedledger.data.transfer.SettlementContext,
    ) {
        val candidates = context.candidates + context.onBehalfCandidates
        if (candidates.isEmpty()) return
        val enriched = candidates.map { candidate ->
            val currencies = (candidate.currencyOptions.map { it.normalizedCurrencyCode } + context.baseCurrency)
                .distinct()
            val rows = currencies.flatMap { currency ->
                repository.loadExpenseCandidates(
                    activityId = context.activityId,
                    fromParticipantId = candidate.fromParticipantId,
                    toParticipantId = candidate.toParticipantId,
                    currency = currency,
                ).getOrDefault(emptyList())
            }.distinctBy { it.expenseId }
            candidate.copy(expenseOptions = rows)
        }
        val byKey = enriched.associateBy { it.candidateKey }
        val latest = _uiState.value
        _uiState.value = latest.copy(
            candidates = latest.candidates.mapNotNull { item -> byKey[item.candidateKey]?.let(::toUi) },
            onBehalfCandidates = latest.onBehalfCandidates.mapNotNull { item -> byKey[item.candidateKey]?.let(::toUi) },
        )
    }

    fun clearSessionCache() = queryCache.clear()

    private fun invalidateFinancialReadCaches(activityId: String) {
        queryCache.invalidatePrefix("financial-query:list:$activityId")
        queryCache.invalidatePrefix("financial-query:detail:$activityId:")
        queryCache.invalidatePrefix("financial-query:context:$activityId")
        queryCache.invalidatePrefix("financial-query:preview:$activityId")
    }

    private fun setError(message: String) {
        _uiState.value = _uiState.value.copy(errorMessage = message)
    }

    private fun toUi(candidate: SettlementCandidate) = TransferCandidateUi(
        candidateKey = candidate.candidateKey,
        participantId = candidate.participantId,
        participantName = candidate.participantName,
        amount = candidate.amount,
        fromParticipantId = candidate.fromParticipantId,
        fromParticipantName = candidate.fromParticipantName,
        toParticipantId = candidate.toParticipantId,
        toParticipantName = candidate.toParticipantName,
        kind = candidate.kind,
        onBehalfOptions = candidate.onBehalfOptions,
        currencyOptions = candidate.currencyOptions,
        expenseOptions = candidate.expenseOptions,
        claimedUserId = candidate.claimedUserId,
        avatarStyle = candidate.avatarStyle,
    )

    private fun toUiState(
        context: com.ffocalors.sharedledger.data.transfer.SettlementContext,
        direction: SettlementDirection,
    ) = TransferUiState(
        isLoading = false,
        baseCurrency = context.baseCurrency,
        multiCurrencyEnabled = context.multiCurrencyEnabled,
        currentParticipantId = context.currentParticipantId,
        canActOnBehalf = context.canActOnBehalf,
        candidates = context.candidates.map(::toUi),
        onBehalfCandidates = context.onBehalfCandidates.map(::toUi),
        emptyMessage = when {
            context.candidates.isNotEmpty() || context.onBehalfCandidates.isNotEmpty() -> null
            context.canActOnBehalf -> null
            context.currentParticipantId == null -> "当前用户尚未绑定参与人，请先在活动管理中绑定"
            direction == SettlementDirection.TRANSFER -> "当前没有待付款债务"
            else -> "当前没有待收款债务"
        },
    )

    private fun contextKey(activityId: String, direction: SettlementDirection) =
        QueryCacheKey<com.ffocalors.sharedledger.data.transfer.SettlementContext>(
            "transfer-query:$activityId:${direction.name}",
        )

    private fun isValidActingParty(
        state: TransferUiState,
        candidate: TransferCandidateUi,
        onBehalfOfParticipantId: String?,
    ): Boolean {
        return when (candidate.kind) {
            SettlementCandidateKind.PERSONAL -> {
                val expectedCurrentParticipantId = when (loadedDirection) {
                    SettlementDirection.TRANSFER -> candidate.fromParticipantId
                    SettlementDirection.RECEIVE -> candidate.toParticipantId
                    null -> return false
                }
                state.currentParticipantId == expectedCurrentParticipantId && onBehalfOfParticipantId == null
            }
            SettlementCandidateKind.ON_BEHALF -> state.canActOnBehalf &&
                onBehalfOfParticipantId != null &&
                candidate.onBehalfOptions.any { it.participantId == onBehalfOfParticipantId }
        }
    }

    private fun selectedCurrencyOption(
        candidate: TransferCandidateUi,
        requestedCurrency: String,
        baseCurrency: String,
    ): SettlementCurrencyOption? {
        val currency = requestedCurrency.trim().uppercase().ifBlank { baseCurrency }
        return candidate.currencyOptions.firstOrNull { it.normalizedCurrencyCode == currency }
            ?: candidate.currencyOptions.firstOrNull { it.normalizedCurrencyCode == baseCurrency }
            ?: candidate.currencyOptions.firstOrNull()
            ?: SettlementCurrencyOption(baseCurrency, candidate.amount)
    }

    private suspend fun resolvePendingRequest(
        draft: TransferDraft,
        candidate: TransferCandidateUi,
        amount: BigDecimal,
        currency: String,
        direction: SettlementDirection,
    ): PendingTransferRequest {
        val type = "settlement"
        val stored = requestStore.read(currentUserId, draft.activityId, direction)
            .asReversed()
            .firstOrNull { pending ->
                pending.matches(
                    activityId = draft.activityId,
                    direction = direction,
                    fromParticipantId = candidate.fromParticipantId,
                    toParticipantId = candidate.toParticipantId,
                    amount = amount,
                    currency = currency,
                    type = type,
                    onBehalfOfParticipantId = draft.onBehalfOfParticipantId,
                    occurredAt = draft.occurredAt,
                    allocationMode = draft.allocationMode,
                    targetExpenseIds = draft.targetExpenseIds,
                )
            }
        if (stored != null) return stored

        // A changed payload always gets a new id. Reusing a caller-supplied id
        // here could replay a previously submitted payload after an edit.
        val requestId = UUID.randomUUID().toString()
        val request = PendingTransferRequest(
            requestId = requestId,
            activityId = draft.activityId,
            direction = direction,
            fromParticipantId = candidate.fromParticipantId,
            toParticipantId = candidate.toParticipantId,
            amount = amount.stripTrailingZeros().toPlainString(),
            currency = currency,
            type = type,
            occurredAt = draft.occurredAt?.trim().takeUnless { it.isNullOrBlank() }
                ?: Instant.now().toString(),
            onBehalfOfParticipantId = draft.onBehalfOfParticipantId,
            allocationMode = draft.allocationMode,
            targetExpenseIds = draft.targetExpenseIds,
            expectedFinancialVersion = draft.expectedFinancialVersion,
            createdAtEpochMillis = System.currentTimeMillis(),
        )
        requestStore.upsert(currentUserId, request)
        return request
    }

    private suspend fun readPendingRequest(
        activityId: String,
        direction: SettlementDirection,
    ): PendingTransferRequest? = runCatching {
        requestStore.read(currentUserId, activityId, direction)
            // The store appends each newly-created payload. Prefer list order
            // over wall-clock ties so an edit made within one millisecond still
            // restores the newest form identity.
            .lastOrNull()
    }.getOrNull()

    private suspend fun removePendingRequest(request: PendingTransferRequest) {
        runCatching { requestStore.remove(currentUserId, request) }
    }

    private fun messageFor(error: Throwable): String =
        (error as? com.ffocalors.sharedledger.data.transfer.TransferOperationException)?.userMessage
            ?: TransferErrorMapper.toUserMessage(error)

    class Factory(
        private val repository: TransferRepository = TransferRepositoryFactory.create(),
        private val queryCache: SessionQueryCache = SessionQueryCache(),
        private val currentUserId: String = "",
        private val context: Context? = null,
        private val requestStore: TransferRequestStore? = null,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = TransferViewModel(
            repository = repository,
            queryCache = queryCache,
            currentUserId = currentUserId,
            requestStore = requestStore ?: context?.let(::PreferencesTransferRequestStore)
                ?: InMemoryTransferRequestStore(),
        ) as T
    }
}
