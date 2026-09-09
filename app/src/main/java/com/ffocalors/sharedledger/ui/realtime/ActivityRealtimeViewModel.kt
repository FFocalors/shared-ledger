package com.ffocalors.sharedledger.ui.realtime

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeConnectionState
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeCoordinator
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeDomain
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeSource
import com.ffocalors.sharedledger.data.realtime.SupabaseActivityRealtimeSourceFactory
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Monotonic invalidation versions for the four activity read-model domains. */
data class RealtimeDomainRevisions(
    val activityIdentity: Long = 0L,
    val expense: Long = 0L,
    val financial: Long = 0L,
    val attachment: Long = 0L,
) {
    operator fun get(domain: ActivityRealtimeDomain): Long = when (domain) {
        ActivityRealtimeDomain.ActivityIdentity -> activityIdentity
        ActivityRealtimeDomain.Expense -> expense
        ActivityRealtimeDomain.Financial -> financial
        ActivityRealtimeDomain.Attachment -> attachment
    }

    fun increment(domain: ActivityRealtimeDomain): RealtimeDomainRevisions = when (domain) {
        ActivityRealtimeDomain.ActivityIdentity -> copy(activityIdentity = activityIdentity + 1)
        ActivityRealtimeDomain.Expense -> copy(expense = expense + 1)
        ActivityRealtimeDomain.Financial -> copy(financial = financial + 1)
        ActivityRealtimeDomain.Attachment -> copy(attachment = attachment + 1)
    }
}

data class RealtimeInvalidation(
    val activityId: String,
    val domain: ActivityRealtimeDomain,
    val revision: Long,
)

/** Diagnostic state for a single activity-scoped realtime subscription. */
data class RealtimeUiState(
    val activeActivityId: String? = null,
    val connectionState: ActivityRealtimeConnectionState = ActivityRealtimeConnectionState.Disconnected,
    val revisions: RealtimeDomainRevisions = RealtimeDomainRevisions(),
    val pendingDomains: Set<ActivityRealtimeDomain> = emptySet(),
    val refreshingDomains: Set<ActivityRealtimeDomain> = emptySet(),
    val errors: Map<ActivityRealtimeDomain, String> = emptyMap(),
    val lastInvalidation: RealtimeInvalidation? = null,
)

/**
 * View-model bridge for activity realtime invalidations.
 *
 * The coordinator owns subscription lifetime and debounce. This class only turns a
 * successful refresh callback into a monotonically increasing read-model revision;
 * repository/ViewModel owners can re-read their own domain when that revision changes.
 */
class ActivityRealtimeViewModel(
    private val sourceFactory: (kotlinx.coroutines.CoroutineScope) -> ActivityRealtimeSource =
        SupabaseActivityRealtimeSourceFactory::create,
) : ViewModel() {
    private val _uiState = MutableStateFlow(RealtimeUiState())
    val uiState: StateFlow<RealtimeUiState> = _uiState.asStateFlow()

    private var coordinator: ActivityRealtimeCoordinator? = null
    private var bridgeJob: Job? = null
    private var observedActivityId: String? = null
    private var bridgeGeneration = 0L

    fun observeActivity(activityId: String?) {
        if (activityId.isNullOrBlank()) {
            stop()
            return
        }
        if (activityId == observedActivityId && coordinator != null) return

        stop()
        observedActivityId = activityId
        val generation = bridgeGeneration
        val source = sourceFactory(viewModelScope)
        val nextCoordinator = ActivityRealtimeCoordinator(
            scope = viewModelScope,
            source = source,
            refresh = { refreshedActivityId, domain ->
                publishInvalidation(generation, refreshedActivityId, domain)
                Result.success(Unit)
            },
        )
        coordinator = nextCoordinator
        bridgeJob = viewModelScope.launch {
            nextCoordinator.state.collect { state ->
                if (generation == bridgeGeneration) publishCoordinatorState(state)
            }
        }
        nextCoordinator.start(activityId)
    }

    fun stop() {
        bridgeGeneration += 1
        bridgeJob?.cancel()
        bridgeJob = null
        coordinator?.stop()
        coordinator = null
        observedActivityId = null
        _uiState.value = RealtimeUiState()
    }

    fun onForeground() {
        coordinator?.onForeground()
    }

    override fun onCleared() {
        stop()
        super.onCleared()
    }

    private fun publishCoordinatorState(state: com.ffocalors.sharedledger.data.realtime.ActivityRealtimeState) {
        _uiState.value = _uiState.value.copy(
            activeActivityId = state.activityId,
            connectionState = state.connectionState,
            pendingDomains = state.pendingDomains,
            refreshingDomains = state.refreshingDomains,
            errors = state.lastErrors,
        )
    }

    private fun publishInvalidation(
        generation: Long,
        activityId: String,
        domain: ActivityRealtimeDomain,
    ) {
        if (generation != bridgeGeneration || activityId != observedActivityId) return
        val nextRevisions = _uiState.value.revisions.increment(domain)
        _uiState.value = _uiState.value.copy(
            revisions = nextRevisions,
            lastInvalidation = RealtimeInvalidation(activityId, domain, nextRevisions[domain]),
        )
    }
}

/** Alternate descriptive name for callers that already use an Activity prefix. */
typealias ActivityRealtimeUiState = RealtimeUiState
