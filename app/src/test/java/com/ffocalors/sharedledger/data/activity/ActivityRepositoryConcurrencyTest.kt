package com.ffocalors.sharedledger.data.activity

import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ActivityRepositoryConcurrencyTest {
    @Test
    fun boundedReadsKeepInputOrderAndNeverExceedFourActiveOperations() = runTest {
        val active = AtomicInteger(0)
        val maximumActive = AtomicInteger(0)

        val result = mapConcurrentlyPreservingOrder((0 until 12).toList(), maxConcurrency = 4) { item ->
            val current = active.incrementAndGet()
            maximumActive.updateAndGet { previous -> maxOf(previous, current) }
            try {
                delay(1)
                item * 2
            } finally {
                active.decrementAndGet()
            }
        }

        assertEquals((0 until 12).map { it * 2 }, result)
        assertTrue("active reads: ${maximumActive.get()}", maximumActive.get() <= 4)
    }

    @Test
    fun cancellationIsNotConvertedIntoACompletedRead() = runTest {
        try {
            mapConcurrentlyPreservingOrder(listOf(1, 2, 3), maxConcurrency = 4) {
                throw CancellationException("test cancellation")
            }
            throw AssertionError("expected cancellation")
        } catch (error: CancellationException) {
            assertEquals("test cancellation", error.message)
        }
    }
}
