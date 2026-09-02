package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.domain.financial.TransferDispute

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

interface FinancialRecordRepository {
    /**
     * Creation boundary for the future RPC adapter. The caller supplies the complete domain
     * record; a real implementation can replace this with the RPC response/returned transferId.
     */
    fun create(record: FundRecord): FinancialWriteResult<FundRecord>

    fun list(activityId: String, type: FundRecordType? = null): FinancialReadResult<List<FundRecord>>
    fun get(activityId: String, transferId: String): FinancialReadResult<FundRecord>
    fun void(
        activityId: String,
        transferId: String,
        reason: String,
    ): FinancialWriteResult<FundRecord>

    fun addDispute(
        activityId: String,
        transferId: String,
        participantId: String,
        note: String,
    ): FinancialWriteResult<TransferDispute>

    fun resolveDispute(
        activityId: String,
        disputeId: String,
    ): FinancialWriteResult<TransferDispute>
}
