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
    val iconKey: String = ExpenseIconKey.MONEY,
    val financialLocked: Boolean = false,
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

/**
 * Server-calculated repayment progress for one directional Expense debt.
 * Amounts are kept in both the bill currency and the activity base currency;
 * callers must not recompute one from the other.
 */
data class ExpenseRepaymentProgress(
    val expenseId: String,
    val debtorParticipantId: String,
    val creditorParticipantId: String,
    val currency: String,
    val owedOriginalAmount: BigDecimal,
    val owedBaseAmount: BigDecimal,
    val reverseOffsetOriginalAmount: BigDecimal,
    val reverseOffsetBaseAmount: BigDecimal,
    val settledTransferOriginalAmount: BigDecimal,
    val settledTransferBaseAmount: BigDecimal,
    val prepaymentOriginalAmount: BigDecimal,
    val prepaymentBaseAmount: BigDecimal,
    val remainingOriginalAmount: BigDecimal,
    val remainingBaseAmount: BigDecimal,
    val financialVersion: Long? = null,
) {
    val settledOriginalAmount: BigDecimal
        get() = settledTransferOriginalAmount + prepaymentOriginalAmount

    val settledBaseAmount: BigDecimal
        get() = settledTransferBaseAmount + prepaymentBaseAmount
}

data class ExpenseDetail(
    val expense: Expense,
    val ledgerUnit: ExpenseLedgerUnit,
    val baseCurrency: String,
    val payments: List<Payment>,
    val splits: List<Split>,
    val participants: List<ExpenseParticipant>,
    val debtSettlements: List<ExpenseDebtSettlement> = emptyList(),
    /** Authoritative currency-aware projection; empty only for legacy fixtures. */
    val repaymentProgress: List<ExpenseRepaymentProgress> = emptyList(),
    val repaymentProgressAvailable: Boolean = false,
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
    val iconKey: String = ExpenseIconKey.MONEY,
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
    val iconKey: String = ExpenseIconKey.MONEY,
)

data class UpdateExpensePresentationInput(
    val expenseId: String,
    val title: String,
    val note: String? = null,
    val iconKey: String = ExpenseIconKey.MONEY,
    val expectedVersion: Long? = null,
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
    val iconKey: String = ExpenseIconKey.MONEY,
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
            iconKey = ExpenseIconKey.normalize(iconKey),
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
    val financialLocked: Boolean? = null,
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
