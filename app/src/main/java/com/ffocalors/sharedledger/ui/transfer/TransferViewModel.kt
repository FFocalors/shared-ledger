package com.ffocalors.sharedledger.ui.transfer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.data.transfer.SettlementTransferResult
import com.ffocalors.sharedledger.data.transfer.SettlementParticipant
import com.ffocalors.sharedledger.data.transfer.TransferErrorMapper
import com.ffocalors.sharedledger.data.transfer.TransferRepository
import com.ffocalors.sharedledger.data.transfer.TransferRepositoryFactory
import com.ffocalors.sharedledger.data.transfer.TransferWriteState
import com.ffocalors.sharedledger.ui.screens.TransferDraft
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
    val fromParticipantId: String? = null,
    val fromParticipantName: String? = null,
    val toParticipantId: String? = null,
    val toParticipantName: String? = null,
    val onBehalfOptions: List<SettlementParticipant> = emptyList(),
    val candidateKey: String = "${fromParticipantId.orEmpty()}->${toParticipantId.orEmpty()}",
)

data class TransferUiState(
    val isLoading: Boolean = true,
    val baseCurrency: String = "CNY",
    val currentParticipantId: String? = null,
    val canActOnBehalf: Boolean = false,
    val candidates: List<TransferCandidateUi> = emptyList(),
    val errorMessage: String? = null,
    val emptyMessage: String? = null,
    val isSubmitting: Boolean = false,
    val submissionBlocked: Boolean = false,
    val writeState: TransferWriteState? = null,
)

class TransferViewModel(
    private val repository: TransferRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(TransferUiState())
    val uiState: StateFlow<TransferUiState> = _uiState.asStateFlow()
    private var loadedActivityId: String? = null
    private var loadedDirection: SettlementDirection? = null

    fun load(activityId: String, direction: SettlementDirection, force: Boolean = false) {
        if (!force && loadedActivityId == activityId && loadedDirection == direction &&
            !_uiState.value.isLoading && _uiState.value.errorMessage == null
        ) return
        loadedActivityId = activityId
        loadedDirection = direction
        viewModelScope.launch {
            _uiState.value = TransferUiState(isLoading = true)
            repository.loadContext(activityId, direction).fold(
                onSuccess = { context ->
                    _uiState.value = TransferUiState(
                        isLoading = false,
                        baseCurrency = context.baseCurrency,
                        currentParticipantId = context.currentParticipantId,
                        canActOnBehalf = context.canActOnBehalf,
                        candidates = context.candidates.map(::toUi),
                        emptyMessage = when {
                            context.candidates.isNotEmpty() -> null
                            context.currentParticipantId == null -> "当前用户尚未绑定参与人，请先在活动管理中绑定"
                            direction == SettlementDirection.TRANSFER -> "当前没有待付款债务"
                            else -> "当前没有待收款债务"
                        },
                    )
                },
                onFailure = { error ->
            _uiState.value = TransferUiState(isLoading = false, errorMessage = messageFor(error))
                },
            )
        }
    }

    fun submit(draft: TransferDraft, onSuccess: (SettlementTransferResult) -> Unit = {}) {
        val state = _uiState.value
        if (state.isSubmitting || state.submissionBlocked) return
        val amount = draft.amount.toBigDecimalOrNull()
        val candidate = draft.candidateKey?.let { key ->
            state.candidates.firstOrNull { it.candidateKey == key }
        } ?: state.candidates.firstOrNull { draft.candidateKey == null && it.participantId == draft.participantId }
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
                    val direction = if (draft.mode.name == "RECEIVE") SettlementDirection.RECEIVE else SettlementDirection.TRANSFER
                    val currentParticipantId = state.currentParticipantId
                        ?: when (direction) {
                            SettlementDirection.TRANSFER -> candidate.fromParticipantId
                            SettlementDirection.RECEIVE -> candidate.toParticipantId
                        }
                    if (currentParticipantId.isNullOrBlank()) {
                        _uiState.value = _uiState.value.copy(isSubmitting = false, errorMessage = "结算方向信息已失效，请重新加载")
                        return@launch
                    }
                    val input = CreateSettlementTransferInput(
                        activityId = draft.activityId,
                        currentParticipantId = currentParticipantId,
                        selectedParticipantId = draft.participantId,
                        amount = amount,
                        direction = direction,
                        occurredAt = Instant.now().toString(),
                        onBehalfOfParticipantId = draft.onBehalfOfParticipantId,
                    )
                    val result = repository.createSettlementWrite(input)
                    if (result.isSuccess && result.value != null) {
                            _uiState.value = _uiState.value.copy(isSubmitting = false)
                            onSuccess(result.value)
                    } else {
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
        onBehalfOptions = candidate.onBehalfOptions,
    )

    private fun isValidActingParty(
        state: TransferUiState,
        candidate: TransferCandidateUi,
        onBehalfOfParticipantId: String?,
    ): Boolean {
        val from = candidate.fromParticipantId ?: return onBehalfOfParticipantId == null
        val to = candidate.toParticipantId ?: return onBehalfOfParticipantId == null
        val currentIsParty = state.currentParticipantId == from || state.currentParticipantId == to
        if (!currentIsParty && onBehalfOfParticipantId == null) return false
        if (onBehalfOfParticipantId == null) return true
        return state.canActOnBehalf && candidate.onBehalfOptions.any { it.participantId == onBehalfOfParticipantId }
    }

    private fun messageFor(error: Throwable): String =
        (error as? com.ffocalors.sharedledger.data.transfer.TransferOperationException)?.userMessage
            ?: TransferErrorMapper.toUserMessage(error)

    class Factory(private val repository: TransferRepository = TransferRepositoryFactory.create()) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = TransferViewModel(repository) as T
    }
}
