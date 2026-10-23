package com.ffocalors.sharedledger.data.agent

import com.ffocalors.sharedledger.BuildConfig
import java.net.URI

/**
 * Agent service endpoint. Mirrors the Supabase URL rule: https always; http only for local
 * development hosts and only when [allowLocalHttp] (debug builds).
 */
data class AgentConfig(
    val baseUrl: String,
    val allowLocalHttp: Boolean = false,
) {
    /** True only for a non-blank, allowed URL; a blank or disallowed URL means "agent not available". */
    val isConfigured: Boolean
        get() = baseUrl.isNotBlank() && hasAllowedUrl()

    val normalizedBaseUrl: String get() = baseUrl.trim().trimEnd('/')

    private fun hasAllowedUrl(): Boolean = runCatching {
        val uri = URI(baseUrl.trim())
        when (uri.scheme?.lowercase()) {
            "https" -> !uri.host.isNullOrBlank()
            "http" -> allowLocalHttp && (uri.host in LOCAL_DEVELOPMENT_HOSTS || isPrivateIpv4(uri.host))
            else -> false
        }
    }.getOrDefault(false)

    companion object {
        private fun isPrivateIpv4(host: String?): Boolean {
            val parts = host?.split('.') ?: return false
            if (parts.size != 4 || parts.any { !it.matches(Regex("0|[1-9][0-9]{0,2}")) }) return false
            val octets = parts.map { it.toInt() }
            if (octets.any { it !in 0..255 }) return false
            return octets[0] == 10 ||
                (octets[0] == 172 && octets[1] in 16..31) ||
                (octets[0] == 192 && octets[1] == 168)
        }
        private val LOCAL_DEVELOPMENT_HOSTS = setOf("10.0.2.2", "127.0.0.1", "localhost")

        /** Offline demo mode (debug builds with `agent.demo=true`). */
        val isDemo: Boolean get() = BuildConfig.AGENT_DEMO

        /** The Agent entry is shown for a configured endpoint or in demo mode. */
        fun agentAvailable(config: AgentConfig = fromBuildConfig()): Boolean = isDemo || config.isConfigured

        fun fromBuildConfig(): AgentConfig = AgentConfig(
            baseUrl = BuildConfig.AGENT_BASE_URL.trim(),
            allowLocalHttp = BuildConfig.DEBUG,
        )
    }
}
