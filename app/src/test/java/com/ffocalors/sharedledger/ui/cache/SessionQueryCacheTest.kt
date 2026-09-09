package com.ffocalors.sharedledger.ui.cache

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SessionQueryCacheTest {
    private class FakeClock(var now: Long = 0L) : QueryCacheClock {
        override fun nowMillis() = now
    }

    @Test
    fun reportsFreshStaleAndMissWithInjectedClock() {
        val clock = FakeClock()
        val cache = SessionQueryCache(ttlMillis = 60_000L, clock = clock)
        val key = QueryCacheKey<String>("key")

        assertEquals(QueryCacheState.Miss, cache.read(key).state)
        runTest { cache.getOrLoad(key) { Result.success("value") } }
        assertEquals(QueryCacheState.Fresh, cache.read(key).state)
        clock.now = 60_000L
        assertEquals(QueryCacheState.Stale, cache.read(key).state)
        assertEquals("value", cache.read(key).value)
    }

    @Test
    fun concurrentLoadsShareOneRequest() = runTest {
        val events = mutableListOf<QueryCacheDebugEvent>()
        val cache = SessionQueryCache(
            refreshScope = this,
            debugObserver = QueryCacheDebugObserver { events += it },
        )
        val key = QueryCacheKey<String>("same")
        val gate = CompletableDeferred<Result<String>>()
        var calls = 0
        val first = async { cache.getOrLoad(key) { calls++; gate.await() } }
        val second = async { cache.getOrLoad(key) { calls++; Result.success("wrong") } }
        runCurrent()
        assertEquals(1, calls)
        gate.complete(Result.success("value"))
        assertEquals("value", first.await().getOrThrow())
        assertEquals("value", second.await().getOrThrow())
        assertTrue(events.any { it.type == QueryCacheDebugEventType.SingleFlightJoined })
    }

    @Test
    fun invalidationDuringLoadSchedulesTrailingRefresh() = runTest {
        val cache = SessionQueryCache(refreshScope = this)
        val key = QueryCacheKey<String>("trailing")
        val firstGate = CompletableDeferred<Result<String>>()
        var calls = 0
        val first = async {
            cache.getOrLoad(key) {
                calls++
                if (calls == 1) firstGate.await() else Result.success("new")
            }
        }
        runCurrent()
        cache.invalidate(key)
        firstGate.complete(Result.success("old"))
        assertEquals("old", first.await().getOrThrow())
        advanceUntilIdle()
        assertEquals(2, calls)
        assertEquals("new", cache.read(key).value)
    }

    @Test
    fun clearDropsValuesAndPreventsInFlightResultFromReturningToCache() = runTest {
        val cache = SessionQueryCache(refreshScope = this)
        val key = QueryCacheKey<String>("clear")
        val gate = CompletableDeferred<Result<String>>()
        val load = async { cache.getOrLoad(key) { gate.await() } }
        runCurrent()
        cache.clear()
        gate.complete(Result.success("discarded"))
        assertEquals("discarded", load.await().getOrThrow())
        advanceUntilIdle()
        assertEquals(QueryCacheState.Miss, cache.read(key).state)
        assertNull(cache.read(key).value)
    }

    @Test
    fun debugObserverReportsStateAndSuccessfulLoadDurationWithoutAKey() = runTest {
        val clock = FakeClock()
        val events = mutableListOf<QueryCacheDebugEvent>()
        val cache = SessionQueryCache(
            clock = clock,
            debugObserver = QueryCacheDebugObserver { events += it },
        )
        val key = QueryCacheKey<String>("user-id-must-not-be-emitted")

        cache.getOrLoad(key) {
            clock.now = 17L
            Result.success("value")
        }
        cache.getOrLoad(key) { Result.success("unused") }
        clock.now = 60_017L
        cache.getOrLoad(key) { Result.success("fresh-again") }

        assertEquals(
            listOf(
                QueryCacheDebugEventType.Miss,
                QueryCacheDebugEventType.LoadSucceeded,
                QueryCacheDebugEventType.Hit,
                QueryCacheDebugEventType.Stale,
                QueryCacheDebugEventType.LoadSucceeded,
            ),
            events.map { it.type },
        )
        assertEquals(17L, events[1].loadDurationMillis)
        assertTrue(events.none { it.toString().contains(key.value) })
    }
}
