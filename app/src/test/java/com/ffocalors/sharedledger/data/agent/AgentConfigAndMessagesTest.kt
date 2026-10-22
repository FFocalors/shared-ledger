package com.ffocalors.sharedledger.data.agent

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentConfigAndMessagesTest {
    @Test
    fun blankOrInvalidBaseUrlIsNotConfigured() {
        assertFalse(AgentConfig("").isConfigured)
        assertFalse(AgentConfig("   ", allowLocalHttp = true).isConfigured)
        assertFalse(AgentConfig("not a url").isConfigured)
        assertFalse(AgentConfig("ftp://agent.example.com").isConfigured)
    }

    @Test
    fun httpsIsAlwaysAllowedHttpOnlyForLocalHostsInDebug() {
        assertTrue(AgentConfig("https://agent.example.com").isConfigured)
        assertFalse(AgentConfig("http://agent.example.com", allowLocalHttp = true).isConfigured)
        for (host in listOf("10.0.2.2", "127.0.0.1", "localhost")) {
            assertTrue(AgentConfig("http://$host:8000", allowLocalHttp = true).isConfigured)
            assertFalse(AgentConfig("http://$host:8000", allowLocalHttp = false).isConfigured)
        }
        assertEquals(
            "https://agent.example.com/api",
            AgentConfig(" https://agent.example.com/api/ ").normalizedBaseUrl,
        )
    }

    private fun apiError(code: AgentErrorCode) = AgentApiResult.ApiError(code, "server says", false, 400)

    @Test
    fun mapsFailuresToChineseCopy() {
        assertEquals("登录已过期，请重新登录后再试。", AgentErrorMessages.forFailure(apiError(AgentErrorCode.UNAUTHENTICATED)))
        assertEquals("你没有这个活动的权限。", AgentErrorMessages.forFailure(apiError(AgentErrorCode.FORBIDDEN)))
        assertEquals("助手已被关闭，可以继续手动记账。", AgentErrorMessages.forFailure(apiError(AgentErrorCode.AGENT_DISABLED)))
        assertEquals("说得太快了，稍等几秒再发。", AgentErrorMessages.forFailure(apiError(AgentErrorCode.RATE_LIMITED)))
        assertEquals(
            "助手服务暂时连不上，稍后再试；手动记账不受影响。",
            AgentErrorMessages.forFailure(apiError(AgentErrorCode.DEPENDENCY_UNAVAILABLE)),
        )
        assertEquals(
            "连不上助手服务，检查网络后点重试。",
            AgentErrorMessages.forFailure(AgentApiResult.NetworkFailure(RuntimeException())),
        )
        assertEquals(
            "助手返回了无法识别的内容，请更新 App 后再试。",
            AgentErrorMessages.forFailure(AgentApiResult.ContractViolation("x")),
        )
        for (code in listOf(AgentErrorCode.NOT_FOUND, AgentErrorCode.STATE_REVISION_CONFLICT, AgentErrorCode.UNKNOWN)) {
            assertEquals("server says", AgentErrorMessages.forFailure(apiError(code)))
        }
    }

    @Test
    fun unavailableRepositoryFailsFastAsAgentDisabled() = runBlocking {
        val result = UnavailableAgentRepository().listSessions()
        assertEquals(AgentErrorCode.AGENT_DISABLED, (result as AgentApiResult.ApiError).code)
    }
}
