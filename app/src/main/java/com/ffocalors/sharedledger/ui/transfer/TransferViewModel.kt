package com.ffocalors.sharedledger.ui.transfer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementCandidateKind
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.data.transfer.SettlementTransferResult
import com.ffocalors.sharedledger.data.transfer.SettlementParticipant
import com.ffocalors.sharedledger.data.transfer.TransferErrorMapper
import com.ffocalors.sharedledger.data.transfer.TransferRepository
import com.ffocalors.sharedledger.data.transfer.TransferRepositoryFactory
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
    val candidateKey: String = "${kind.name}:$fromParticipantId->$toParticipantId",
    val claimedUserId: String? = null,
    val avatarStyle: String? = null,
)

data class TransferUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val baseCurrency: String = "CNY",
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
)

class TransferViewModel(
    private val repository: TransferRepository,
    private val queryCache: SessionQueryCache = SessionQueryCache(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(TransferUiState())
    val uiState: StateFlow<TransferUiState> = _uiState.asStateFlow()
    private var loadedActivityId: String? = null
    private var loadedDirection: SettlementDirection? = null

    fun load(activityId: String, direction: SettlementDirection, force: Boolean = false) {
        val key = contextKey(activityId, direction)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            _uiState.value = toUiState(cached.value, direction)
            loadedActivityId = activityId
            loadedDirection = direction
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
                onSuccess = { _uiState.value = toUiState(it, direction) },
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
        if (state.isSubmitting || state.submissionBlocked) return
        val amount = draft.amount.toBigDecimalOrNull()
        val allCandidates = state.candidates + state.onBehalfCandidates
        val candidate = draft.candidateKey?.let { key ->
            allCandidates.firstOrNull { it.candidateKey == key }
        } ?: allCandidates.singleOrNull { it.participantId == draft.participantId }
        when {
            state.currentParticipantId.isNullOrBlank() && draft.onBehalfOfParticipantId == null ->
                setError("当前用户尚未绑定参与人，请先选择代记参与人")
            candidate == null -> setError("请选择当前仍有债务的参与人")
            amount == null || amount <= BigDecimal.ZERO -> setError("请输入大于 0 的金额")
            amount > candidate.amount -> setError("金额不能超过当前债务 ${candidate.amount.toPlainString()}")
            !isValidActingParty(state, candidate, draft.onBehalfOfParticipantId) -> setError("请选择有效的代记参与人")
            else -> {
                _uiState.value = state.copy(isSubmitting = true, errorMessage = null)
                viewModelScope.launch {
                    val input = CreateSettlementTransferInput(
                        activityId = draft.activityId,
                        fromParticipantId = candidate.fromParticipantId,
                        toParticipantId = candidate.toParticipantId,
                        amount = amount,
                        occurredAt = Instant.now().toString(),
                        onBehalfOfParticipantId = draft.onBehalfOfParticipantId,
                    )
                    val result = repository.createSettlementWrite(input)
                    if (result.isSuccess && result.value != null) {
                        queryCache.invalidatePrefix("transfer-query:${draft.activityId}:")
                        invalidateFinancialReadCaches(draft.activityId)
                        _uiState.value = _uiState.value.copy(isSubmitting = false)
                        onSuccess(result.value)
                    } else {
                        if (result.isUnknown) {
                            queryCache.invalidatePrefix("transfer-query:${draft.activityId}:")
                            invalidateFinancialReadCaches(draft.activityId)
                        }
                        _uiState.value = _uiState.value.copy(
                            isSubmitting = false,
                            errorMessage = result.errorMessage ?: "转账失败",
                            submissionBlocked = result.isUnknown,
                            writeState = result.state,
                        )
                    }
                }
            }
        }
    }

    fun retry() {
        val activityId = loadedActivityId ?: return
        val direction = loadedDirection ?: return
        load(activityId, direction, force = true)
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
        claimedUserId = candidate.claimedUserId,
        avatarStyle = candidate.avatarStyle,
    )

    private fun toUiState(
        context: com.ffocalors.sharedledger.data.transfer.SettlementContext,
        direction: SettlementDirection,
    ) = TransferUiState(
        isLoading = false,
        baseCurrency = context.baseCurrency,
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

    private fun messageFor(error: Throwable): String =
        (error as? com.ffocalors.sharedledger.data.transfer.TransferOperationException)?.userMessage
            ?: TransferErrorMapper.toUserMessage(error)

    class Factory(
        private val repository: TransferRepository = TransferRepositoryFactory.create(),
        private val queryCache: SessionQueryCache = SessionQueryCache(),
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = TransferViewModel(repository, queryCache) as T
    }
}
