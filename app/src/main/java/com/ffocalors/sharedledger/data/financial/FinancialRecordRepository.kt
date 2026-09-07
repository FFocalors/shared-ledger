package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.domain.financial.TransferDispute
import java.math.BigDecimal

sealed interface FinancialReadResult<out T> {
    data class Success<T>(val value: T) : FinancialReadResult<T>
    data class Failure(val message: String) : FinancialReadResult<Nothing>
}

/** Every successful mutation asks the caller to re-query; no local balance projection is kept. */
data class FinancialWriteResult<out T>(
    val value: T?,
    val errorMessage: String? = null,
    val requiresRefresh: Boolean = true,
) {
    val isSuccess: Boolean get() = value != null && errorMessage == null

    companion object {
        fun <T> success(value: T): FinancialWriteResult<T> = FinancialWriteResult(value)
        fun <T> failure(message: String): FinancialWriteResult<T> =
            FinancialWriteResult(value = null, errorMessage = message, requiresRefresh = false)
    }
}

data class PrepaymentAccount(
    val accountId: String,
    val owner: com.ffocalors.sharedledger.domain.financial.ParticipantInfo,
    val custodian: com.ffocalors.sharedledger.domain.financial.ParticipantInfo,
    val balance: BigDecimal,
    /** Amount already consumed by expense debts from this account. */
    val usedAmount: BigDecimal = BigDecimal.ZERO,
)

data class FinancialContext(
    val activityId: String,
    val currency: String,
    val participants: List<com.ffocalors.sharedledger.domain.financial.ParticipantInfo>,
    val currentParticipantId: String?,
    val accounts: List<PrepaymentAccount>,
)

data class FinalSettlementSuggestion(
    val id: String,
    val activityId: String,
    val from: com.ffocalors.sharedledger.domain.financial.ParticipantInfo,
    val to: com.ffocalors.sharedledger.domain.financial.ParticipantInfo,
    val amount: BigDecimal,
    val ordinaryAmount: BigDecimal,
    val prepaymentReturnAmount: BigDecimal,
    val currency: String,
    val sourceFinancialVersion: Long,
)

data class PrepaymentInput(
    val activityId: String,
    val ownerParticipantId: String,
    val custodianParticipantId: String,
    val amount: BigDecimal,
    val occurredAt: String,
)

interface FinancialRecordRepository {
    /**
     * Creation boundary for the future RPC adapter. The caller supplies the complete domain
     * record; a real implementation can replace this with the RPC response/returned transferId.
     */
    suspend fun create(record: FundRecord): FinancialWriteResult<FundRecord>

    suspend fun list(activityId: String, type: FundRecordType? = null): FinancialReadResult<List<FundRecord>>
    suspend fun get(activityId: String, transferId: String): FinancialReadResult<FundRecord>
    suspend fun void(
        activityId: String,
        transferId: String,
        reason: String,
    ): FinancialWriteResult<FundRecord>

    suspend fun addDispute(
        activityId: String,
        transferId: String,
        participantId: String,
        note: String,
    ): FinancialWriteResult<TransferDispute>

    suspend fun resolveDispute(
        activityId: String,
        disputeId: String,
    ): FinancialWriteResult<TransferDispute>

    suspend fun loadPrepaymentContext(activityId: String): FinancialReadResult<FinancialContext>

    suspend fun currentParticipantId(activityId: String): FinancialReadResult<String?>

    suspend fun createPrepayment(input: PrepaymentInput): FinancialWriteResult<FundRecord>

    suspend fun createPrepaymentReturn(input: PrepaymentInput): FinancialWriteResult<FundRecord>

    suspend fun previewFinalSettlement(activityId: String): FinancialReadResult<List<FinalSettlementSuggestion>>

    suspend fun executeFinalSettlement(
        request: FinalSettlementSuggestion,
        occurredAt: String,
    ): FinancialWriteResult<FundRecord>
}
