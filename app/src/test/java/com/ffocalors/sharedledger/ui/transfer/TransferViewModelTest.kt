package com.ffocalors.sharedledger.ui.transfer

import com.ffocalors.sharedledger.data.transfer.CreateSettlementTransferInput
import com.ffocalors.sharedledger.data.transfer.InMemoryTransferRequestStore
import com.ffocalors.sharedledger.data.transfer.SettlementCandidate
import com.ffocalors.sharedledger.data.transfer.SettlementCandidateKind
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
import org.junit.Assert.assertNotEquals
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
    fun activityMultiCurrencyFlagIsExposedToTransferUi() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeTransferRepository().apply { multiCurrencyEnabled = true }
        val viewModel = TransferViewModel(repository)

        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.multiCurrencyEnabled)
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
    fun unknownWriteCanSafelyRetryWithTheSameRequestId() = runTest(dispatcher) {
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

        assertTrue(!viewModel.uiState.value.submissionBlocked)
        assertEquals(TransferWriteState.UNKNOWN, viewModel.uiState.value.writeState)
        viewModel.submit(draft)
        advanceUntilIdle()
        assertEquals(2, repository.createCalls.get())
        assertEquals(repository.requestIds[0], repository.requestIds[1])
    }

    @Test
    fun unknownPayloadSurvivesViewModelRecreationAndClearsAfterSuccess() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val store = InMemoryTransferRequestStore()
        val firstGate = CompletableDeferred<Result<SettlementTransferResult>>()
        val firstRepository = FakeTransferRepository().apply { createGate = firstGate }
        val draft = TransferDraft("activity-1", null, TransferMode.TRANSFER, "creditor", "10.0")

        val firstViewModel = TransferViewModel(
            repository = firstRepository,
            currentUserId = "user-1",
            requestStore = store,
        )
        firstViewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()
        firstViewModel.submit(draft)
        advanceUntilIdle()
        firstGate.complete(Result.failure(TransferOperationException("network", IOException("timeout"))))
        advanceUntilIdle()

        val secondRepository = FakeTransferRepository()
        val secondViewModel = TransferViewModel(
            repository = secondRepository,
            currentUserId = "user-1",
            requestStore = store,
        )
        secondViewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()
        secondViewModel.submit(draft)
        advanceUntilIdle()

        assertEquals(firstRepository.inputs.single().requestId, secondRepository.inputs.single().requestId)
        assertEquals(firstRepository.inputs.single().occurredAt, secondRepository.inputs.single().occurredAt)
        assertTrue(store.read("user-1", "activity-1", SettlementDirection.TRANSFER).isEmpty())
    }

    @Test
    fun editingPayloadRotatesRequestIdAndKeepsOldUnknownRequest() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val store = InMemoryTransferRequestStore()
        val gate = CompletableDeferred<Result<SettlementTransferResult>>()
        val repository = FakeTransferRepository().apply { createGate = gate }
        val viewModel = TransferViewModel(
            repository = repository,
            currentUserId = "user-1",
            requestStore = store,
        )
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()
        viewModel.submit(TransferDraft("activity-1", null, TransferMode.TRANSFER, "creditor", "10.0"))
        advanceUntilIdle()
        gate.complete(Result.failure(TransferOperationException("network", IOException("timeout"))))
        advanceUntilIdle()
        val firstRequestId = repository.inputs.single().requestId

        viewModel.submit(TransferDraft("activity-1", null, TransferMode.TRANSFER, "creditor", "11.0"))
        advanceUntilIdle()

        assertNotEquals(firstRequestId, repository.inputs[1].requestId)
        assertEquals(2, store.read("user-1", "activity-1", SettlementDirection.TRANSFER).size)
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

        assertEquals("debtor", repository.lastInput?.fromParticipantId)
        assertEquals("creditor", repository.lastInput?.toParticipantId)
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

        assertEquals("debtor", repository.lastInput?.fromParticipantId)
        assertEquals("creditor", repository.lastInput?.toParticipantId)
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
                candidateKey = "ON_BEHALF:debtor-b->creditor",
            ),
        )
        advanceUntilIdle()

        assertEquals(BigDecimal("20.0"), repository.lastInput?.amount)
        assertEquals("debtor-b", repository.lastInput?.fromParticipantId)
        assertEquals("creditor", repository.lastInput?.toParticipantId)
    }

    @Test
    fun boundCreatorOnBehalfSubmissionPreservesHzlToWhrEndpoints() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = BoundCreatorTransferRepository()
        val viewModel = TransferViewModel(repository)
        viewModel.load("activity-1", SettlementDirection.TRANSFER)
        advanceUntilIdle()

        viewModel.submit(
            TransferDraft(
                activityId = "activity-1",
                ledgerUnitId = null,
                mode = TransferMode.TRANSFER,
                participantId = "whr",
                amount = "52.0",
                onBehalfOfParticipantId = "hzl",
                candidateKey = "ON_BEHALF:hzl->whr",
            ),
        )
        advanceUntilIdle()

        assertEquals("hzl", repository.lastInput?.fromParticipantId)
        assertEquals("whr", repository.lastInput?.toParticipantId)
        assertEquals("hzl", repository.lastInput?.onBehalfOfParticipantId)
    }

    private class FakeTransferRepository : TransferRepository {
        val createCalls = AtomicInteger()
        val requestIds = mutableListOf<String?>()
        val inputs = mutableListOf<CreateSettlementTransferInput>()
        var loadContextCalls = 0
        var multiCurrencyEnabled = false
        var createGate: CompletableDeferred<Result<SettlementTransferResult>>? = null
        override suspend fun loadContext(activityId: String, direction: SettlementDirection) = Result.success(
            SettlementContext(
                activityId = activityId,
                currentParticipantId = "debtor",
                currentParticipantName = "我",
                baseCurrency = "CNY",
                multiCurrencyEnabled = multiCurrencyEnabled,
                candidates = listOf(
                    SettlementCandidate(
                        participantId = "creditor",
                        participantName = "Alice",
                        amount = BigDecimal("30.0"),
                        fromParticipantId = "debtor",
                        fromParticipantName = "我",
                        toParticipantId = "creditor",
                        toParticipantName = "Alice",
                    ),
                ),
            ),
        ).also { loadContextCalls++ }

        override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> {
            createCalls.incrementAndGet()
            requestIds += input.requestId
            inputs += input
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
                onBehalfCandidates = listOf(
                    SettlementCandidate(
                        participantId = if (direction == SettlementDirection.RECEIVE) "debtor" else "creditor",
                        participantName = if (direction == SettlementDirection.RECEIVE) "Debtor" else "Creditor",
                        amount = BigDecimal("30.0"),
                        fromParticipantId = "debtor",
                        fromParticipantName = "Debtor",
                        toParticipantId = "creditor",
                        toParticipantName = "Creditor",
                        kind = SettlementCandidateKind.ON_BEHALF,
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
                onBehalfCandidates = listOf(
                    SettlementCandidate(
                        participantId = "creditor",
                        participantName = "Creditor",
                        amount = BigDecimal("10.0"),
                        fromParticipantId = "debtor-a",
                        fromParticipantName = "Debtor A",
                        toParticipantId = "creditor",
                        toParticipantName = "Creditor",
                        kind = SettlementCandidateKind.ON_BEHALF,
                        onBehalfOptions = listOf(SettlementParticipant("debtor-a", "Debtor A")),
                    ),
                    SettlementCandidate(
                        participantId = "creditor",
                        participantName = "Creditor",
                        amount = BigDecimal("20.0"),
                        fromParticipantId = "debtor-b",
                        fromParticipantName = "Debtor B",
                        toParticipantId = "creditor",
                        toParticipantName = "Creditor",
                        kind = SettlementCandidateKind.ON_BEHALF,
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

    private class BoundCreatorTransferRepository : TransferRepository {
        var lastInput: CreateSettlementTransferInput? = null

        override suspend fun loadContext(activityId: String, direction: SettlementDirection) = Result.success(
            SettlementContext(
                activityId = activityId,
                currentParticipantId = "zhy",
                currentParticipantName = "zhy",
                baseCurrency = "CNY",
                canActOnBehalf = true,
                onBehalfCandidates = listOf(
                    SettlementCandidate(
                        participantId = "whr",
                        participantName = "whr",
                        amount = BigDecimal("52.0"),
                        fromParticipantId = "hzl",
                        fromParticipantName = "hzl",
                        toParticipantId = "whr",
                        toParticipantName = "whr",
                        kind = SettlementCandidateKind.ON_BEHALF,
                        onBehalfOptions = listOf(SettlementParticipant("hzl", "hzl")),
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
