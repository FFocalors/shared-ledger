package com.ffocalors.sharedledger.data.expense

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

interface ExpenseRepository {
    suspend fun listByActivity(activityId: String, includeDeleted: Boolean = true): Result<List<Expense>>
    suspend fun listByLedgerUnit(ledgerUnitId: String, includeDeleted: Boolean = true): Result<List<Expense>>
    suspend fun getDetail(expenseId: String): Result<ExpenseDetail>
    suspend fun create(input: CreateExpenseInput): Result<ExpenseMutationResult>
    suspend fun update(input: UpdateExpenseInput): Result<ExpenseMutationResult>
    suspend fun delete(expenseId: String): Result<ExpenseMutationResult>
    suspend fun restore(expenseId: String): Result<ExpenseMutationResult>
    suspend fun refund(input: RefundExpenseInput, originalExpenseId: String): Result<ExpenseMutationResult>
}

class SupabaseExpenseRepository(private val client: SupabaseClient) : ExpenseRepository {
    override suspend fun listByActivity(activityId: String, includeDeleted: Boolean): Result<List<Expense>> = runCatching {
        val units = client.from("ledger_units").select {
            filter {
                eq("activity_id", activityId)
                eq("is_deleted", false)
            }
        }.decodeList<ExpenseLedgerUnitRowDto>()
        units.flatMap { loadRowsForLedgerUnit(it.id, includeDeleted) }
            .map { ExpenseDtoMappers.expense(it) }
            .distinctBy(Expense::id)
            .sortedWith(compareByDescending<Expense> { it.occurredAt }.thenByDescending { it.id })
    }.mapFailure()

    override suspend fun listByLedgerUnit(ledgerUnitId: String, includeDeleted: Boolean): Result<List<Expense>> = runCatching {
        loadRowsForLedgerUnit(ledgerUnitId, includeDeleted)
            .map { ExpenseDtoMappers.expense(it) }
            .sortedWith(compareByDescending<Expense> { it.occurredAt }.thenByDescending { it.id })
    }.mapFailure()

    override suspend fun getDetail(expenseId: String): Result<ExpenseDetail> = runCatching {
        val expense = client.from("expenses").select {
            filter { eq("id", expenseId) }
        }.decodeSingle<ExpenseRowDto>().let { ExpenseDtoMappers.expense(it) }
        val ledgerUnit = client.from("ledger_units").select {
            filter { eq("id", expense.ledgerUnitId) }
        }.decodeSingle<ExpenseLedgerUnitRowDto>().let { ExpenseDtoMappers.ledgerUnit(it) }
        val baseCurrency = client.from("activities").select {
            filter { eq("id", ledgerUnit.activityId) }
        }.decodeSingle<ExpenseActivityCurrencyRowDto>().let { ExpenseDtoMappers.baseCurrency(it) }
        val payments = client.from("payments").select {
            filter { eq("expense_id", expenseId) }
        }.decodeList<PaymentRowDto>().map { ExpenseDtoMappers.payment(it) }
        val splits = client.from("splits").select {
            filter { eq("expense_id", expenseId) }
        }.decodeList<SplitRowDto>().map { ExpenseDtoMappers.split(it) }
        val debtRows = client.from("expense_debts").select {
            filter { eq("expense_id", expenseId) }
        }.decodeList<ExpenseDebtRowDto>()
        val debtIds = debtRows.map { it.id }
        val allocations = if (debtIds.isEmpty()) emptyList() else client.from("transfer_allocations").select {
            filter { isIn("expense_debt_id", debtIds) }
        }.decodeList<TransferAllocationRowDto>()
        val usages = if (debtIds.isEmpty()) emptyList() else client.from("prepayment_usages").select {
            filter { isIn("expense_debt_id", debtIds) }
        }.decodeList<PrepaymentUsageRowDto>()
        val participantIds = (payments.map(Payment::participantId) + splits.map(Split::participantId)).distinct()
        val participants = if (participantIds.isEmpty()) {
            emptyList()
        } else {
            client.from("participants").select {
                filter { isIn("id", participantIds) }
            }.decodeList<ExpenseParticipantRowDto>().filterNot { it.isDeleted }.map { ExpenseDtoMappers.participant(it) }
        }
        ExpenseDetail(
            expense = expense,
            ledgerUnit = ledgerUnit,
            baseCurrency = baseCurrency,
            payments = payments,
            splits = splits,
            participants = participants.sortedBy { it.order },
            debtSettlements = ExpenseDtoMappers.debtSettlements(debtRows, allocations, usages),
        )
    }.mapFailure()

    override suspend fun create(input: CreateExpenseInput): Result<ExpenseMutationResult> = runCatching {
        val result = client.postgrest.rpc("create_expense", ExpenseRpcPayloadBuilder.create(input))
            .decodeSingle<CreateExpenseRpcDto>()
        ExpenseMutationResult(result.expenseId, ExpenseDtoMappers.decimalOrNull(result.baseAmount), result.version)
    }.mapFailure()

    override suspend fun update(input: UpdateExpenseInput): Result<ExpenseMutationResult> = runCatching {
        val result = client.postgrest.rpc("update_expense", ExpenseRpcPayloadBuilder.update(input))
            .decodeSingle<UpdateExpenseRpcDto>()
        ExpenseMutationResult(result.updatedExpenseId, ExpenseDtoMappers.decimalOrNull(result.baseAmount), result.version)
    }.mapFailure()

    override suspend fun delete(expenseId: String): Result<ExpenseMutationResult> = runCatching {
        val result = client.postgrest.rpc("delete_expense", buildJsonObject { put("expense_id", expenseId) })
            .decodeSingle<DeleteExpenseRpcDto>()
        ExpenseMutationResult(result.deletedExpenseId, null, result.version, result.deleted)
    }.mapFailure()

    override suspend fun restore(expenseId: String): Result<ExpenseMutationResult> = runCatching {
        val result = client.postgrest.rpc("restore_expense", buildJsonObject { put("expense_id", expenseId) })
            .decodeSingle<RestoreExpenseRpcDto>()
        ExpenseMutationResult(result.restoredExpenseId, null, result.version, result.restored)
    }.mapFailure()

    override suspend fun refund(input: RefundExpenseInput, originalExpenseId: String): Result<ExpenseMutationResult> =
        create(input.toCreateInput(originalExpenseId))

    private suspend fun loadRowsForLedgerUnit(ledgerUnitId: String, includeDeleted: Boolean): List<ExpenseRowDto> =
        client.from("expenses").select {
            filter {
                eq("ledger_unit_id", ledgerUnitId)
                if (!includeDeleted) eq("is_deleted", false)
            }
        }.decodeList()

    private fun <T> Result<T>.mapFailure(): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = { Result.failure(ExpenseOperationException(ExpenseErrorMapper.toUserMessage(it), it)) },
    )
}

object ExpenseRepositoryFactory {
    fun create(): ExpenseRepository = SupabaseClientProvider.createOrNull()?.let(::SupabaseExpenseRepository)
        ?: UnavailableExpenseRepository()
}

class UnavailableExpenseRepository(
    private val message: String = "尚未配置 Supabase，无法加载账单数据",
) : ExpenseRepository {
    private fun <T> unavailable(): Result<T> = Result.failure(ExpenseOperationException(message))
    override suspend fun listByActivity(activityId: String, includeDeleted: Boolean) = unavailable<List<Expense>>()
    override suspend fun listByLedgerUnit(ledgerUnitId: String, includeDeleted: Boolean) = unavailable<List<Expense>>()
    override suspend fun getDetail(expenseId: String) = unavailable<ExpenseDetail>()
    override suspend fun create(input: CreateExpenseInput) = unavailable<ExpenseMutationResult>()
    override suspend fun update(input: UpdateExpenseInput) = unavailable<ExpenseMutationResult>()
    override suspend fun delete(expenseId: String) = unavailable<ExpenseMutationResult>()
    override suspend fun restore(expenseId: String) = unavailable<ExpenseMutationResult>()
    override suspend fun refund(input: RefundExpenseInput, originalExpenseId: String) = unavailable<ExpenseMutationResult>()
}
