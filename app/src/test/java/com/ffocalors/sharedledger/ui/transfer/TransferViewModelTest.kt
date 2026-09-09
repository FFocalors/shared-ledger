package com.ffocalors.sharedledger.ui.transfer

import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementContext
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.data.transfer.SettlementParticipant
import com.ffocalors.sharedledger.data.transfer.SettlementTransferResult
import com.ffocalors.sharedledger.data.transfer.TransferRepository
import com.ffocalors.sharedledger.data.transfer.TransferOperationException
import com.ffocalors.sharedledger.data.transfer.TransferWriteState
import com.ffocalors.sharedledger.ui.screens.TransferDraft
import com.ffocalors.sharedledger.ui.screens.TransferMode
import java.math.BigDecimal
import java.io.IOException
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
    fun contextIsCachedForActivityAndDirection() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeTransferRepository()
        val viewModel = TransferViewModel(repository)

        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()

        assertEquals(1, repository.loadContextCalls)
        assertEquals(false, viewModel.uiState.value.isRefreshing)
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

    @Test
    fun unknownWriteBlocksBlindResubmissionUntilContextIsReloaded() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<Result<SettlementTransferResult>>()
        val repository = FakeTransferRepository().apply { createGate = gate }
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()
        val draft = TransferDraft("activity-1", null, TransferMode.TRANSFER, "creditor", "10.0")

        viewModel.submit(draft)
        advanceUntilIdle()
        gate.complete(Result.failure(TransferOperationException("network", IOException("timeout"))))
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.submissionBlocked)
        assertEquals(TransferWriteState.UNKNOWN, viewModel.uiState.value.writeState)
        viewModel.submit(draft)
        advanceUntilIdle()
        assertEquals(1, repository.createCalls.get())
    }

    @Test
    fun unboundCreatorUsesCandidateEndpointWhenActingOnBehalf() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = UnboundCreatorTransferRepository()
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()

        viewModel.submit(
            TransferDraft(
                activityId = "activity-1",
                ledgerUnitId = null,
                mode = TransferMode.TRANSFER,
                participantId = "creditor",
                amount = "10.0",
                onBehalfOfParticipantId = "debtor",
            ),
        )
        advanceUntilIdle()

        assertEquals("debtor", repository.lastInput?.currentParticipantId)
        assertEquals("debtor", repository.lastInput?.onBehalfOfParticipantId)
        assertEquals(1, repository.createCalls.get())
    }

    @Test
    fun unboundCreatorReceiveUsesDebtorToCreditorEndpoints() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = UnboundCreatorTransferRepository()
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.RECEIVE)
        advanceUntilIdle()

        viewModel.submit(
            TransferDraft(
                activityId = "activity-1",
                ledgerUnitId = null,
                mode = TransferMode.RECEIVE,
                participantId = "debtor",
                amount = "10.0",
                onBehalfOfParticipantId = "debtor",
            ),
        )
        advanceUntilIdle()

        assertEquals("creditor", repository.lastInput?.currentParticipantId)
        assertEquals("debtor", repository.lastInput?.selectedParticipantId)
        assertEquals(SettlementDirection.RECEIVE, repository.lastInput?.direction)
    }

    @Test
    fun duplicateParticipantCandidatesUseStableDebtKey() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = DuplicateCandidateTransferRepository()
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()

        viewModel.submit(
            TransferDraft(
                activityId = "activity-1",
                ledgerUnitId = null,
                mode = TransferMode.TRANSFER,
                participantId = "creditor",
                amount = "20.0",
                onBehalfOfParticipantId = "debtor-b",
                candidateKey = "debtor-b->creditor",
            ),
        )
        advanceUntilIdle()

        assertEquals(BigDecimal("20.0"), repository.lastInput?.amount)
        assertEquals("debtor-b", repository.lastInput?.currentParticipantId)
    }

    private class FakeTransferRepository : TransferRepository {
        val createCalls = AtomicInteger()
        var loadContextCalls = 0
        var createGate: CompletableDeferred<Result<SettlementTransferResult>>? = null
        override suspend fun loadContext(activityId: String, direction: SettlementDirection) = Result.success(
            SettlementContext(
                activityId = activityId,
                currentParticipantId = "debtor",
                currentParticipantName = "我",
                baseCurrency = "CNY",
                candidates = listOf(SettlementCandidate("creditor", "Alice", BigDecimal("30.0"))),
            ),
        ).also { loadContextCalls++ }

        override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> {
            createCalls.incrementAndGet()
            return createGate?.await() ?: Result.success(SettlementTransferResult("transfer-1", input.amount, "CNY", 2))
        }
    }

    private class UnboundCreatorTransferRepository : TransferRepository {
        val createCalls = AtomicInteger()
        var lastInput: CreateSettlementTransferInput? = null

        override suspend fun loadContext(activityId: String, direction: SettlementDirection) = Result.success(
            SettlementContext(
                activityId = activityId,
                currentParticipantId = null,
                currentParticipantName = null,
                baseCurrency = "CNY",
                canActOnBehalf = true,
                candidates = listOf(
                    SettlementCandidate(
                        participantId = if (direction == SettlementDirection.RECEIVE) "debtor" else "creditor",
                        participantName = if (direction == SettlementDirection.RECEIVE) "Debtor" else "Creditor",
                        amount = BigDecimal("30.0"),
                        fromParticipantId = "debtor",
                        toParticipantId = "creditor",
                        onBehalfOptions = listOf(SettlementParticipant("debtor", "Debtor")),
                    ),
                ),
            ),
        )

        override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> {
            createCalls.incrementAndGet()
            lastInput = input
            return Result.success(SettlementTransferResult("transfer-1", input.amount, "CNY", 2))
        }
    }

    private class DuplicateCandidateTransferRepository : TransferRepository {
        var lastInput: CreateSettlementTransferInput? = null

        override suspend fun loadContext(activityId: String, direction: SettlementDirection) = Result.success(
            SettlementContext(
                activityId = activityId,
                currentParticipantId = null,
                currentParticipantName = null,
                baseCurrency = "CNY",
                canActOnBehalf = true,
                candidates = listOf(
                    SettlementCandidate(
                        participantId = "creditor",
                        participantName = "Creditor",
                        amount = BigDecimal("10.0"),
                        fromParticipantId = "debtor-a",
                        toParticipantId = "creditor",
                        onBehalfOptions = listOf(SettlementParticipant("debtor-a", "Debtor A")),
                    ),
                    SettlementCandidate(
                        participantId = "creditor",
                        participantName = "Creditor",
                        amount = BigDecimal("20.0"),
                        fromParticipantId = "debtor-b",
                        toParticipantId = "creditor",
                        onBehalfOptions = listOf(SettlementParticipant("debtor-b", "Debtor B")),
                    ),
                ),
            ),
        )

        override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> {
            lastInput = input
            return Result.success(SettlementTransferResult("transfer-1", input.amount, "CNY", 2))
        }
    }
}
