package com.ffocalors.sharedledger.data.agent

import com.ffocalors.sharedledger.BuildConfig

/** Debug implementation: returns one shared in-memory fake when `agent.demo=true`. */
object DemoAgentRepositoryProvider {
    private val shared: AgentRepository by lazy { DemoAgentRepository() }

    fun createOrNull(): AgentRepository? = if (BuildConfig.AGENT_DEMO) shared else null
}
