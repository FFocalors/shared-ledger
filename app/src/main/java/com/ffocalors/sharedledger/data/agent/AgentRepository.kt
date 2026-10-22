package com.ffocalors.sharedledger.data.agent

import com.ffocalors.sharedledger.BuildConfig
import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.auth.auth
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout

/**
 * Data-layer entry point for the Agent service. Every mutating call takes a request object that
 * already carries its `client_request_id`; callers reuse the same object to retry the same action.
 */
interface AgentRepository {
    suspend fun listSessions(cursor: String? = null, limit: Int? = null): AgentApiResult<ListSessionsResponse>
    suspend fun createSession(request: CreateSessionRequest): AgentApiResult<CreateSessionResponse>
    suspend fun getSession(sessionId: String): AgentApiResult<SessionDetailResponse>
    suspend fun submitTurn(sessionId: String, request: SubmitTurnRequest): AgentApiResult<SubmitTurnAccepted>
    suspend fun pollEvents(turnId: String, afterSeq: Int = 0, limit: Int? = null): AgentApiResult<PollEventsResponse>
    suspend fun cancelTurn(turnId: String, request: CancelTurnRequest): AgentApiResult<CancelTurnResponse>
    suspend fun resumeAuth(turnId: String, request: ResumeAuthRequest): AgentApiResult<TurnMutationAccepted>
    suspend fun resumeClarification(
        turnId: String,
        request: ResumeClarificationRequest,
    ): AgentApiResult<TurnMutationAccepted>

    suspend fun resumeProposalAdjust(
        turnId: String,
        request: ResumeProposalAdjustRequest,
    ): AgentApiResult<ProposalAdjustedAccepted>

    /** v1: Success carries the 501 "confirmation unavailable" body; there is no real success. */
    suspend fun confirmProposal(
        proposalId: String,
        request: ConfirmProposalRequest,
    ): AgentApiResult<ConfirmationUnavailableResponse>
}

class DefaultAgentRepository(private val client: AgentApiClient) : AgentRepository {
    override suspend fun listSessions(cursor: String?, limit: Int?) = client.listSessions(cursor, limit)
    override suspend fun createSession(request: CreateSessionRequest) = client.createSession(request)
    override suspend fun getSession(sessionId: String) = client.getSession(sessionId)
    override suspend fun submitTurn(sessionId: String, request: SubmitTurnRequest) =
        client.submitTurn(sessionId, request)

    override suspend fun pollEvents(turnId: String, afterSeq: Int, limit: Int?) =
        client.pollEvents(turnId, afterSeq, limit)

    override suspend fun cancelTurn(turnId: String, request: CancelTurnRequest) = client.cancelTurn(turnId, request)
    override suspend fun resumeAuth(turnId: String, request: ResumeAuthRequest) = client.resumeAuth(turnId, request)
    override suspend fun resumeClarification(turnId: String, request: ResumeClarificationRequest) =
        client.resumeClarification(turnId, request)

    override suspend fun resumeProposalAdjust(turnId: String, request: ResumeProposalAdjustRequest) =
        client.resumeProposalAdjust(turnId, request)

    override suspend fun confirmProposal(proposalId: String, request: ConfirmProposalRequest) =
        client.confirmProposal(proposalId, request)
}

/** Used when no Agent endpoint is configured: every call fails fast as "agent disabled". */
class UnavailableAgentRepository : AgentRepository {
    private fun <T> unavailable(): AgentApiResult<T> = AgentApiResult.ApiError(
        code = AgentErrorCode.AGENT_DISABLED,
        message = "agent base url is not configured",
        retryable = false,
        httpStatus = null,
    )

    override suspend fun listSessions(cursor: String?, limit: Int?) = unavailable<ListSessionsResponse>()
    override suspend fun createSession(request: CreateSessionRequest) = unavailable<CreateSessionResponse>()
    override suspend fun getSession(sessionId: String) = unavailable<SessionDetailResponse>()
    override suspend fun submitTurn(sessionId: String, request: SubmitTurnRequest) = unavailable<SubmitTurnAccepted>()
    override suspend fun pollEvents(turnId: String, afterSeq: Int, limit: Int?) = unavailable<PollEventsResponse>()
    override suspend fun cancelTurn(turnId: String, request: CancelTurnRequest) = unavailable<CancelTurnResponse>()
    override suspend fun resumeAuth(turnId: String, request: ResumeAuthRequest) = unavailable<TurnMutationAccepted>()
    override suspend fun resumeClarification(turnId: String, request: ResumeClarificationRequest) =
        unavailable<TurnMutationAccepted>()

    override suspend fun resumeProposalAdjust(turnId: String, request: ResumeProposalAdjustRequest) =
        unavailable<ProposalAdjustedAccepted>()

    override suspend fun confirmProposal(proposalId: String, request: ConfirmProposalRequest) =
        unavailable<ConfirmationUnavailableResponse>()
}

object AgentRepositoryFactory {
    private val sharedHttpClient: HttpClient by lazy {
        HttpClient(OkHttp) {
            install(HttpTimeout) {
                connectTimeoutMillis = 10_000
                socketTimeoutMillis = 30_000
                requestTimeoutMillis = 30_000
            }
        }
    }

    fun create(config: AgentConfig = AgentConfig.fromBuildConfig()): AgentRepository {
        if (BuildConfig.AGENT_DEMO) DemoAgentRepositoryProvider.createOrNull()?.let { return it }
        if (!config.isConfigured) return UnavailableAgentRepository()
        return DefaultAgentRepository(
            AgentApiClient(
                baseUrl = config.normalizedBaseUrl,
                tokenProvider = ::supabaseAccessToken,
                http = sharedHttpClient,
            ),
        )
    }

    private suspend fun supabaseAccessToken(): String? =
        SupabaseClientProvider.createOrNull()?.auth?.currentSessionOrNull()?.accessToken
}
