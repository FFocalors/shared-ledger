package com.ffocalors.sharedledger.data.agent

/** Chinese user-facing copy for Agent call failures. */
object AgentErrorMessages {
    const val UNAUTHENTICATED = "登录已过期，请重新登录后再试。"
    const val FORBIDDEN = "你没有这个活动的权限。"
    const val AGENT_DISABLED = "助手已被关闭，可以继续手动记账。"
    const val RATE_LIMITED = "说得太快了，稍等几秒再发。"
    const val DEPENDENCY_UNAVAILABLE = "助手服务暂时连不上，稍后再试；手动记账不受影响。"
    const val NETWORK_FAILURE = "连不上助手服务，检查网络后点重试。"
    const val CONTRACT_VIOLATION = "助手返回了无法识别的内容，请更新 App 后再试。"

    fun forFailure(failure: AgentApiResult.Failure): String = when (failure) {
        is AgentApiResult.ApiError -> forApiError(failure)
        is AgentApiResult.NetworkFailure -> NETWORK_FAILURE
        is AgentApiResult.ContractViolation -> CONTRACT_VIOLATION
    }

    fun forApiError(error: AgentApiResult.ApiError): String = when (error.code) {
        AgentErrorCode.UNAUTHENTICATED -> UNAUTHENTICATED
        AgentErrorCode.FORBIDDEN -> FORBIDDEN
        AgentErrorCode.AGENT_DISABLED -> AGENT_DISABLED
        AgentErrorCode.RATE_LIMITED -> RATE_LIMITED
        AgentErrorCode.DEPENDENCY_UNAVAILABLE -> DEPENDENCY_UNAVAILABLE
        else -> error.message
    }

    /** Same mapping for an error carried inside an `error` event payload. */
    fun forEvent(payload: ErrorEventPayload): String = forApiError(
        AgentApiResult.ApiError(payload.code, payload.message, payload.retryable, httpStatus = null),
    )
}
