package com.ffocalors.sharedledger.ui.cache

import android.util.Log
import com.ffocalors.sharedledger.BuildConfig
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlin.coroutines.coroutineContext

/** A clock boundary keeps cache expiry deterministic in unit tests. */
fun interface QueryCacheClock {
    fun nowMillis(): Long
}

/** A typed, stable identifier for one query in a [SessionQueryCache]. */
data class QueryCacheKey<T : Any>(val value: String)

enum class QueryCacheState {
    Fresh,
    Stale,
    Miss,
}

/** Diagnostic event kinds emitted only when a [QueryCacheDebugObserver] is supplied. */
enum class QueryCacheDebugEventType {
    Hit,
    Miss,
    Stale,
    SingleFlightJoined,
    LoadSucceeded,
}

/** A key-free diagnostic event; it never exposes user, business, amount, or content data. */
data class QueryCacheDebugEvent(
    val type: QueryCacheDebugEventType,
    val loadDurationMillis: Long? = null,
)

/** Optional injectable diagnostics sink. The default sink is debug-only and key-free. */
fun interface QueryCacheDebugObserver {
    fun onEvent(event: QueryCacheDebugEvent)
}

private fun defaultDebugObserver(): QueryCacheDebugObserver? =
    if (BuildConfig.DEBUG) {
        QueryCacheDebugObserver { event ->
            // Keep diagnostics anonymous: event payloads contain no query key or user data.
            Log.d(
                "SharedLedgerCache",
                "event=${event.type} durationMs=${event.loadDurationMillis ?: -1L}",
            )
        }
    } else {
        null
    }

/** A cache read can expose stale content while a caller refreshes it. */
data class QueryCacheRead<T : Any>(
    val state: QueryCacheState,
    val value: T? = null,
)

/**
 * A process-memory cache intended to live for one authenticated UI session.
 *
 * Values are only written after successful reads. Requests for the same key share
 * one in-flight read. If that key is invalidated during the read, its result is
 * not committed and one trailing read is started automatically after the current
 * read finishes.
 */
class SessionQueryCache(
    private val ttlMillis: Long = DEFAULT_TTL_MILLIS,
    private val clock: QueryCacheClock = QueryCacheClock { System.currentTimeMillis() },
    private val refreshScope: CoroutineScope? = null,
    private val debugObserver: QueryCacheDebugObserver? = defaultDebugObserver(),
) {
    init {
        require(ttlMillis >= 0L) { "ttlMillis must not be negative" }
    }

    private data class Entry<T : Any>(val value: T, val storedAtMillis: Long)

    private class Flight<T : Any>(
        val loader: suspend () -> Result<T>,
        val scope: CoroutineScope,
        val trailingScope: CoroutineScope,
        val deferred: CompletableDeferred<Result<T>> = CompletableDeferred(),
        val generation: Long,
    ) {
        var trailingRefresh = false
    }

    private val lock = Any()
    private val entries = mutableMapOf<String, Entry<*>>()
    private val staleKeys = mutableSetOf<String>()
    private val generations = mutableMapOf<String, Long>()
    private val flights = mutableMapOf<String, Flight<*>>()
    private val fallbackTrailingScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** Reads without starting I/O; stale values remain available to render. */
    fun <T : Any> read(key: QueryCacheKey<T>): QueryCacheRead<T> {
        val result = synchronized(lock) { readLocked(key) }
        emit(result.state.debugEvent())
        return result
    }

    /**
     * Reads a fresh value or performs a shared refresh. A forced refresh always
     * bypasses a fresh entry, but still joins an existing refresh for the key.
     */
    suspend fun <T : Any> getOrLoad(
        key: QueryCacheKey<T>,
        forceRefresh: Boolean = false,
        loader: suspend () -> Result<T>,
    ): Result<T> {
        var immediate: Result<T>? = null
        var selectedFlight: Flight<T>? = null
        val debugEvents = mutableListOf<QueryCacheDebugEvent>()
        synchronized(lock) {
            val existing = flights[key.value]
            if (!forceRefresh) {
                val cached = readLocked(key)
                debugEvents += cached.state.debugEvent()
                if (cached.state == QueryCacheState.Fresh && cached.value != null) {
                    immediate = Result.success(cached.value)
                }
            }
            if (immediate == null && existing != null) {
                debugEvents += QueryCacheDebugEvent(QueryCacheDebugEventType.SingleFlightJoined)
                @Suppress("UNCHECKED_CAST")
                selectedFlight = existing as Flight<T>
            } else if (immediate == null) {
                val next = Flight<T>(
                    loader = loader,
                    scope = refreshScope ?: CoroutineScope(coroutineContext),
                    trailingScope = refreshScope ?: fallbackTrailingScope,
                    generation = generations[key.value] ?: 0L,
                )
                flights[key.value] = next
                next.scope.launch { runFlight(key.value, next) }
                selectedFlight = next
            }
        }
        debugEvents.forEach(::emit)
        return immediate ?: selectedFlight!!.deferred.await()
    }

    /** Marks a query stale. An in-flight query gets a trailing refresh. */
    fun <T : Any> invalidate(key: QueryCacheKey<T>) {
        synchronized(lock) {
            generations[key.value] = (generations[key.value] ?: 0L) + 1L
            staleKeys += key.value
            @Suppress("UNCHECKED_CAST")
            (flights[key.value] as Flight<T>?)?.trailingRefresh = true
        }
    }

    /** Removes a query completely, useful after permission/not-found failures. */
    fun <T : Any> remove(key: QueryCacheKey<T>) {
        synchronized(lock) {
            entries.remove(key.value)
            staleKeys.remove(key.value)
            generations[key.value] = (generations[key.value] ?: 0L) + 1L
            @Suppress("UNCHECKED_CAST")
            (flights[key.value] as Flight<T>?)?.trailingRefresh = false
        }
    }

    /** Removes all cached values under a stable prefix while allowing active readers to finish. */
    fun removePrefix(prefix: String) {
        synchronized(lock) {
            val keys = (entries.keys + staleKeys + generations.keys + flights.keys)
                .filter { it.startsWith(prefix) }
                .toSet()
            keys.forEach { key ->
                entries.remove(key)
                staleKeys.remove(key)
                generations[key] = (generations[key] ?: 0L) + 1L
                flights[key]?.trailingRefresh = false
            }
        }
    }

    /** Invalidates every query whose stable identifier starts with [prefix]. */
    fun invalidatePrefix(prefix: String) {
        synchronized(lock) {
            (entries.keys + flights.keys).filter { it.startsWith(prefix) }.forEach { key ->
                generations[key] = (generations[key] ?: 0L) + 1L
                staleKeys += key
                @Suppress("UNCHECKED_CAST")
                (flights[key] as Flight<Any>?)?.trailingRefresh = true
            }
        }
    }

    /** Drops all session values. In-flight results are prevented from being committed. */
    fun clear() {
        synchronized(lock) {
            entries.clear()
            staleKeys.clear()
            (generations.keys + flights.keys).forEach { key ->
                generations[key] = (generations[key] ?: 0L) + 1L
            }
            flights.values.forEach { it.trailingRefresh = false }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T : Any> readLocked(key: QueryCacheKey<T>): QueryCacheRead<T> {
        val entry = entries[key.value] as Entry<T>?
        if (entry == null) {
            return QueryCacheRead(QueryCacheState.Miss)
        }
        val age = (clock.nowMillis() - entry.storedAtMillis).coerceAtLeast(0L)
        return QueryCacheRead(
            state = if (key.value !in staleKeys && age < ttlMillis) {
                QueryCacheState.Fresh
            } else {
                QueryCacheState.Stale
            },
            value = entry.value,
        )
    }

    private fun QueryCacheState.debugEvent(): QueryCacheDebugEvent = QueryCacheDebugEvent(
        type = when (this) {
            QueryCacheState.Fresh -> QueryCacheDebugEventType.Hit
            QueryCacheState.Stale -> QueryCacheDebugEventType.Stale
            QueryCacheState.Miss -> QueryCacheDebugEventType.Miss
        },
    )

    private fun emit(event: QueryCacheDebugEvent) {
        runCatching { debugObserver?.onEvent(event) }
    }

    private suspend fun <T : Any> runFlight(key: String, flight: Flight<T>) {
        try {
            val startedAtMillis = clock.nowMillis()
            val result = try {
                flight.loader()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                Result.failure(error)
            }
            if (result.isSuccess) {
                emit(
                    QueryCacheDebugEvent(
                        type = QueryCacheDebugEventType.LoadSucceeded,
                        loadDurationMillis = (clock.nowMillis() - startedAtMillis).coerceAtLeast(0L),
                    ),
                )
            }
            var trailing = false
            var trailingGeneration: Long? = null
            synchronized(lock) {
                val currentGeneration = generations[key] ?: 0L
                val isCurrent = flights[key] === flight
                val invalidated = currentGeneration != flight.generation || flight.trailingRefresh
                if (isCurrent) {
                    flights.remove(key)
                    trailing = flight.trailingRefresh
                    if (trailing) trailingGeneration = currentGeneration
                    if (result.isSuccess && !invalidated) {
                        result.getOrNull()?.let {
                            entries[key] = Entry(it, clock.nowMillis())
                            staleKeys.remove(key)
                        }
                    }
                }
            }
            flight.deferred.complete(result)
            if (trailing) {
                // Start after completing the first waiter so invalidation never blocks
                // the UI on a second network request.
                flight.trailingScope.launch {
                    val expectedGeneration = trailingGeneration ?: return@launch
                    val next = Flight(
                        loader = flight.loader,
                        scope = flight.scope,
                        trailingScope = flight.trailingScope,
                        generation = synchronized(lock) { generations[key] ?: 0L },
                    )
                    val shouldRun = synchronized(lock) {
                        if (flights[key] != null || generations[key] != expectedGeneration) {
                            false
                        } else {
                            flights[key] = next
                            true
                        }
                    }
                    if (shouldRun) runFlight(key, next)
                }
            }
        } catch (cancelled: CancellationException) {
            synchronized(lock) {
                if (flights[key] === flight) {
                    flights.remove(key)
                }
                flight.trailingRefresh = false
            }
            // A canceled owner must not leave other single-flight waiters suspended forever.
            flight.deferred.completeExceptionally(cancelled)
            throw cancelled
        }
    }

    companion object {
        const val DEFAULT_TTL_MILLIS = 60_000L
    }
}
