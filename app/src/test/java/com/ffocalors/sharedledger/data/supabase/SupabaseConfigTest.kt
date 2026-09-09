package com.ffocalors.sharedledger.data.supabase

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Before
import org.junit.Test
import io.github.jan.supabase.SupabaseClient
import java.lang.reflect.Proxy
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class SupabaseConfigTest {
    private val fakeClient = Proxy.newProxyInstance(
        SupabaseClient::class.java.classLoader,
        arrayOf(SupabaseClient::class.java),
    ) { _, _, _ -> null } as SupabaseClient

    @Before
    fun useFakeClientFactory() {
        SupabaseClientProvider.setClientFactoryForTests { fakeClient }
    }

    @After
    fun resetProvider() {
        SupabaseClientProvider.resetForTests()
    }

    @Test
    fun rejectsMissingOrPrivilegedKeys() {
        assertFalse(SupabaseConfig("", "").isUsable)
        assertFalse(SupabaseConfig("https://demo.supabase.co", "sb_secret_do_not_use").isUsable)
        assertFalse(SupabaseConfig("https://demo.supabase.co", "service_role_do_not_use").isUsable)
    }

    @Test
    fun acceptsHttpsPublishableConfiguration() {
        assertTrue(SupabaseConfig("https://demo.supabase.co", "sb_publishable_demo").isUsable)
    }

    @Test
    fun acceptsOnlyExplicitLocalHttpHostsInDebugConfiguration() {
        assertTrue(
            SupabaseConfig(
                "http://10.0.2.2:54321",
                "sb_publishable_demo",
                allowLocalHttp = true,
            ).isUsable,
        )
        assertFalse(
            SupabaseConfig(
                "http://example.com:54321",
                "sb_publishable_demo",
                allowLocalHttp = true,
            ).isUsable,
        )
        assertFalse(SupabaseConfig("http://127.0.0.1:54321", "sb_publishable_demo").isUsable)
    }

    @Test
    fun reusesClientForTheSameConfiguration() {
        val config = SupabaseConfig("https://demo.supabase.co", "sb_publishable_demo")

        val first = SupabaseClientProvider.createOrNull(config)
        val second = SupabaseClientProvider.createOrNull(config)

        assertSame(first, second)
    }

    @Test
    fun invalidConfigurationDoesNotExposeOrReplaceCachedClient() {
        val validConfig = SupabaseConfig("https://demo.supabase.co", "sb_publishable_demo")
        val validClient = SupabaseClientProvider.createOrNull(validConfig)

        assertNull(
            SupabaseClientProvider.createOrNull(
                SupabaseConfig("", "sb_publishable_demo"),
            ),
        )
        assertSame(validClient, SupabaseClientProvider.createOrNull(validConfig))
    }

    @Test
    fun concurrentCreationSharesOneClient() {
        val config = SupabaseConfig("https://demo.supabase.co", "sb_publishable_demo")
        val executor = Executors.newFixedThreadPool(8)
        try {
            val futures = List(16) {
                executor.submit { SupabaseClientProvider.createOrNull(config) }
            }
            executor.shutdown()
            check(executor.awaitTermination(10, TimeUnit.SECONDS))

            val clients = futures.map { it.get() }
            clients.drop(1).forEach { client -> assertSame(clients.first(), client) }
        } finally {
            executor.shutdownNow()
        }
    }
}
