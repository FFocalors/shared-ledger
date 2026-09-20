package com.ffocalors.sharedledger.ui.expense

import com.ffocalors.sharedledger.data.expense.CreateExpenseInput
import com.ffocalors.sharedledger.data.expense.Expense
import com.ffocalors.sharedledger.data.expense.ExpenseDetail
import com.ffocalors.sharedledger.data.expense.ExpenseRepository
import com.ffocalors.sharedledger.data.expense.ExpenseSplitMethod
import com.ffocalors.sharedledger.data.expense.ExpenseMutationResult
import com.ffocalors.sharedledger.data.expense.ExpenseOperationException
import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.data.expense.ExpenseWriteState
import com.ffocalors.sharedledger.data.expense.ExpenseWriteResult
import com.ffocalors.sharedledger.data.expense.toExpenseWriteResult
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
import com.ffocalors.sharedledger.ui.screens.ExpenseSplitMethodUi
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
import java.io.IOException
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
        assertFalse(viewModel.detailState("expense-real").value.isLoading)
        assertFalse(viewModel.detailState("expense-real").value.isRefreshing)
        val uiState = viewModel.detailState("expense-real").value.detail!!.toUiState()
        assertEquals(listOf("Alice"), uiState.payments.map { it.participant })
        assertTrue(uiState.payments.none { it.isCurrentUser })
        assertEquals(ExpenseSplitMethodUi.Manual, uiState.splitMethod)
        assertTrue(uiState.splits.all { it.settlement.name == "Paid" })
        assertTrue(uiState.attachments.isEmpty())

        viewModel.loadDetail("expense-real")
        advanceUntilIdle()
        assertFalse(viewModel.detailState("expense-real").value.isLoading)
        assertFalse(viewModel.detailState("expense-real").value.isRefreshing)
    }

    @Test
    fun permissionFailureRemovesCachedExpenseDetail() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.loadDetail("expense-real")
        advanceUntilIdle()
        assertTrue(viewModel.detailState("expense-real").value.detail != null)

        repository.detailResult = Result.failure(
            ExpenseOperationException(
                "无权访问账单",
                failureKind = ReadFailureKind.PermissionDenied,
            ),
        )
        viewModel.loadDetail("expense-real", force = true)
        advanceUntilIdle()

        assertNull(viewModel.detailState("expense-real").value.detail)
        assertEquals(ReadFailureKind.PermissionDenied, viewModel.detailState("expense-real").value.failureKind)
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
                    fxRate = BigDecimal("1.234"),
                ),
            )
        }

        val uiState = detail.toUiState()

        assertEquals("12.34", uiState.amount)
        assertEquals("USD", uiState.currencyCode)
        assertEquals("10.00", uiState.originalAmount)
        assertEquals("EUR", uiState.originalCurrencyCode)
        assertEquals("12.340", uiState.payments.single().amount)
        assertEquals("6.170", uiState.splits.first().owedAmount)
    }

    @Test
    fun detailIdentityUsesClaimedParticipantInsteadOfPayer() = runTest(dispatcher) {
        val repository = FakeExpenseRepository()
        val source = repository.getDetail("expense-real").getOrThrow()
        val detail = source.copy(
            expense = source.expense.copy(
                title = "晚餐",
                originalAmount = BigDecimal("156.2"),
                baseAmount = BigDecimal("156.2"),
                splitMethod = ExpenseSplitMethod.Aa,
            ),
            payments = listOf(Payment("payment-whr", "expense-real", "whr", BigDecimal("156.2"), BigDecimal("156.2"))),
            splits = listOf(
                Split("split-whr", "expense-real", "whr", BigDecimal("52.0667"), BigDecimal("52.1")),
                Split("split-zhy", "expense-real", "zhy", BigDecimal("52.0667"), BigDecimal("52.1")),
                Split("split-hzl", "expense-real", "hzl", BigDecimal("52.0666"), BigDecimal("52.0")),
            ),
            participants = listOf(
                com.ffocalors.sharedledger.data.expense.ExpenseParticipant("whr", "activity-real", "whr", 0),
                com.ffocalors.sharedledger.data.expense.ExpenseParticipant("zhy", "activity-real", "zhy", 1),
                com.ffocalors.sharedledger.data.expense.ExpenseParticipant("hzl", "activity-real", "hzl", 2),
            ),
        )

        val uiState = detail.toUiState(currentParticipantId = "zhy")
        val splits = uiState.splits.associateBy { it.participant }

        assertEquals(ExpenseSplitMethodUi.Aa, uiState.splitMethod)
        assertEquals(listOf("whr"), uiState.payments.map { it.participant })
        assertFalse(uiState.payments.single().isCurrentUser)
        assertTrue(splits.getValue("whr").isPayer)
        assertFalse(splits.getValue("whr").isCurrentUser)
        assertFalse(splits.getValue("zhy").isPayer)
        assertTrue(splits.getValue("zhy").isCurrentUser)
        assertEquals("52.1", splits.getValue("whr").owedAmount)
        assertEquals("52.1", splits.getValue("zhy").owedAmount)
        assertEquals("52.0", splits.getValue("hzl").owedAmount)
    }

    @Test
    fun detailMapperKeepsEachPayerAndAmountSeparate() = runTest(dispatcher) {
        val repository = FakeExpenseRepository()
        val source = repository.getDetail("expense-real").getOrThrow()
        val detail = source.copy(
            payments = listOf(
                Payment("payment-a", "expense-real", "participant-a", BigDecimal("4"), BigDecimal("4.0")),
                Payment("payment-b", "expense-real", "participant-b", BigDecimal("6"), BigDecimal("6.0")),
            ),
        )

        val uiState = detail.toUiState(currentParticipantId = "participant-b")

        assertEquals(listOf("Alice", "Bob"), uiState.payments.map { it.participant })
        assertEquals(listOf("4.0", "6.0"), uiState.payments.map { it.amount })
        assertEquals(listOf(false, true), uiState.payments.map { it.isCurrentUser })
        assertTrue(uiState.splits.all { it.isPayer })
        assertEquals(ExpenseSplitMethodUi.Manual, uiState.splitMethod)
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
    fun activityAndLedgerListsKeepDeletedExpenseVisibleWithoutCountingItInTotals() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val original = repository.listExpenses.single()
        repository.listExpenses = listOf(
            original.copy(id = "expense-active", baseAmount = BigDecimal("10")),
            original.copy(
                id = "expense-deleted",
                baseAmount = BigDecimal("7"),
                occurredAt = "2026-09-04T12:00:00Z",
                isDeleted = true,
            ),
        )
        val shares = FakeParticipantExpenseShareRepository(
            ParticipantExpenseShareSnapshot(
                isBound = true,
                activityTotalBaseAmount = BigDecimal("10"),
                ledgerUnitTotals = mapOf("ledger-real" to BigDecimal("10")),
                expenseTotals = mapOf(
                    "expense-active" to BigDecimal("10"),
                    "expense-deleted" to BigDecimal("7"),
                ),
            ),
        )
        val viewModel = ExpenseViewModel(repository, "user-1", shares)

        viewModel.loadByActivity("activity-real")
        viewModel.loadByLedgerUnit("activity-real", "ledger-real")
        advanceUntilIdle()

        assertEquals(listOf(true), repository.activityIncludeDeleted)
        assertEquals(listOf(true), repository.ledgerIncludeDeleted)
        val activityState = viewModel.listState("activity:activity-real").value
        val ledgerState = viewModel.listState("ledger:ledger-real").value
        assertEquals(listOf("expense-active", "expense-deleted"), activityState.expenses.map { it.expenseId })
        assertEquals(2, ledgerState.expenses.size)
        assertEquals(BigDecimal("7"), activityState.expenses.single { it.isDeleted }.amount)
        assertEquals(BigDecimal("10"), activityState.totalBaseAmount)
        assertEquals(BigDecimal("10"), activityState.ledgerUnitTotals["ledger-real"])
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
    fun shareAggregatorKeepsDeletedExpenseAmountForCardButExcludesItFromSummaries() {
        val result = ParticipantExpenseShareAggregator.aggregate(
            participantId = "participant-a",
            expenses = listOf(
                ParticipantExpenseFact("expense-active", "ledger", isDeleted = false),
                ParticipantExpenseFact("expense-deleted", "ledger", isDeleted = true),
            ),
            splits = listOf(
                ParticipantSplitFact("expense-active", "participant-a", BigDecimal("80")),
                ParticipantSplitFact("expense-deleted", "participant-a", BigDecimal("35")),
            ),
        )

        assertEquals(BigDecimal("80"), result.activityTotalBaseAmount)
        assertEquals(BigDecimal("80"), result.ledgerUnitTotals["ledger"])
        assertEquals(BigDecimal("35"), result.expenseTotals["expense-deleted"])
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
    fun unknownCreateBlocksBlindResubmission() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<Result<ExpenseMutationResult>>()
        val repository = FakeExpenseRepository().apply { createGate = gate }
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))
        val draft = validDraft()

        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", draft)
        advanceUntilIdle()
        gate.complete(Result.failure(ExpenseOperationException("network", IOException("timeout"))))
        advanceUntilIdle()

        assertTrue(viewModel.form.value.submissionBlocked)
        assertEquals(ExpenseWriteState.UNKNOWN, viewModel.form.value.writeState)
        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", draft)
        advanceUntilIdle()
        assertEquals(1, repository.createCalls.get())
    }

    @Test
    fun unknownWriteConfirmationCallbackRunsOnlyAfterAuthoritativeRead() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<Result<ExpenseMutationResult>>()
        val repository = FakeExpenseRepository().apply { createGate = gate }
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", validDraft())
        advanceUntilIdle()
        gate.complete(Result.failure(ExpenseOperationException("network", IOException("timeout"))))
        advanceUntilIdle()

        var confirmed = 0
        viewModel.recoverFromUnknownWrite("activity-real", "ledger-real") { confirmed++ }
        advanceUntilIdle()

        assertEquals(1, confirmed)
        assertFalse(viewModel.form.value.submissionBlocked)
        assertNull(viewModel.form.value.errorMessage)
    }

    @Test
    fun committedCreateKeepsReturnedIdAndContinuesSuccessFlow() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository().apply {
            createWriteResult = ExpenseWriteResult.committedRefreshFailure(
                operationId = "expense-committed",
                message = "账单已保存，但最新详情暂时无法刷新，请稍后刷新确认",
                value = ExpenseMutationResult("expense-committed", BigDecimal.TEN, 2),
            )
        }
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))
        var successId: String? = null

        viewModel.submit(ExpenseFormMode.Create, null, "activity-real", validDraft()) { successId = it }
        advanceUntilIdle()

        assertEquals("expense-committed", successId)
        assertEquals(false, viewModel.form.value.isSubmitting)
        assertEquals(false, viewModel.form.value.submissionBlocked)
        assertEquals(ExpenseWriteState.COMMITTED_REFRESH_FAILED, viewModel.form.value.writeState)
        assertEquals("账单已保存，但最新详情暂时无法刷新，请稍后刷新确认", viewModel.form.value.errorMessage)
    }

    @Test
    fun updateDeleteAndRefundUseRepositoryOperations() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(ExpenseFormMode.Edit, "expense-real", "activity-real", validDraft())
        advanceUntilIdle()
        viewModel.delete("expense-real")
        advanceUntilIdle()
        viewModel.submit(ExpenseFormMode.Refund, "expense-real", "activity-real", validDraft().copy(originalExpenseId = "expense-real"))
        advanceUntilIdle()

        assertEquals(1, repository.updateCalls.get())
        assertEquals(1, repository.deleteCalls.get())
        assertEquals(1, repository.refundCalls.get())
        assertEquals("expense-real", repository.lastRefund?.originalExpenseId)
    }

    @Test
    fun committedDeleteKeepsAuthoritativeDeletedStateWhenDetailRefreshFails() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", dynamicShareRepository(repository))

        viewModel.loadDetail("expense-real")
        advanceUntilIdle()
        repository.listExpenses = repository.listExpenses.map { it.copy(isDeleted = true) }
        repository.detailResult = Result.failure(ExpenseOperationException("网络暂时不可用", IOException("timeout")))
        repository.deleteWriteResult = ExpenseWriteResult.committedRefreshFailure(
            operationId = "expense-real",
            message = "账单已作废，但最新状态暂时无法确认，请稍后刷新确认，勿重复提交",
            value = ExpenseMutationResult("expense-real", null, 2, true),
        )

        viewModel.delete("expense-real")
        advanceUntilIdle()

        assertFalse(viewModel.form.value.isSubmitting)
        assertFalse(viewModel.form.value.submissionBlocked)
        assertEquals(ExpenseWriteState.COMMITTED_REFRESH_FAILED, viewModel.form.value.writeState)
        assertEquals(true, viewModel.detailState("expense-real").value.detail?.expense?.isDeleted)
        assertEquals("账单已作废，但最新状态暂时无法确认，请稍后刷新确认，勿重复提交", viewModel.detailState("expense-real").value.actionMessage)
    }

    @Test
    fun unknownDeleteBlocksBlindRetry() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository().apply {
            deleteWriteResult = ExpenseWriteResult.unknown("账单写入结果未知，请先刷新账单确认，勿重复提交")
        }
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.delete("expense-real")
        advanceUntilIdle()
        viewModel.delete("expense-real")
        advanceUntilIdle()

        assertEquals(1, repository.deleteCalls.get())
        assertTrue(viewModel.form.value.submissionBlocked)
        assertEquals(ExpenseWriteState.UNKNOWN, viewModel.form.value.writeState)
    }

    @Test
    fun independentRefundDoesNotRequireOriginalExpense() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeExpenseRepository()
        val viewModel = ExpenseViewModel(repository, "user-1", fakeShareRepository(repository))

        viewModel.submit(
            ExpenseFormMode.Refund,
            null,
            "activity-real",
            validDraft().copy(originalExpenseId = null),
        )
        advanceUntilIdle()

        assertEquals(1, repository.refundCalls.get())
        assertEquals(null, repository.lastRefund?.originalExpenseId)
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

    private fun dynamicShareRepository(repository: FakeExpenseRepository) =
        object : ParticipantExpenseShareRepository {
            private fun snapshot() = ParticipantExpenseShareAggregator.aggregate(
                participantId = "participant-a",
                expenses = repository.listExpenses.map {
                    ParticipantExpenseFact(it.id, it.ledgerUnitId, it.isDeleted)
                },
                splits = repository.listExpenses.map {
                    ParticipantSplitFact(it.id, "participant-a", it.baseAmount)
                },
            )

            override suspend fun getForActivity(activityId: String, currentUserId: String) =
                Result.success(snapshot())

            override suspend fun getForLedgerUnit(
                activityId: String,
                ledgerUnitId: String,
                currentUserId: String,
            ) = Result.success(snapshot())
        }
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
    val refundCalls = AtomicInteger()
    var createGate: CompletableDeferred<Result<ExpenseMutationResult>>? = null
    var lastCreate: CreateExpenseInput? = null
    var lastUpdate: UpdateExpenseInput? = null
    var lastRefund: RefundExpenseInput? = null
    var createWriteResult: ExpenseWriteResult<ExpenseMutationResult>? = null
    var deleteWriteResult: ExpenseWriteResult<ExpenseMutationResult>? = null
    var detailResult: Result<ExpenseDetail>? = null
    var listExpenses: List<Expense> = listOf(expense)
    val activityIncludeDeleted = mutableListOf<Boolean>()
    val ledgerIncludeDeleted = mutableListOf<Boolean>()

    override suspend fun listByActivity(activityId: String, includeDeleted: Boolean): Result<List<Expense>> {
        activityIncludeDeleted += includeDeleted
        return Result.success(if (includeDeleted) listExpenses else listExpenses.filterNot { it.isDeleted })
    }
    override suspend fun listByLedgerUnit(ledgerUnitId: String, includeDeleted: Boolean): Result<List<Expense>> {
        ledgerIncludeDeleted += includeDeleted
        return Result.success(if (includeDeleted) listExpenses else listExpenses.filterNot { it.isDeleted })
    }
    override suspend fun getDetail(expenseId: String) = detailResult ?: Result.success(
        detail.copy(expense = listExpenses.firstOrNull { it.id == expenseId } ?: detail.expense),
    )
    override suspend fun create(input: CreateExpenseInput): Result<ExpenseMutationResult> {
        createCalls.incrementAndGet()
        lastCreate = input
        return createGate?.await() ?: Result.success(ExpenseMutationResult("expense-new", BigDecimal.TEN, 1))
    }
    override suspend fun createWrite(input: CreateExpenseInput): ExpenseWriteResult<ExpenseMutationResult> {
        createCalls.incrementAndGet()
        lastCreate = input
        return createWriteResult
            ?: (createGate?.await() ?: Result.success(ExpenseMutationResult("expense-new", BigDecimal.TEN, 1)))
                .toExpenseWriteResult()
    }
    override suspend fun update(input: UpdateExpenseInput): Result<ExpenseMutationResult> {
        updateCalls.incrementAndGet()
        lastUpdate = input
        return Result.success(ExpenseMutationResult(input.expenseId, BigDecimal.TEN, 2))
    }
    override suspend fun delete(expenseId: String): Result<ExpenseMutationResult> {
        deleteCalls.incrementAndGet()
        listExpenses = listExpenses.map { if (it.id == expenseId) it.copy(isDeleted = true) else it }
        return Result.success(ExpenseMutationResult(expenseId, null, 3, true))
    }
    override suspend fun deleteWrite(expenseId: String): ExpenseWriteResult<ExpenseMutationResult> {
        deleteWriteResult?.let {
            deleteCalls.incrementAndGet()
            return it
        }
        return delete(expenseId).toExpenseWriteResult()
    }
    override suspend fun refund(input: RefundExpenseInput): Result<ExpenseMutationResult> {
        refundCalls.incrementAndGet()
        lastRefund = input
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
