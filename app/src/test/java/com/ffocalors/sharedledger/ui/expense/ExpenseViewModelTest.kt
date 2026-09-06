package com.ffocalors.sharedledger.ui.expense

import com.ffocalors.sharedledger.data.expense.CreateExpenseInput
import com.ffocalors.sharedledger.data.expense.Expense
import com.ffocalors.sharedledger.data.expense.ExpenseDetail
import com.ffocalors.sharedledger.data.expense.ExpenseRepository
import com.ffocalors.sharedledger.data.expense.ExpenseSplitMethod
import com.ffocalors.sharedledger.data.expense.ExpenseMutationResult
import com.ffocalors.sharedledger.data.expense.ManualSplitInput
import com.ffocalors.sharedledger.data.expense.Payment
import com.ffocalors.sharedledger.data.expense.PaymentInput
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepository
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseFact
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareAggregator
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareSnapshot
import com.ffocalors.sharedledger.data.expense.ParticipantSplitFact
import com.ffocalors.sharedledger.data.expense.RefundExpenseInput
import com.ffocalors.sharedledger.data.expense.Split
import com.ffocalors.sharedledger.data.expense.UpdateExpenseInput
import com.ffocalors.sharedledger.ui.screens.createDefaultExpenseDraft
import com.ffocalors.sharedledger.ui.screens.formatExpenseDetailAmount
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal
import java.util.concurrent.atomic.AtomicInteger

class ExpenseViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun listUsesRealExpenseUuidAndDetailMapperShowsFactsOnly() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.loadByActivity("activity-real")
        advanceUntilIdle()

        assertEquals("expense-real", viewModel.listState("activity:activity-real").value.expenses.single().expenseId)
        viewModel.loadDetail("expense-real")
        advanceUntilIdle()
        val uiState = viewModel.detailState("expense-real").value.detail!!.toUiState()
        assertEquals("Alice、Bob", uiState.payer)
        assertTrue(uiState.splits.all { it.settlement.name == "Pending" })
        assertTrue(uiState.attachments.isEmpty())
    }

    @Test
    fun detailMapperKeepsBaseAndOriginalCurrencyFactsSeparate() = runTest(dispatcher) {
        val repository = FakeExpenseRepository()
        val detail = repository.getDetail("expense-real").getOrThrow().let { current ->
            current.copy(
                baseCurrency = "USD",
                expense = current.expense.copy(
                    baseAmount = BigDecimal("12.34"),
                    originalAmount = BigDecimal("10.00"),
                    originalCurrency = "EUR",
                ),
            )
        }

        val uiState = detail.toUiState()

        assertEquals("12.34", uiState.amount)
        assertEquals("USD", uiState.currencyCode)
        assertEquals("10.00", uiState.originalAmount)
        assertEquals("EUR", uiState.originalCurrencyCode)
    }

    @Test
    fun expenseDetailAmountFormattingSupportsKnownAndFallbackCurrencies() {
        assertEquals("¥12.3", formatExpenseDetailAmount("12.34", "CNY"))
        assertEquals("$12.34", formatExpenseDetailAmount("12.34", "USD"))
        assertEquals("€12.34", formatExpenseDetailAmount("12.34", "EUR"))
        assertEquals("AUD 12.34", formatExpenseDetailAmount("12.34", "AUD"))
    }

    @Test
    fun listUsesCurrentUserSharesForEachExpenseAndLedgerTotalIncludingRefund() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val original = repository.listExpenses.single()
        repository.listExpenses = listOf(
            original.copy(id = "expense-paid", originalAmount = BigDecimal("300"), originalCurrency = "EUR", baseAmount = BigDecimal("300")),
            original.copy(id = "expense-refund", originalAmount = BigDecimal("-90"), originalCurrency = "USD", baseAmount = BigDecimal("-90")),
        )
        val shareRepository = FakeParticipantExpenseShareRepository(
            ParticipantExpenseShareSnapshot(
                isBound = true,
                activityTotalBaseAmount = BigDecimal("210.0"),
                ledgerUnitTotals = mapOf("ledger-real" to BigDecimal("210.0")),
                expenseTotals = mapOf(
                    "expense-paid" to BigDecimal("300.0"),
                    "expense-refund" to BigDecimal("-90.0"),
                ),
            ),
        )
        val viewModel = ExpenseViewModel(repository, "user-1", shareRepository)

        viewModel.loadByLedgerUnit("ledger-real")
        advanceUntilIdle()

        val state = viewModel.listState("ledger:ledger-real").value
        assertEquals(BigDecimal("210.0"), state.totalBaseAmount)
        assertEquals(BigDecimal("300.0"), state.expenses.first { it.expenseId == "expense-paid" }.amount)
        assertEquals(BigDecimal("-90.0"), state.expenses.first { it.expenseId == "expense-refund" }.amount)
        assertTrue(state.expenses.all { it.currencyCode == "CNY" })
        assertTrue(state.participantBound)
    }

    @Test
    fun shareAggregatorKeepsEachClaimedUsersLedgerAndExpenseAmountsSeparate() {
        val expenses = listOf(
            ParticipantExpenseFact("expense-one", "ledger-one"),
            ParticipantExpenseFact("expense-two", "ledger-two"),
        )
        val splits = listOf(
            ParticipantSplitFact("expense-one", "participant-a", BigDecimal("100.0")),
            ParticipantSplitFact("expense-one", "participant-b", BigDecimal("100.0")),
            ParticipantSplitFact("expense-one", "participant-c", BigDecimal("100.0")),
            ParticipantSplitFact("expense-two", "participant-a", BigDecimal("40.0")),
            ParticipantSplitFact("expense-two", "participant-b", BigDecimal("60.0")),
        )

        val participantA = ParticipantExpenseShareAggregator.aggregate("participant-a", expenses, splits)
        val participantB = ParticipantExpenseShareAggregator.aggregate("participant-b", expenses, splits)

        assertEquals(BigDecimal("140.0"), participantA.activityTotalBaseAmount)
        assertEquals(BigDecimal("100.0"), participantA.expenseTotals["expense-one"])
        assertEquals(BigDecimal("100.0"), participantA.ledgerUnitTotals["ledger-one"])
        assertEquals(BigDecimal("40.0"), participantA.ledgerUnitTotals["ledger-two"])
        assertEquals(BigDecimal("160.0"), participantB.activityTotalBaseAmount)
        assertEquals(BigDecimal("60.0"), participantB.expenseTotals["expense-two"])
    }

    @Test
    fun shareAggregatorReducesTotalWithNegativeRefundSplit() {
        val result = ParticipantExpenseShareAggregator.aggregate(
            participantId = "participant-a",
            expenses = listOf(
                ParticipantExpenseFact("expense", "ledger"),
                ParticipantExpenseFact("refund", "ledger"),
            ),
            splits = listOf(
                ParticipantSplitFact("expense", "participant-a", BigDecimal("300.0")),
                ParticipantSplitFact("refund", "participant-a", BigDecimal("-90.0")),
            ),
        )

        assertEquals(BigDecimal("210.0"), result.activityTotalBaseAmount)
        assertEquals(BigDecimal("-90.0"), result.expenseTotals["refund"])
        assertEquals(BigDecimal("210.0"), result.ledgerUnitTotals["ledger"])
    }

    @Test
    fun unboundShareHasNoFakeZeroAmount() {
        val result = ParticipantExpenseShareSnapshot.unbound()

        assertFalse(result.isBound)
        assertNull(result.activityTotalBaseAmount)
        assertTrue(result.expenseTotals.isEmpty())
    }

    @Test
    fun defaultDraftIsStableSafeAaInputForNonDivisibleParticipantCount() {
        val participants = listOf(
            ExpenseFormParticipant("a", "Alice"),
            ExpenseFormParticipant("b", "Bob"),
            ExpenseFormParticipant("c", "Carol"),
        )

        val draft = createDefaultExpenseDraft("ledger-real", participants, "CNY", "2026-09-05T12:00:00Z")

        assertEquals(ExpenseSplitMethod.Aa, draft.splitMethod)
        assertEquals(listOf("a", "b", "c"), draft.aaParticipantIds)
        assertTrue(draft.manualSplitAmounts.isEmpty())
        assertEquals("2026-09-05T12:00:00Z", draft.occurredAt)
    }

    @Test
    fun invalidInputDoesNotCallRepository() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", validDraft().copy(amount = "0"))
        advanceUntilIdle()

        assertEquals(0, repository.createCalls.get())
        assertEquals("金额必须大于 0", viewModel.form.value.errorMessage)
    }

    @Test
    fun zeroSelectedPayerAndZeroManualSplitAreRejected() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(
            ExpenseFormMode.Create,
            null,
            "activity-real",
            validDraft().copy(
                payerIds = listOf("participant-a", "participant-b"),
                payerAmounts = mapOf("participant-a" to "10", "participant-b" to "0"),
            ),
        )
        advanceUntilIdle()
        assertEquals("每位付款人的金额必须大于 0", viewModel.form.value.errorMessage)

        viewModel.submit(
            ExpenseFormMode.Create,
            null,
            "activity-real",
            validDraft().copy(manualSplitAmounts = mapOf("participant-a" to "0")),
        )
        advanceUntilIdle()
        assertEquals("至少填写一项大于 0 的手动分摊", viewModel.form.value.errorMessage)
        assertEquals(0, repository.createCalls.get())
    }

    @Test
    fun payloadOmitsZeroManualSplits() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(
            ExpenseFormMode.Create,
            null,
            "activity-real",
            validDraft().copy(
                manualSplitAmounts = mapOf("participant-a" to "10", "participant-b" to "0"),
            ),
        )
        advanceUntilIdle()

        assertEquals(listOf("participant-a"), repository.lastCreate?.manualSplits?.map { it.participantId })
    }

    @Test
    fun createPreventsDuplicateSubmissionAndSendsUuidInputs() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<Result<ExpenseMutationResult>>()
        val repository = FakeExpenseRepository().apply { createGate = gate }
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", validDraft())
        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", validDraft())
        advanceUntilIdle()
        assertEquals(1, repository.createCalls.get())
        assertTrue(viewModel.form.value.isSubmitting)
        assertEquals("participant-a", repository.lastCreate?.payments?.single()?.participantId)
        gate.complete(Result.success(ExpenseMutationResult("expense-new", BigDecimal.TEN, 1)))
        advanceUntilIdle()
        assertTrue(!viewModel.form.value.isSubmitting)
    }

    @Test
    fun updateDeleteRestoreAndRefundUseRepositoryOperations() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(ExpenseFormMode.Edit, "expense-real", "activity-real", validDraft())
        advanceUntilIdle()
        viewModel.delete("expense-real")
        advanceUntilIdle()
        viewModel.restore("expense-real")
        advanceUntilIdle()
        viewModel.submit(ExpenseFormMode.Refund, "expense-real", "activity-real", validDraft().copy(originalExpenseId = "expense-real"))
        advanceUntilIdle()

        assertEquals(1, repository.updateCalls.get())
        assertEquals(1, repository.deleteCalls.get())
        assertEquals(1, repository.restoreCalls.get())
        assertEquals(1, repository.refundCalls.get())
    }

    @Test
    fun editingRefundPreservesOriginalExpenseIdInUpdate() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))
        val refundDetail = repository.getDetail("expense-real").getOrThrow().let { detail ->
            detail.copy(expense = detail.expense.copy(originalExpenseId = "original-expense"))
        }
        val draft = refundDetail.toFormDraft(ExpenseFormMode.Edit)

        viewModel.submit(ExpenseFormMode.Edit, "expense-real", "activity-real", draft)
        advanceUntilIdle()

        assertEquals("original-expense", draft.originalExpenseId)
        assertEquals("original-expense", repository.lastUpdate?.originalExpenseId)
    }

    private fun validDraft() = ExpenseFormDraft(
        ledgerUnitId = "ledger-real",
        title = "晚餐",
        amount = "10",
        currency = "CNY",
        fxRate = "1",
        payerIds = listOf("participant-a"),
        payerAmounts = mapOf("participant-a" to "10"),
        splitMethod = ExpenseSplitMethod.Manual,
        manualSplitAmounts = mapOf("participant-a" to "10"),
        aaParticipantIds = emptyList(),
        occurredAt = "2026-09-05T12:00:00Z",
        note = "note",
    )

    private fun fakeShareRepository(repository: FakeExpenseRepository) =
        FakeParticipantExpenseShareRepository(
            ParticipantExpenseShareSnapshot(
                isBound = true,
                activityTotalBaseAmount = repository.listExpenses.fold(BigDecimal.ZERO) { total, expense -> total + expense.baseAmount },
                ledgerUnitTotals = mapOf("ledger-real" to repository.listExpenses.fold(BigDecimal.ZERO) { total, expense -> total + expense.baseAmount }),
                expenseTotals = repository.listExpenses.associate { it.id to it.baseAmount },
            ),
        )
}

private class FakeParticipantExpenseShareRepository(
    private val snapshot: ParticipantExpenseShareSnapshot,
) : ParticipantExpenseShareRepository {
    override suspend fun getForActivity(activityId: String, currentUserId: String) = Result.success(snapshot)

    override suspend fun getForLedgerUnit(
        activityId: String,
        ledgerUnitId: String,
        currentUserId: String,
    ) = Result.success(snapshot)
}

private class FakeExpenseRepository : ExpenseRepository {
    val createCalls = AtomicInteger()
    val updateCalls = AtomicInteger()
    val deleteCalls = AtomicInteger()
    val restoreCalls = AtomicInteger()
    val refundCalls = AtomicInteger()
    var createGate: CompletableDeferred<Result<ExpenseMutationResult>>? = null
    var lastCreate: CreateExpenseInput? = null
    var lastUpdate: UpdateExpenseInput? = null
    var listExpenses: List<Expense> = listOf(expense)

    override suspend fun listByActivity(activityId: String, includeDeleted: Boolean) = Result.success(listExpenses)
    override suspend fun listByLedgerUnit(ledgerUnitId: String, includeDeleted: Boolean) = Result.success(listExpenses)
    override suspend fun getDetail(expenseId: String) = Result.success(detail)
    override suspend fun create(input: CreateExpenseInput): Result<ExpenseMutationResult> {
        createCalls.incrementAndGet()
        lastCreate = input
        return createGate?.await() ?: Result.success(ExpenseMutationResult("expense-new", BigDecimal.TEN, 1))
    }
    override suspend fun update(input: UpdateExpenseInput): Result<ExpenseMutationResult> {
        updateCalls.incrementAndGet()
        lastUpdate = input
        return Result.success(ExpenseMutationResult(input.expenseId, BigDecimal.TEN, 2))
    }
    override suspend fun delete(expenseId: String): Result<ExpenseMutationResult> {
        deleteCalls.incrementAndGet()
        return Result.success(ExpenseMutationResult(expenseId, null, 3, true))
    }
    override suspend fun restore(expenseId: String): Result<ExpenseMutationResult> {
        restoreCalls.incrementAndGet()
        return Result.success(ExpenseMutationResult(expenseId, null, 4, false))
    }
    override suspend fun refund(input: RefundExpenseInput, originalExpenseId: String): Result<ExpenseMutationResult> {
        refundCalls.incrementAndGet()
        return Result.success(ExpenseMutationResult("refund-real", BigDecimal.TEN.negate(), 5))
    }

    companion object {
        private val expense = Expense(
            id = "expense-real", ledgerUnitId = "ledger-real", title = "晚餐",
            originalAmount = BigDecimal("10"), originalCurrency = "CNY", fxRate = BigDecimal.ONE,
            baseAmount = BigDecimal("10"), splitMethod = ExpenseSplitMethod.Manual,
            occurredAt = "2026-09-05T12:00:00Z", note = "note", originalExpenseId = null,
            createdBy = "user-1", updatedBy = "user-1", createdAt = null, updatedAt = null,
            version = 1, isDeleted = false,
        )
        private val detail = ExpenseDetail(
            expense = expense,
            ledgerUnit = com.ffocalors.sharedledger.data.expense.ExpenseLedgerUnit("ledger-real", "activity-real", "默认账本", "default"),
            baseCurrency = "CNY",
            payments = listOf(
                Payment("pay-a", "expense-real", "participant-a", BigDecimal("10"), null),
                Payment("pay-b", "expense-real", "participant-b", BigDecimal.ZERO, null),
            ),
            splits = listOf(
                Split("split-a", "expense-real", "participant-a", BigDecimal("5"), null),
                Split("split-b", "expense-real", "participant-b", BigDecimal("5"), null),
            ),
            participants = listOf(
                com.ffocalors.sharedledger.data.expense.ExpenseParticipant("participant-a", "activity-real", "Alice", 0),
                com.ffocalors.sharedledger.data.expense.ExpenseParticipant("participant-b", "activity-real", "Bob", 1),
            ),
        )
    }
}
