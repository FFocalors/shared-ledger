package com.ffocalors.sharedledger.ui.financial

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.financial.FinancialContext
import com.ffocalors.sharedledger.data.financial.FinalSettlementSuggestion
import com.ffocalors.sharedledger.data.financial.FinalSettlementMode
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepositoryFactory
import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.data.common.StructuredReadFailure
import com.ffocalors.sharedledger.data.common.readFailureKind
import com.ffocalors.sharedledger.data.common.shouldRemoveCachedRead
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.ui.cache.QueryCacheKey
import com.ffocalors.sharedledger.ui.cache.QueryCacheState
import com.ffocalors.sharedledger.ui.cache.SessionQueryCache
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class FinancialReadUiState<T>(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val data: T? = null,
    val errorMessage: String? = null,
    val failureKind: ReadFailureKind? = null,
)

typealias FinancialListUiState = FinancialReadUiState<List<FundRecord>>
typealias FinancialDetailUiState = FinancialReadUiState<FundRecord>
typealias FinancialContextUiState = FinancialReadUiState<FinancialContext>
typealias FinalSettlementPreviewUiState = FinancialReadUiState<List<FinalSettlementSuggestion>>

private class FinancialReadException(
    message: String,
    override val failureKind: ReadFailureKind,
) : RuntimeException(message), StructuredReadFailure

/** Session-cached read model for all financial read-only routes. */
class FinancialReadViewModel(
    private val repository: FinancialRecordRepository,
    private val queryCache: SessionQueryCache = SessionQueryCache(),
) : ViewModel() {
    private val listStates = mutableMapOf<String, MutableStateFlow<FinancialListUiState>>()
    private val detailStates = mutableMapOf<String, MutableStateFlow<FinancialDetailUiState>>()
    private val contextStates = mutableMapOf<String, MutableStateFlow<FinancialContextUiState>>()
    private val previewStates = mutableMapOf<String, MutableStateFlow<FinalSettlementPreviewUiState>>()

    fun listState(activityId: String): StateFlow<FinancialListUiState> = recordsState(activityId)

    fun recordsState(activityId: String): StateFlow<FinancialListUiState> =
        listStates.getOrPut(activityId) { MutableStateFlow(FinancialListUiState()) }.asStateFlow()

    fun detailState(activityId: String, transferId: String): StateFlow<FinancialDetailUiState> =
        detailStates.getOrPut(detailScope(activityId, transferId)) {
            MutableStateFlow(FinancialDetailUiState())
        }.asStateFlow()

    fun contextState(activityId: String): StateFlow<FinancialContextUiState> =
        contextStates.getOrPut(activityId) { MutableStateFlow(FinancialContextUiState()) }.asStateFlow()

    fun previewState(
        activityId: String,
        mode: FinalSettlementMode = FinalSettlementMode.BASE_UNIFIED,
    ): StateFlow<FinalSettlementPreviewUiState> =
        previewStates.getOrPut(previewScope(activityId, mode)) { MutableStateFlow(FinalSettlementPreviewUiState()) }.asStateFlow()

    fun settlementPreviewState(
        activityId: String,
        mode: FinalSettlementMode = FinalSettlementMode.BASE_UNIFIED,
    ): StateFlow<FinalSettlementPreviewUiState> = previewState(activityId, mode)

    /** Loads one full timeline snapshot; [type] is always filtered locally. */
    fun loadList(activityId: String, type: FundRecordType? = null, force: Boolean = false) =
        loadRecords(activityId, type, force)

    fun loadRecords(activityId: String, type: FundRecordType? = null, force: Boolean = false) {
        val state = listStates.getOrPut(activityId) { MutableStateFlow(FinancialListUiState()) }
        val key = listKey(activityId)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            state.value = FinancialListUiState(
                isLoading = false,
                isRefreshing = false,
                data = cached.value.filterBy(type),
            )
            return
        }
        val existing = cached.value ?: state.value.data
        state.value = loadingState(existing?.filterBy(type))
        viewModelScope.launch {
            val result = queryCache.getOrLoad(key, forceRefresh = true) {
                repository.listAll(activityId).toCacheResult()
            }
            result.fold(
                onSuccess = { records ->
                    state.value = FinancialListUiState(
                        isLoading = false,
                        isRefreshing = false,
                        data = records.filterBy(type),
                    )
                },
                onFailure = { error -> state.value = failureState(existing?.filterBy(type), error) },
            )
        }
    }

    fun loadDetail(activityId: String, transferId: String, force: Boolean = false) {
        val scope = detailScope(activityId, transferId)
        val state = detailStates.getOrPut(scope) { MutableStateFlow(FinancialDetailUiState()) }
        val key = detailKey(activityId, transferId)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            state.value = FinancialDetailUiState(
                isLoading = false,
                isRefreshing = false,
                data = cached.value,
            )
            return
        }
        val existing = cached.value ?: state.value.data
        state.value = loadingState(existing)
        viewModelScope.launch {
            queryCache.getOrLoad(key, forceRefresh = true) {
                repository.get(activityId, transferId).toCacheResult()
            }.fold(
                onSuccess = {
                    state.value = FinancialDetailUiState(
                        isLoading = false,
                        isRefreshing = false,
                        data = it,
                    )
                },
                onFailure = { state.value = failureState(existing, it) },
            )
        }
    }

    fun loadContext(activityId: String, force: Boolean = false) {
        val state = contextStates.getOrPut(activityId) { MutableStateFlow(FinancialContextUiState()) }
        val key = contextKey(activityId)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            state.value = FinancialContextUiState(
                isLoading = false,
                isRefreshing = false,
                data = cached.value,
            )
            return
        }
        val existing = cached.value ?: state.value.data
        state.value = loadingState(existing)
        viewModelScope.launch {
            queryCache.getOrLoad(key, forceRefresh = true) {
                repository.loadPrepaymentContext(activityId).toCacheResult()
            }.fold(
                onSuccess = {
                    state.value = FinancialContextUiState(
                        isLoading = false,
                        isRefreshing = false,
                        data = it,
                    )
                },
                onFailure = { state.value = failureState(existing, it) },
            )
        }
    }

    fun loadSettlementPreview(
        activityId: String,
        mode: FinalSettlementMode = FinalSettlementMode.BASE_UNIFIED,
        force: Boolean = false,
    ) {
        val scope = previewScope(activityId, mode)
        val state = previewStates.getOrPut(scope) { MutableStateFlow(FinalSettlementPreviewUiState()) }
        val key = previewKey(activityId, mode)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            state.value = FinalSettlementPreviewUiState(
                isLoading = false,
                isRefreshing = false,
                data = cached.value,
            )
            return
        }
        val existing = cached.value ?: state.value.data
        state.value = loadingState(existing)
        viewModelScope.launch {
            queryCache.getOrLoad(key, forceRefresh = true) {
                repository.previewFinalSettlement(activityId, mode).toCacheResult()
            }.fold(
                onSuccess = {
                    state.value = FinalSettlementPreviewUiState(
                        isLoading = false,
                        isRefreshing = false,
                        data = it,
                    )
                },
                onFailure = { state.value = failureState(existing, it) },
            )
        }
    }

    /** Precise invalidation for Realtime callbacks or a successful/committed write. */
    fun invalidateActivity(activityId: String) {
        queryCache.invalidate(listKey(activityId))
        queryCache.invalidate(contextKey(activityId))
        queryCache.invalidatePrefix("financial-query:preview:$activityId:")
        queryCache.invalidatePrefix("financial-query:detail:$activityId:")
    }

    fun invalidateTransfer(activityId: String, transferId: String) {
        queryCache.invalidate(listKey(activityId))
        queryCache.invalidate(detailKey(activityId, transferId))
    }

    fun invalidateAfterWrite(activityId: String, transferId: String? = null) {
        if (transferId == null) invalidateActivity(activityId)
        else invalidateTransfer(activityId, transferId)
    }

    fun clearSessionCache() = queryCache.clear()

    private fun <T : Any> loadingState(existing: T?): FinancialReadUiState<T> = FinancialReadUiState(
        isLoading = existing == null,
        isRefreshing = existing != null,
        data = existing,
    )

    private fun <T : Any> failureState(existing: T?, error: Throwable) = FinancialReadUiState<T>(
        isLoading = false,
        isRefreshing = false,
        data = existing.takeUnless { error.readFailureKind().shouldRemoveCachedRead() },
        errorMessage = error.message ?: "资金数据加载失败，请重试",
        failureKind = error.readFailureKind(),
    )

    private fun List<FundRecord>.filterBy(type: FundRecordType?): List<FundRecord> =
        if (type == null) this else filter { it.type == type }

    private suspend fun <T> FinancialReadResult<T>.toCacheResult(): Result<T> = when (this) {
        is FinancialReadResult.Success -> Result.success(value)
        is FinancialReadResult.Failure -> Result.failure(FinancialReadException(message, kind))
    }

    private fun listKey(activityId: String) = QueryCacheKey<List<FundRecord>>("financial-query:list:$activityId")
    private fun detailKey(activityId: String, transferId: String) =
        QueryCacheKey<FundRecord>(detailScope(activityId, transferId))
    private fun detailScope(activityId: String, transferId: String) = "financial-query:detail:$activityId:$transferId"
    private fun contextKey(activityId: String) = QueryCacheKey<FinancialContext>("financial-query:context:$activityId")
    private fun previewScope(activityId: String, mode: FinalSettlementMode) =
        "financial-query:preview:$activityId:${mode.databaseValue}"

    private fun previewKey(activityId: String, mode: FinalSettlementMode) =
        QueryCacheKey<List<FinalSettlementSuggestion>>(previewScope(activityId, mode))

    class Factory(
        private val repository: FinancialRecordRepository = FinancialRecordRepositoryFactory.create(),
        private val queryCache: SessionQueryCache = SessionQueryCache(),
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            FinancialReadViewModel(repository, queryCache) as T
    }
}
