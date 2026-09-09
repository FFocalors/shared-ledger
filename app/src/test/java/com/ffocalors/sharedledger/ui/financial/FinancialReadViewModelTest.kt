package com.ffocalors.sharedledger.ui.financial

import com.ffocalors.sharedledger.data.financial.FakeFinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinalSettlementSuggestion
import com.ffocalors.sharedledger.data.financial.FinancialContext
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.data.financial.fakeFinancialRecordSamples
import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import java.math.BigDecimal
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class FinancialReadViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun listUsesOneCachedSnapshotAndFiltersLocally() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val delegate = FakeFinancialRecordRepository()
        val repository = CountingFinancialRepository(delegate)
        val viewModel = FinancialReadViewModel(repository)

        viewModel.loadRecords("fake-preview-activity")
        advanceUntilIdle()
        assertEquals(4, viewModel.recordsState("fake-preview-activity").value.data?.size)
        assertFalse(viewModel.recordsState("fake-preview-activity").value.isLoading)
        assertFalse(viewModel.recordsState("fake-preview-activity").value.isRefreshing)
        assertEquals(1, repository.listAllCalls)

        viewModel.loadRecords("fake-preview-activity", FundRecordType.SETTLEMENT)
        advanceUntilIdle()
        assertEquals(1, viewModel.recordsState("fake-preview-activity").value.data?.size)
        assertFalse(viewModel.recordsState("fake-preview-activity").value.isLoading)
        assertFalse(viewModel.recordsState("fake-preview-activity").value.isRefreshing)
        assertEquals(1, repository.listAllCalls)
    }

    @Test
    fun allFinancialReadStatesClearLoadingAfterSuccessAndCacheHit() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val delegate = FakeFinancialRecordRepository()
        val record = fakeFinancialRecordSamples().first()
        val repository = object : FinancialRecordRepository by delegate {
            override suspend fun loadPrepaymentContext(activityId: String) = FinancialReadResult.Success(
                FinancialContext(
                    activityId = activityId,
                    currency = "CNY",
                    participants = listOf(record.from, record.to),
                    currentParticipantId = record.from.participantId,
                    accounts = emptyList(),
                ),
            )

            override suspend fun previewFinalSettlement(activityId: String) = FinancialReadResult.Success(
                listOf(
                    FinalSettlementSuggestion(
                        id = "suggestion-1",
                        activityId = activityId,
                        from = record.from,
                        to = record.to,
                        amount = record.amount,
                        ordinaryAmount = record.amount,
                        prepaymentReturnAmount = BigDecimal.ZERO,
                        currency = record.currency,
                        sourceFinancialVersion = 1L,
                    ),
                ),
            )
        }
        val viewModel = FinancialReadViewModel(repository)

        viewModel.loadDetail("fake-preview-activity", record.transferId)
        viewModel.loadContext("fake-preview-activity")
        viewModel.loadSettlementPreview("fake-preview-activity")
        advanceUntilIdle()

        assertFalse(viewModel.detailState("fake-preview-activity", record.transferId).value.isLoading)
        assertFalse(viewModel.detailState("fake-preview-activity", record.transferId).value.isRefreshing)
        assertFalse(viewModel.contextState("fake-preview-activity").value.isLoading)
        assertFalse(viewModel.contextState("fake-preview-activity").value.isRefreshing)
        assertFalse(viewModel.previewState("fake-preview-activity").value.isLoading)
        assertFalse(viewModel.previewState("fake-preview-activity").value.isRefreshing)

        viewModel.loadDetail("fake-preview-activity", record.transferId)
        viewModel.loadContext("fake-preview-activity")
        viewModel.loadSettlementPreview("fake-preview-activity")
        advanceUntilIdle()

        assertFalse(viewModel.detailState("fake-preview-activity", record.transferId).value.isLoading)
        assertFalse(viewModel.detailState("fake-preview-activity", record.transferId).value.isRefreshing)
        assertFalse(viewModel.contextState("fake-preview-activity").value.isLoading)
        assertFalse(viewModel.contextState("fake-preview-activity").value.isRefreshing)
        assertFalse(viewModel.previewState("fake-preview-activity").value.isLoading)
        assertFalse(viewModel.previewState("fake-preview-activity").value.isRefreshing)
    }

    @Test
    fun permissionFailureRemovesCachedFinancialData() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val delegate = FakeFinancialRecordRepository()
        val repository = object : FinancialRecordRepository by delegate {
            var next: FinancialReadResult<List<com.ffocalors.sharedledger.domain.financial.FundRecord>>? = null

            override suspend fun listAll(activityId: String): FinancialReadResult<List<com.ffocalors.sharedledger.domain.financial.FundRecord>> =
                next ?: delegate.listAll(activityId)
        }
        val viewModel = FinancialReadViewModel(repository)

        viewModel.loadRecords("fake-preview-activity")
        advanceUntilIdle()
        assertNotNull(viewModel.recordsState("fake-preview-activity").value.data)

        repository.next = FinancialReadResult.Failure("无权访问", ReadFailureKind.PermissionDenied)
        viewModel.loadRecords("fake-preview-activity", force = true)
        advanceUntilIdle()

        assertNull(viewModel.recordsState("fake-preview-activity").value.data)
        assertEquals(ReadFailureKind.PermissionDenied, viewModel.recordsState("fake-preview-activity").value.failureKind)
    }

    @Test
    fun transientFailureKeepsCachedFinancialData() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val delegate = FakeFinancialRecordRepository()
        val repository = object : FinancialRecordRepository by delegate {
            var next: FinancialReadResult<List<com.ffocalors.sharedledger.domain.financial.FundRecord>>? = null

            override suspend fun listAll(activityId: String): FinancialReadResult<List<com.ffocalors.sharedledger.domain.financial.FundRecord>> =
                next ?: delegate.listAll(activityId)
        }
        val viewModel = FinancialReadViewModel(repository)

        viewModel.loadRecords("fake-preview-activity")
        advanceUntilIdle()
        val cached = viewModel.recordsState("fake-preview-activity").value.data
        repository.next = FinancialReadResult.Failure("网络暂时不可用", ReadFailureKind.Transient)
        viewModel.loadRecords("fake-preview-activity", force = true)
        advanceUntilIdle()

        assertEquals(cached, viewModel.recordsState("fake-preview-activity").value.data)
        assertEquals(ReadFailureKind.Transient, viewModel.recordsState("fake-preview-activity").value.failureKind)
    }

    private class CountingFinancialRepository(
        private val delegate: FinancialRecordRepository,
    ) : FinancialRecordRepository by delegate {
        var listAllCalls = 0

        override suspend fun listAll(activityId: String) = delegate.listAll(activityId).also { listAllCalls++ }
    }
}
