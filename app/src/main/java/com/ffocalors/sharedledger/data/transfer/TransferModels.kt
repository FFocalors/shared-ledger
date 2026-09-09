package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal

enum class SettlementDirection {
    TRANSFER,
    RECEIVE,
}

data class SettlementCandidate(
    val participantId: String,
    val participantName: String,
    val amount: BigDecimal,
    val fromParticipantId: String? = null,
    val fromParticipantName: String? = null,
    val toParticipantId: String? = null,
    val toParticipantName: String? = null,
    val onBehalfOptions: List<SettlementParticipant> = emptyList(),
) {
    /** Stable identity for one directed bilateral debt, even when the target repeats. */
    val candidateKey: String
        get() = "${fromParticipantId.orEmpty()}->${toParticipantId.orEmpty()}"
}

data class SettlementParticipant(
    val participantId: String,
    val participantName: String,
)

data class SettlementContext(
    val activityId: String,
    val currentParticipantId: String?,
    val currentParticipantName: String?,
    val baseCurrency: String,
    val candidates: List<SettlementCandidate>,
    val canActOnBehalf: Boolean = false,
)

data class CreateSettlementTransferInput(
    val activityId: String,
    val currentParticipantId: String,
    val selectedParticipantId: String,
    val amount: BigDecimal,
    val direction: SettlementDirection,
    val occurredAt: String,
    val onBehalfOfParticipantId: String? = null,
)

data class SettlementTransferResult(
    val transferId: String,
    val amount: BigDecimal,
    val currency: String,
    val financialVersion: Long,
)

enum class TransferWriteState {
    SUCCEEDED,
    FAILED,
    UNKNOWN,
}

data class TransferWriteResult<out T>(
    val value: T? = null,
    val errorMessage: String? = null,
    val state: TransferWriteState = if (value != null && errorMessage == null) {
        TransferWriteState.SUCCEEDED
    } else {
        TransferWriteState.FAILED
    },
) {
    val isSuccess: Boolean get() = state == TransferWriteState.SUCCEEDED && value != null
    val isUnknown: Boolean get() = state == TransferWriteState.UNKNOWN

    companion object {
        fun <T> success(value: T) = TransferWriteResult(value = value)
        fun <T> failure(message: String) = TransferWriteResult<T>(errorMessage = message)
        fun <T> unknown(message: String) = TransferWriteResult<T>(
            errorMessage = message,
            state = TransferWriteState.UNKNOWN,
        )
    }
}
