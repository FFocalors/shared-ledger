package com.ffocalors.sharedledger.ui.transfer

import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementContext
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.data.transfer.SettlementTransferResult
import com.ffocalors.sharedledger.data.transfer.TransferRepository
import com.ffocalors.sharedledger.ui.screens.TransferDraft
import com.ffocalors.sharedledger.ui.screens.TransferMode
import java.math.BigDecimal
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TransferViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun submitRejectsAmountAboveCurrentDebt() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeTransferRepository()
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()

        viewModel.submit(TransferDraft("activity-1", null, TransferMode.TRANSFER, "creditor", "30.1"))

        assertEquals("金额不能超过当前债务 30.0", viewModel.uiState.value.errorMessage)
        assertEquals(0, repository.createCalls.get())
    }

    @Test
    fun duplicateSubmitIsIgnoredWhileRequestIsInFlight() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<Result<SettlementTransferResult>>()
        val repository = FakeTransferRepository().apply { createGate = gate }
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()
        val draft = TransferDraft("activity-1", null, TransferMode.TRANSFER, "creditor", "10.0")

        viewModel.submit(draft)
        viewModel.submit(draft)
        advanceUntilIdle()
        assertEquals(1, repository.createCalls.get())
        assertTrue(viewModel.uiState.value.isSubmitting)

        gate.complete(Result.success(SettlementTransferResult("transfer-1", BigDecimal("10.0"), "CNY", 2)))
        advanceUntilIdle()
        assertTrue(!viewModel.uiState.value.isSubmitting)
    }

    private class FakeTransferRepository : TransferRepository {
        val createCalls = AtomicInteger()
        var createGate: CompletableDeferred<Result<SettlementTransferResult>>? = null
        override suspend fun loadContext(activityId: String, direction: SettlementDirection) = Result.success(
            SettlementContext(
                activityId = activityId,
                currentParticipantId = "debtor",
                currentParticipantName = "我",
                baseCurrency = "CNY",
                candidates = listOf(SettlementCandidate("creditor", "Alice", BigDecimal("30.0"))),
            ),
        )

        override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> {
            createCalls.incrementAndGet()
            return createGate?.await() ?: Result.success(SettlementTransferResult("transfer-1", input.amount, "CNY", 2))
        }
    }
}
