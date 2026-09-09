package com.ffocalors.sharedledger.data.realtime

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.realtime.PostgresAction
import io.github.jan.supabase.realtime.RealtimeChannel
import io.github.jan.supabase.realtime.channel
import io.github.jan.supabase.realtime.postgresChangeFlow
import io.github.jan.supabase.realtime.realtime
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.util.concurrent.atomic.AtomicBoolean

data class ActivityRealtimeTableSpec(
    val table: String,
    val filterColumn: String,
    val domain: ActivityRealtimeDomain,
    val requiresLedgerUnitScope: Boolean = false,
)

val ACTIVITY_REALTIME_TABLE_SPECS: List<ActivityRealtimeTableSpec> = listOf(
    ActivityRealtimeTableSpec("activities", "id", ActivityRealtimeDomain.ActivityIdentity),
    ActivityRealtimeTableSpec("activity_members", "activity_id", ActivityRealtimeDomain.ActivityIdentity),
    ActivityRealtimeTableSpec("ledger_units", "activity_id", ActivityRealtimeDomain.ActivityIdentity),
    ActivityRealtimeTableSpec("participants", "activity_id", ActivityRealtimeDomain.ActivityIdentity),
    ActivityRealtimeTableSpec("participant_claims", "activity_id", ActivityRealtimeDomain.ActivityIdentity),
    ActivityRealtimeTableSpec("expenses", "ledger_unit_id", ActivityRealtimeDomain.Expense, requiresLedgerUnitScope = true),
    ActivityRealtimeTableSpec("expense_debts", "activity_id", ActivityRealtimeDomain.Expense),
    ActivityRealtimeTableSpec("bilateral_debts", "activity_id", ActivityRealtimeDomain.Expense),
    ActivityRealtimeTableSpec("transfers", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("transfer_allocations", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("transfer_components", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("prepayment_accounts", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("prepayment_usages", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("final_settlement_paths", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("transfer_disputes", "activity_id", ActivityRealtimeDomain.Financial),
    ActivityRealtimeTableSpec("attachments", "activity_id", ActivityRealtimeDomain.Attachment),
)

internal fun activityRealtimeFilterExpression(
    spec: ActivityRealtimeTableSpec,
    activityId: String,
): String = "${spec.filterColumn}=eq.$activityId"

internal fun ledgerUnitRealtimeFilterExpression(
    spec: ActivityRealtimeTableSpec,
    ledgerUnitId: String,
): String = "${spec.filterColumn}=eq.$ledgerUnitId"

internal fun mapRealtimeChannelStatus(
    status: RealtimeChannel.Status,
    wasConnected: Boolean,
    closing: Boolean,
): ActivityRealtimeConnectionState = when {
    closing -> ActivityRealtimeConnectionState.Disconnected
    status == RealtimeChannel.Status.SUBSCRIBED -> ActivityRealtimeConnectionState.Connected
    status == RealtimeChannel.Status.SUBSCRIBING && wasConnected -> ActivityRealtimeConnectionState.Reconnecting
    status == RealtimeChannel.Status.SUBSCRIBING -> ActivityRealtimeConnectionState.Connecting
    status == RealtimeChannel.Status.UNSUBSCRIBING && wasConnected -> ActivityRealtimeConnectionState.Reconnecting
    else -> ActivityRealtimeConnectionState.Disconnected
}

internal class RealtimeCloseGate(
    private val action: () -> Unit,
) {
    private val closed = AtomicBoolean(false)

    val isClosed: Boolean
        get() = closed.get()

    fun close() {
        if (closed.compareAndSet(false, true)) action()
    }
}

internal class RealtimeCollectorFailure(cause: Throwable) : RuntimeException(
    "Realtime collector failed",
    cause,
)

internal suspend fun cancelAndJoinRealtimeCollectors(collectorJobs: Collection<Job>) {
    collectorJobs.forEach(Job::cancel)
    collectorJobs.joinAll()
}

/** Supabase Realtime adapter: one RLS-filtered channel and no client-side financial calculations. */
class SupabaseActivityRealtimeSource(
    private val client: SupabaseClient,
    private val scope: CoroutineScope,
) : ActivityRealtimeSource {
    private val lock = Any()
    private val activeByActivity = mutableMapOf<String, SupabaseSubscription>()

    override fun subscribe(
        activityId: String,
        onSignal: (ActivityRealtimeSignal) -> Unit,
        onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
    ): ActivityRealtimeSubscription {
        require(activityId.isNotBlank()) { "activityId must not be blank" }
        val previous = synchronized(lock) { activeByActivity.remove(activityId) }
        previous?.close()
        val subscription = SupabaseSubscription(activityId, onSignal, onConnectionState)
        synchronized(lock) { activeByActivity[activityId] = subscription }
        subscription.start()
        return subscription
    }

    fun close() {
        val subscriptions = synchronized(lock) {
            val current = activeByActivity.values.toList()
            activeByActivity.clear()
            current
        }
        subscriptions.forEach(SupabaseSubscription::close)
    }

    private inner class SupabaseSubscription(
        private val activityId: String,
        private val onSignal: (ActivityRealtimeSignal) -> Unit,
        private val onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
    ) : ActivityRealtimeSubscription {
        private val closeGate = RealtimeCloseGate(::closeInternal)
        private val refreshRequests = Channel<Unit>(Channel.CONFLATED)
        private var channel: RealtimeChannel? = null
        private var sessionJob: Job? = null

        fun start() {
            onConnectionState(ActivityRealtimeConnectionState.Connecting)
            sessionJob = scope.launch { runSessionLoop() }
        }

        private suspend fun runSessionLoop() {
            try {
                while (!closeGate.isClosed) {
                    val ledgerUnitIds = try {
                        loadLedgerUnitIds()
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (error: Throwable) {
                        if (!closeGate.isClosed) onConnectionState(ActivityRealtimeConnectionState.Failed)
                        refreshRequests.receive()
                        continue
                    }
                    runChannelSession(ledgerUnitIds)
                }
            } catch (cancelled: CancellationException) {
                if (!closeGate.isClosed) onConnectionState(ActivityRealtimeConnectionState.Failed)
                throw cancelled
            } catch (_: Throwable) {
                if (!closeGate.isClosed) onConnectionState(ActivityRealtimeConnectionState.Failed)
            } finally {
                removeFromActiveMap()
            }
        }

        private suspend fun loadLedgerUnitIds(): List<String> = client.from("ledger_units").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<LedgerUnitScopeRow>()
            .filterNot { it.isDeleted }
            .map { it.id }

        private suspend fun runChannelSession(ledgerUnitIds: List<String>) {
            val currentChannel = try {
                client.channel("activity:$activityId") {}
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                if (!closeGate.isClosed) onConnectionState(ActivityRealtimeConnectionState.Failed)
                refreshRequests.receive()
                return
            }
            channel = currentChannel
            var refreshRequested = false
            try {
                coroutineScope {
                    if (closeGate.isClosed) return@coroutineScope
                    val collectorJobs = mutableListOf<Job>()
                    ACTIVITY_REALTIME_TABLE_SPECS
                        .filterNot(ActivityRealtimeTableSpec::requiresLedgerUnitScope)
                        .forEach { spec ->
                            collectorJobs += launch { collectChanges(currentChannel, spec, activityId, onSignal) }
                        }
                    val expenseSpec = ACTIVITY_REALTIME_TABLE_SPECS.first { it.requiresLedgerUnitScope }
                    ledgerUnitIds.forEach { ledgerUnitId ->
                        collectorJobs += launch { collectChanges(currentChannel, expenseSpec, ledgerUnitId, onSignal) }
                    }
                    collectorJobs += launch { collectChannelStatus(currentChannel) }
                    currentChannel.subscribe()
                    refreshRequests.receive()
                    refreshRequested = true
                    cancelAndJoinRealtimeCollectors(collectorJobs)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: RealtimeCollectorFailure) {
                // The collector already emitted Failed; close and wait for refresh below.
            } catch (_: Throwable) {
                if (!closeGate.isClosed) onConnectionState(ActivityRealtimeConnectionState.Failed)
            } finally {
                closeChannel(currentChannel)
                if (channel === currentChannel) channel = null
            }
            if (!refreshRequested && !closeGate.isClosed) refreshRequests.receive()
        }

        private suspend fun collectChannelStatus(currentChannel: RealtimeChannel) {
            var wasConnected = false
            currentChannel.status
                .onEach { status ->
                    val mapped = mapRealtimeChannelStatus(status, wasConnected, closeGate.isClosed)
                    if (mapped == ActivityRealtimeConnectionState.Connected) wasConnected = true
                    if (!closeGate.isClosed) onConnectionState(mapped)
                }
                .catch { error ->
                    if (error is CancellationException) throw error
                    if (!closeGate.isClosed) {
                        onConnectionState(ActivityRealtimeConnectionState.Failed)
                    }
                    throw RealtimeCollectorFailure(error)
                }
                .collect()
        }

        private suspend fun collectChanges(
            currentChannel: RealtimeChannel,
            spec: ActivityRealtimeTableSpec,
            filterValue: String,
            signal: (ActivityRealtimeSignal) -> Unit,
        ) {
            try {
                currentChannel.postgresChangeFlow<PostgresAction>("public") {
                    table = spec.table
                    // Keep every table scoped. DELETE rows may lack the scope column; foreground
                    // re-read remains the recovery path under the frozen publication contract.
                    filter { eq(spec.filterColumn, filterValue) }
                }.collect {
                    if (!closeGate.isClosed) {
                        signal(ActivityRealtimeSignal(activityId, spec.domain, eventId = spec.table))
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                if (!closeGate.isClosed) onConnectionState(ActivityRealtimeConnectionState.Failed)
                throw RealtimeCollectorFailure(error)
            }
        }

        override fun close() {
            closeGate.close()
        }

        override fun refreshScope() {
            if (closeGate.isClosed) return
            if (channel != null) onConnectionState(ActivityRealtimeConnectionState.Reconnecting)
            refreshRequests.trySend(Unit)
        }

        private fun closeInternal() {
            onConnectionState(ActivityRealtimeConnectionState.Disconnected)
            sessionJob?.cancel()
            removeFromActiveMap()
        }

        private suspend fun closeChannel(currentChannel: RealtimeChannel) {
            withContext(NonCancellable) {
                runCatching { currentChannel.unsubscribe() }
                runCatching { client.realtime.removeChannel(currentChannel) }
            }
        }

        private fun removeFromActiveMap() {
            synchronized(lock) {
                if (activeByActivity[activityId] === this) activeByActivity.remove(activityId)
            }
        }
    }
}

@Serializable
private data class LedgerUnitScopeRow(
    val id: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

class UnavailableActivityRealtimeSource(
    private val reason: String = "Supabase 未配置，Realtime 不可用",
) : ActivityRealtimeSource {
    override fun subscribe(
        activityId: String,
        onSignal: (ActivityRealtimeSignal) -> Unit,
        onConnectionState: (ActivityRealtimeConnectionState) -> Unit,
    ): ActivityRealtimeSubscription {
        onConnectionState(ActivityRealtimeConnectionState.Failed)
        return ActivityRealtimeSubscription {}
    }

    fun unavailableReason(): String = reason
}

object SupabaseActivityRealtimeSourceFactory {
    fun create(scope: CoroutineScope): ActivityRealtimeSource =
        SupabaseClientProvider.createOrNull()?.let { client ->
            SupabaseActivityRealtimeSource(client, scope)
        } ?: UnavailableActivityRealtimeSource()
}
