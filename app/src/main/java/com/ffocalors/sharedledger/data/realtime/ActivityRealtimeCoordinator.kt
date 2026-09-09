package com.ffocalors.sharedledger.data.realtime

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay

/** The read models that can be invalidated by one activity-scoped event stream. */
enum class ActivityRealtimeDomain {
    ActivityIdentity,
    Expense,
    Financial,
    Attachment,
}

enum class ActivityRealtimeConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Failed,
}

data class ActivityRealtimeSignal(
    val activityId: String,
    val domain: ActivityRealtimeDomain,
    val eventId: String? = null,
)

fun interface ActivityRealtimeSubscription {
    fun close()

    /** Re-read any dynamic table scope before rebuilding the subscription. */
    fun refreshScope() = Unit
}

/** SDK-free source contract. A Supabase Realtime adapter can implement this later. */
interface ActivityRealtimeSource {
    fun subscribe(
        activityId: String,
        onSignal: (ActivityRealtimeSignal) -> Unit,
        onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
    ): ActivityRealtimeSubscription
}

data class ActivityRealtimeState(
    val activityId: String? = null,
    val connectionState: ActivityRealtimeConnectionState = ActivityRealtimeConnectionState.Disconnected,
    val pendingDomains: Set<ActivityRealtimeDomain> = emptySet(),
    val refreshingDomains: Set<ActivityRealtimeDomain> = emptySet(),
    val lastErrors: Map<ActivityRealtimeDomain, String> = emptyMap(),
    val lastRefreshedAt: Map<ActivityRealtimeDomain, Long> = emptyMap(),
)

private class DomainRefreshWorker(
    scope: CoroutineScope,
    private val debounceMillis: Long,
    private val onQueued: () -> Unit,
    private val onStarted: () -> Unit,
    private val onFinished: (Result<Unit>) -> Unit,
    private val refresh: suspend () -> Result<Unit>,
) {
    private val requests = Channel<Unit>(Channel.UNLIMITED)
    private val job: Job = scope.launch {
        for (ignored in requests) {
            delay(debounceMillis)
            while (requests.tryReceive().isSuccess) {
                // Coalesce all signals received during the debounce window.
            }
            onStarted()
            val result = try {
                refresh()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                Result.failure(error)
            }
            onFinished(result)
        }
    }

    fun request() {
        onQueued()
        requests.trySend(Unit)
    }

    fun close() {
        requests.close()
        job.cancel()
    }
}

private data class ActiveActivity(
    val activityId: String,
    val generation: Long,
    val workers: Map<ActivityRealtimeDomain, DomainRefreshWorker>,
    var subscription: ActivityRealtimeSubscription? = null,
    var scopeRefreshPendingReconnect: Boolean = false,
    var suppressNextIdentityScopeRefresh: Boolean = false,
) {
    fun close() {
        subscription?.close()
        workers.values.forEach(DomainRefreshWorker::close)
    }
}

/**
 * Coordinates one activity-scoped subscription with the application's read-model refreshes.
 * The coordinator owns no Supabase types and can therefore be tested with deterministic sources.
 */
class ActivityRealtimeCoordinator(
    private val scope: CoroutineScope,
    private val source: ActivityRealtimeSource,
    private val refresh: suspend (activityId: String, domain: ActivityRealtimeDomain) -> Result<Unit>,
    private val debounceMillis: Long = DEFAULT_DEBOUNCE_MILLIS,
) {
    private val mutableState = MutableStateFlow(ActivityRealtimeState())
    val state: StateFlow<ActivityRealtimeState> = mutableState.asStateFlow()

    private var generation: Long = 0
    private var active: ActiveActivity? = null

    fun start(activityId: String) {
        require(activityId.isNotBlank()) { "activityId must not be blank" }
        stop()
        val currentGeneration = generation
        val workers = ActivityRealtimeDomain.entries.associateWith { domain ->
            DomainRefreshWorker(
                scope = scope,
                debounceMillis = debounceMillis,
                onQueued = { markQueued(activityId, currentGeneration, domain) },
                onStarted = { markStarted(activityId, currentGeneration, domain) },
                onFinished = { result -> markFinished(activityId, currentGeneration, domain, result) },
                refresh = { refresh(activityId, domain) },
            )
        }
        val current = ActiveActivity(activityId, currentGeneration, workers)
        active = current
        mutableState.value = ActivityRealtimeState(
            activityId = activityId,
            connectionState = ActivityRealtimeConnectionState.Connecting,
        )
        try {
            current.subscription = source.subscribe(
                activityId = activityId,
                onSignal = { signal -> enqueueSignal(currentGeneration, signal) },
                onConnectionState = { connectionState -> updateConnection(currentGeneration, connectionState) },
            )
        } catch (cause: Throwable) {
            mutableState.value = mutableState.value.copy(
                connectionState = ActivityRealtimeConnectionState.Failed,
                lastErrors = mutableState.value.lastErrors + (
                    ActivityRealtimeDomain.ActivityIdentity to (cause.message ?: "Realtime 订阅失败")
                ),
            )
        }
    }

    fun stop() {
        val previous = active
        active = null
        generation += 1
        previous?.close()
        mutableState.value = ActivityRealtimeState()
    }

    fun onForeground() {
        refreshScopeThenRequestAll()
    }

    fun onReconnect() {
        refreshScopeThenRequestAll()
    }

    private fun refreshScopeThenRequestAll() {
        active?.let { current ->
            refreshScopeIfCurrent(
                activityId = current.activityId,
                signalGeneration = current.generation,
                suppressNextIdentityScopeRefresh = true,
            )
        }
        // A scope refresh is best effort. Even when it fails, every read model
        // must still get its normal foreground/reconnect refresh opportunity.
        requestAllDomains()
    }

    private fun requestAllDomains() {
        active?.workers?.values?.forEach(DomainRefreshWorker::request)
    }

    private fun enqueueSignal(signalGeneration: Long, signal: ActivityRealtimeSignal) {
        val current = active ?: return
        if (current.generation != signalGeneration || current.activityId != signal.activityId) return
        current.workers[signal.domain]?.request()
    }

    private fun updateConnection(
        signalGeneration: Long,
        connectionState: ActivityRealtimeConnectionState,
    ) {
        val current = active ?: return
        if (current.generation != signalGeneration) return
        val wasReconnecting = mutableState.value.connectionState == ActivityRealtimeConnectionState.Reconnecting
        mutableState.value = mutableState.value.copy(connectionState = connectionState)
        if (wasReconnecting && connectionState == ActivityRealtimeConnectionState.Connected) {
            if (current.scopeRefreshPendingReconnect) {
                current.scopeRefreshPendingReconnect = false
                requestAllDomains()
            } else {
                refreshScopeThenRequestAll()
            }
        }
    }

    private fun markQueued(activityId: String, signalGeneration: Long, domain: ActivityRealtimeDomain) {
        if (!isCurrent(activityId, signalGeneration)) return
        mutableState.value = mutableState.value.copy(
            pendingDomains = mutableState.value.pendingDomains + domain,
        )
    }

    private fun markStarted(activityId: String, signalGeneration: Long, domain: ActivityRealtimeDomain) {
        if (!isCurrent(activityId, signalGeneration)) return
        mutableState.value = mutableState.value.copy(
            pendingDomains = mutableState.value.pendingDomains - domain,
            refreshingDomains = mutableState.value.refreshingDomains + domain,
        )
    }

    private fun markFinished(
        activityId: String,
        signalGeneration: Long,
        domain: ActivityRealtimeDomain,
        result: Result<Unit>,
    ) {
        if (!isCurrent(activityId, signalGeneration)) return
        val current = mutableState.value
        val errors = current.lastErrors.toMutableMap()
        val refreshed = current.lastRefreshedAt.toMutableMap()
        result.fold(
            onSuccess = {
                errors.remove(domain)
                refreshed[domain] = System.currentTimeMillis()
            },
            onFailure = { error -> errors[domain] = error.message ?: "刷新失败" },
        )
        mutableState.value = current.copy(
            refreshingDomains = current.refreshingDomains - domain,
            lastErrors = errors,
            lastRefreshedAt = refreshed,
        )
        if (result.isSuccess && domain == ActivityRealtimeDomain.ActivityIdentity) {
            val currentActivity = active
            if (currentActivity?.let {
                    it.activityId == activityId &&
                        it.generation == signalGeneration &&
                        it.suppressNextIdentityScopeRefresh
                } == true
            ) {
                currentActivity.suppressNextIdentityScopeRefresh = false
            } else {
                refreshScopeIfCurrent(activityId, signalGeneration)
            }
        }
    }

    private fun refreshScopeIfCurrent(
        activityId: String,
        signalGeneration: Long,
        suppressNextIdentityScopeRefresh: Boolean = false,
    ) {
        val current = active ?: return
        if (current.activityId != activityId || current.generation != signalGeneration) return
        val subscription = current.subscription ?: return
        if (suppressNextIdentityScopeRefresh) {
            current.suppressNextIdentityScopeRefresh = true
        }
        current.scopeRefreshPendingReconnect = true
        try {
            subscription.refreshScope()
            if (!isCurrent(activityId, signalGeneration)) return
            val state = mutableState.value
            if (ActivityRealtimeDomain.ActivityIdentity in state.lastErrors) {
                mutableState.value = state.copy(
                    lastErrors = state.lastErrors - ActivityRealtimeDomain.ActivityIdentity,
                )
            }
        } catch (error: Throwable) {
            current.scopeRefreshPendingReconnect = false
            current.suppressNextIdentityScopeRefresh = false
            if (!isCurrent(activityId, signalGeneration)) return
            mutableState.value = mutableState.value.copy(
                lastErrors = mutableState.value.lastErrors + (
                    ActivityRealtimeDomain.ActivityIdentity to (error.message ?: "Realtime 作用域刷新失败")
                ),
            )
        }
    }

    private fun isCurrent(activityId: String, signalGeneration: Long): Boolean =
        active?.let { it.activityId == activityId && it.generation == signalGeneration } == true

    companion object {
        const val DEFAULT_DEBOUNCE_MILLIS = 250L
    }
}
