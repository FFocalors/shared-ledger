package com.ffocalors.sharedledger.data.supabase

import com.ffocalors.sharedledger.BuildConfig
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.postgrest.Postgrest
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
    fun config(): SupabaseConfig = SupabaseConfig(
        url = BuildConfig.SUPABASE_URL.trim(),
        publishableKey = BuildConfig.SUPABASE_PUBLISHABLE_KEY.trim(),
        allowLocalHttp = BuildConfig.DEBUG,
    )

    fun createOrNull(config: SupabaseConfig = config()): SupabaseClient? {
        if (!config.isUsable) return null
        return createSupabaseClient(
            supabaseUrl = config.url,
            supabaseKey = config.publishableKey,
        ) {
            install(Auth)
            install(Postgrest)
        }
    }
}
