package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal

enum class SettlementDirection {
    TRANSFER,
    RECEIVE,
}

enum class SettlementCandidateKind {
    PERSONAL,
    ON_BEHALF,
}

data class SettlementCandidate(
    val participantId: String,
    val participantName: String,
    val amount: BigDecimal,
    val fromParticipantId: String,
    val fromParticipantName: String,
    val toParticipantId: String,
    val toParticipantName: String,
    val kind: SettlementCandidateKind = SettlementCandidateKind.PERSONAL,
    val onBehalfOptions: List<SettlementParticipant> = emptyList(),
    val claimedUserId: String? = null,
    val avatarStyle: String? = null,
    val currencyOptions: List<SettlementCurrencyOption> = emptyList(),
) {
    /** Stable identity for one directed bilateral debt, even when the target repeats. */
    val candidateKey: String
        get() = "${kind.name}:$fromParticipantId->$toParticipantId"
}

data class SettlementParticipant(
    val participantId: String,
    val participantName: String,
)

/** A server-authorized currency and its current settlement cap for one debt direction. */
data class SettlementCurrencyOption(
    val currencyCode: String,
    val amount: BigDecimal,
    val baseAmount: BigDecimal? = null,
    val financialVersion: Long? = null,
    val baseTotal: BigDecimal? = null,
) {
    val normalizedCurrencyCode: String get() = currencyCode.trim().uppercase()
}

data class SettlementContext(
    val activityId: String,
    val currentParticipantId: String?,
    val currentParticipantName: String?,
    val baseCurrency: String,
    val multiCurrencyEnabled: Boolean = false,
    val candidates: List<SettlementCandidate> = emptyList(),
    val onBehalfCandidates: List<SettlementCandidate> = emptyList(),
    val canActOnBehalf: Boolean = false,
)

data class SettlementAvatarInfo(
    val claimedUserId: String,
    val avatarStyle: String?,
)

data class CreateSettlementTransferInput(
    val activityId: String,
    val fromParticipantId: String,
    val toParticipantId: String,
    val amount: BigDecimal,
    val occurredAt: String,
    val onBehalfOfParticipantId: String? = null,
    val currency: String = "CNY",
    val requestId: String? = null,
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
