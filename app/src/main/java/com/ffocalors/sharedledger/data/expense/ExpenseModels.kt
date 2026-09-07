package com.ffocalors.sharedledger.data.expense

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
) {
    fun toCreateInput(originalExpenseId: String): CreateExpenseInput {
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
)

class ExpenseOperationException(
    val userMessage: String,
    cause: Throwable? = null,
) : RuntimeException(userMessage, cause)
