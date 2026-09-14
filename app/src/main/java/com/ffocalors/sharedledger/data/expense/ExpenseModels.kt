package com.ffocalors.sharedledger.data.expense

import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.data.common.StructuredReadFailure
import java.math.BigDecimal

enum class ExpenseSplitMethod(val backendValue: String) {
    Aa("aa"),
    Manual("manual"),
}

data class Payment(
    val id: String,
    val expenseId: String,
    val participantId: String,
    val amount: BigDecimal,
    val baseAmount: BigDecimal?,
)

data class Split(
    val id: String,
    val expenseId: String,
    val participantId: String,
    val amount: BigDecimal,
    val baseAmount: BigDecimal?,
)

data class Expense(
    val id: String,
    val ledgerUnitId: String,
    val title: String,
    val originalAmount: BigDecimal,
    val originalCurrency: String,
    val fxRate: BigDecimal,
    val baseAmount: BigDecimal,
    val splitMethod: ExpenseSplitMethod,
    val occurredAt: String,
    val note: String?,
    val originalExpenseId: String?,
    val createdBy: String,
    val updatedBy: String,
    val createdAt: String?,
    val updatedAt: String?,
    val version: Long,
    val isDeleted: Boolean,
    val fxRateSource: String = "legacy_manual",
    val fxRateObservedAt: String? = null,
)

data class ExpenseLedgerUnit(
    val id: String,
    val activityId: String,
    val name: String,
    val type: String,
)

data class ExpenseParticipant(
    val id: String,
    val activityId: String,
    val name: String,
    val order: Int,
)

data class ExpenseDebtSettlement(
    val debtId: String,
    val debtorParticipantId: String,
    val amount: BigDecimal,
    val settledAmount: BigDecimal,
) {
    val remainingAmount: BigDecimal
        get() = (amount - settledAmount).max(BigDecimal.ZERO)
}

data class ExpenseDetail(
    val expense: Expense,
    val ledgerUnit: ExpenseLedgerUnit,
    val baseCurrency: String,
    val payments: List<Payment>,
    val splits: List<Split>,
    val participants: List<ExpenseParticipant>,
    val debtSettlements: List<ExpenseDebtSettlement> = emptyList(),
)

data class PaymentInput(
    val participantId: String,
    val amount: BigDecimal,
)

data class ManualSplitInput(
    val participantId: String,
    val amount: BigDecimal,
)

data class CreateExpenseInput(
    val ledgerUnitId: String,
    val title: String,
    val originalAmount: BigDecimal,
    val originalCurrency: String,
    val fxRate: BigDecimal,
    val splitMethod: ExpenseSplitMethod,
    val payments: List<PaymentInput>,
    val manualSplits: List<ManualSplitInput> = emptyList(),
    val aaParticipantIds: List<String> = emptyList(),
    val occurredAt: String,
    val note: String? = null,
    val originalExpenseId: String? = null,
)

data class UpdateExpenseInput(
    val expenseId: String,
    val ledgerUnitId: String,
    val title: String,
    val originalAmount: BigDecimal,
    val originalCurrency: String,
    val fxRate: BigDecimal,
    val splitMethod: ExpenseSplitMethod,
    val payments: List<PaymentInput>,
    val manualSplits: List<ManualSplitInput> = emptyList(),
    val aaParticipantIds: List<String> = emptyList(),
    val occurredAt: String,
    val note: String? = null,
    val originalExpenseId: String? = null,
)

data class RefundExpenseInput(
    val ledgerUnitId: String,
    val title: String,
    val amount: BigDecimal,
    val originalCurrency: String,
    val fxRate: BigDecimal,
    val splitMethod: ExpenseSplitMethod,
    val payments: List<PaymentInput>,
    val manualSplits: List<ManualSplitInput> = emptyList(),
    val aaParticipantIds: List<String> = emptyList(),
    val occurredAt: String,
    val note: String? = null,
    val originalExpenseId: String? = null,
) {
    fun toCreateInput(originalExpenseId: String? = this.originalExpenseId): CreateExpenseInput {
        val refundAmount = amount.abs().negate()
        return CreateExpenseInput(
            ledgerUnitId = ledgerUnitId,
            title = title,
            originalAmount = refundAmount,
            originalCurrency = originalCurrency,
            fxRate = fxRate,
            splitMethod = splitMethod,
            payments = payments.map { it.copy(amount = it.amount.abs().negate()) },
            manualSplits = manualSplits.map { it.copy(amount = it.amount.abs().negate()) },
            aaParticipantIds = aaParticipantIds,
            occurredAt = occurredAt,
            note = note,
            originalExpenseId = originalExpenseId,
        )
    }
}

data class ExpenseMutationResult(
    val expenseId: String,
    val baseAmount: BigDecimal?,
    val version: Long,
    val changed: Boolean? = null,
    val fxRate: BigDecimal? = null,
    val fxRateSource: String? = null,
    val fxRateObservedAt: String? = null,
)

enum class ExpenseWriteState {
    SUCCEEDED,
    FAILED,
    COMMITTED_REFRESH_FAILED,
    UNKNOWN,
}

data class ExpenseWriteResult<out T>(
    val value: T? = null,
    val errorMessage: String? = null,
    val state: ExpenseWriteState = if (value != null && errorMessage == null) {
        ExpenseWriteState.SUCCEEDED
    } else {
        ExpenseWriteState.FAILED
    },
    val operationId: String? = null,
) {
    val isSuccess: Boolean get() = state == ExpenseWriteState.SUCCEEDED && value != null
    val isCommitted: Boolean get() = state == ExpenseWriteState.COMMITTED_REFRESH_FAILED
    val isUnknown: Boolean get() = state == ExpenseWriteState.UNKNOWN

    companion object {
        fun <T> success(value: T) = ExpenseWriteResult(value = value)
        fun <T> failure(message: String) = ExpenseWriteResult<T>(errorMessage = message)
        fun <T> committedRefreshFailure(operationId: String, message: String, value: T? = null) =
            ExpenseWriteResult(
                value = value,
                errorMessage = message,
                state = ExpenseWriteState.COMMITTED_REFRESH_FAILED,
                operationId = operationId,
            )
        fun <T> unknown(message: String) = ExpenseWriteResult<T>(
            errorMessage = message,
            state = ExpenseWriteState.UNKNOWN,
        )
    }
}

class ExpenseOperationException(
    val userMessage: String,
    cause: Throwable? = null,
    override val failureKind: ReadFailureKind = ReadFailureKind.Other,
) : RuntimeException(userMessage, cause), StructuredReadFailure
