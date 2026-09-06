package com.ffocalors.sharedledger.ui.transfer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.data.transfer.SettlementTransferResult
import com.ffocalors.sharedledger.data.transfer.TransferErrorMapper
import com.ffocalors.sharedledger.data.transfer.TransferRepository
import com.ffocalors.sharedledger.data.transfer.TransferRepositoryFactory
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
)

data class TransferUiState(
    val isLoading: Boolean = true,
    val baseCurrency: String = "CNY",
    val currentParticipantId: String? = null,
    val candidates: List<TransferCandidateUi> = emptyList(),
    val errorMessage: String? = null,
    val emptyMessage: String? = null,
    val isSubmitting: Boolean = false,
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
                        candidates = context.candidates.map(::toUi),
                        emptyMessage = if (context.currentParticipantId == null) {
                            "当前用户尚未绑定参与人，请先在活动管理中绑定"
                        } else if (context.candidates.isEmpty()) {
                            if (direction == SettlementDirection.TRANSFER) "当前没有待付款债务" else "当前没有待收款债务"
                        } else null,
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
        if (state.isSubmitting) return
        val amount = draft.amount.toBigDecimalOrNull()
        val candidate = state.candidates.firstOrNull { it.participantId == draft.participantId }
        when {
            state.currentParticipantId.isNullOrBlank() -> setError("当前用户尚未绑定参与人，请先在活动管理中绑定")
            candidate == null -> setError("请选择当前仍有债务的参与人")
            amount == null || amount <= BigDecimal.ZERO -> setError("请输入大于 0 的金额")
            amount > candidate.amount -> setError("金额不能超过当前债务 ${candidate.amount.toPlainString()}")
            else -> {
                _uiState.value = state.copy(isSubmitting = true, errorMessage = null)
                viewModelScope.launch {
                    val input = CreateSettlementTransferInput(
                        activityId = draft.activityId,
                        currentParticipantId = state.currentParticipantId!!,
                        selectedParticipantId = draft.participantId,
                        amount = amount,
                        direction = if (draft.mode.name == "RECEIVE") SettlementDirection.RECEIVE else SettlementDirection.TRANSFER,
                        occurredAt = Instant.now().toString(),
                    )
                    repository.createSettlement(input).fold(
                        onSuccess = { result ->
                            _uiState.value = _uiState.value.copy(isSubmitting = false)
                            onSuccess(result)
                        },
                        onFailure = { error ->
                            _uiState.value = _uiState.value.copy(isSubmitting = false, errorMessage = messageFor(error))
                        },
                    )
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
        participantId = candidate.participantId,
        participantName = candidate.participantName,
        amount = candidate.amount,
    )

    private fun messageFor(error: Throwable): String =
        (error as? com.ffocalors.sharedledger.data.transfer.TransferOperationException)?.userMessage
            ?: TransferErrorMapper.toUserMessage(error)

    class Factory(private val repository: TransferRepository = TransferRepositoryFactory.create()) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = TransferViewModel(repository) as T
    }
}

