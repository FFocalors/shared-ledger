package com.ffocalors.sharedledger.data.expense

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal

internal object ExpenseDtoMappers {
    fun expense(dto: ExpenseRowDto) = Expense(
        id = dto.id,
        ledgerUnitId = dto.ledgerUnitId,
        title = dto.title,
        originalAmount = dto.originalAmount.decimalRequired("original_amount"),
        originalCurrency = dto.originalCurrency.trim(),
        fxRate = dto.fxRate.decimalRequired("fx_rate"),
        baseAmount = dto.baseAmount.decimalRequired("base_amount"),
        splitMethod = ExpenseSplitMethod.entries.firstOrNull { it.backendValue == dto.splitMethod }
            ?: error("unsupported expense split method"),
        occurredAt = dto.occurredAt,
        note = dto.note,
        originalExpenseId = dto.originalExpenseId,
        createdBy = dto.createdBy,
        updatedBy = dto.updatedBy,
        createdAt = dto.createdAt,
        updatedAt = dto.updatedAt,
        version = dto.version,
        isDeleted = dto.isDeleted,
        fxRateSource = dto.fxRateSource,
        fxRateObservedAt = dto.fxRateObservedAt,
    )

    fun payment(dto: PaymentRowDto) = Payment(dto.id, dto.expenseId, dto.participantId,
        dto.amount.decimalRequired("payment.amount"), decimalOrNull(dto.baseAmount))

    fun split(dto: SplitRowDto) = Split(dto.id, dto.expenseId, dto.participantId,
        dto.amount.decimalRequired("split.amount"), decimalOrNull(dto.baseAmount))

    fun ledgerUnit(dto: ExpenseLedgerUnitRowDto) = ExpenseLedgerUnit(dto.id, dto.activityId, dto.name, dto.type)

    fun baseCurrency(dto: ExpenseActivityCurrencyRowDto) = dto.baseCurrency.trim().uppercase()

    fun participant(dto: ExpenseParticipantRowDto) = ExpenseParticipant(dto.id, dto.activityId, dto.name, dto.participantOrder)

    fun debtSettlements(
        debts: List<ExpenseDebtRowDto>,
        allocations: List<TransferAllocationRowDto>,
        usages: List<PrepaymentUsageRowDto>,
    ): List<ExpenseDebtSettlement> {
        val allocatedByDebt = allocations.groupingBy { it.expenseDebtId }
            .fold(BigDecimal.ZERO) { total, row -> total + row.amount.decimalRequired("transfer_allocations.amount") }
        val usedByDebt = usages.groupingBy { it.expenseDebtId }
            .fold(BigDecimal.ZERO) { total, row -> total + row.amount.decimalRequired("prepayment_usages.amount") }
        return debts.map { debt ->
            ExpenseDebtSettlement(
                debtId = debt.id,
                debtorParticipantId = debt.debtorParticipantId,
                amount = debt.amount.decimalRequired("expense_debts.amount"),
                settledAmount = (allocatedByDebt[debt.id] ?: BigDecimal.ZERO) + (usedByDebt[debt.id] ?: BigDecimal.ZERO),
            )
        }
    }

    fun decimalOrNull(value: JsonElement?): BigDecimal? = when (value) {
        null, JsonNull -> null
        is JsonPrimitive -> value.content.toBigDecimalOrNull()
        else -> null
    }

    private fun JsonElement.decimalRequired(field: String): BigDecimal =
        ExpenseDtoMappers.decimalOrNull(this) ?: error("$field must be a decimal value")

}
