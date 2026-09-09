package com.ffocalors.sharedledger.data.supabase

import com.ffocalors.sharedledger.BuildConfig
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.postgrest.Postgrest
import io.github.jan.supabase.realtime.Realtime
import io.github.jan.supabase.storage.Storage
import java.net.URI

data class SupabaseConfig(
    val url: String,
    val publishableKey: String,
    val allowLocalHttp: Boolean = false,
) {
    val isUsable: Boolean
        get() = hasAllowedUrl() && publishableKey.isNotBlank() &&
            !publishableKey.contains("service_role", ignoreCase = true) &&
            !publishableKey.contains("sb_secret_", ignoreCase = true)

    private fun hasAllowedUrl(): Boolean = runCatching {
        val uri = URI(url)
        when (uri.scheme?.lowercase()) {
            "https" -> !uri.host.isNullOrBlank()
            "http" -> allowLocalHttp && uri.host in LOCAL_DEVELOPMENT_HOSTS
            else -> false
        }
    }.getOrDefault(false)

    private companion object {
        val LOCAL_DEVELOPMENT_HOSTS = setOf("10.0.2.2", "127.0.0.1", "localhost")
    }
}

object SupabaseClientProvider {
    private data class ClientCacheEntry(
        val config: SupabaseConfig,
        val client: SupabaseClient,
    )

    private var cachedClient: ClientCacheEntry? = null
    private var clientFactoryForTests: ((SupabaseConfig) -> SupabaseClient)? = null

    fun config(): SupabaseConfig = SupabaseConfig(
        url = BuildConfig.SUPABASE_URL.trim(),
        publishableKey = BuildConfig.SUPABASE_PUBLISHABLE_KEY.trim(),
        allowLocalHttp = BuildConfig.DEBUG,
    )

    @Synchronized
    fun createOrNull(config: SupabaseConfig = config()): SupabaseClient? {
        val normalizedConfig = config.copy(
            url = config.url.trim(),
            publishableKey = config.publishableKey.trim(),
        )
        if (!normalizedConfig.isUsable) return null

        cachedClient?.takeIf { it.config == normalizedConfig }?.let { entry ->
            return entry.client
        }

        val client = (clientFactoryForTests ?: ::createClient)(normalizedConfig)
        cachedClient = ClientCacheEntry(normalizedConfig, client)
        return client
    }

    private fun createClient(config: SupabaseConfig): SupabaseClient = createSupabaseClient(
        supabaseUrl = config.url,
        supabaseKey = config.publishableKey,
    ) {
        install(Auth) {
            // Must match the Android intent filter used by Supabase recovery links.
            scheme = "sharedledger"
            host = "auth"
        }
        install(Postgrest)
        install(Storage)
        install(Realtime)
    }

    /** Installs a deterministic client factory for JVM tests; app callers should not use this. */
    internal fun setClientFactoryForTests(factory: ((SupabaseConfig) -> SupabaseClient)?) {
        synchronized(this) {
            cachedClient = null
            clientFactoryForTests = factory
        }
    }

    /** Clears process-level state between tests without exposing reset semantics to app callers. */
    internal fun resetForTests() {
        synchronized(this) {
            cachedClient = null
            clientFactoryForTests = null
        }
    }
}
