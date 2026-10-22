package com.ffocalors.sharedledger.data.agent

import io.ktor.client.HttpClient
import io.ktor.client.request.accept
import io.ktor.client.request.header
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.request.url
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.content.TextContent
import io.ktor.http.encodeURLPathPart
import io.ktor.http.takeFrom
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** Outcome of one Agent HTTP call. Transport and contract problems never escape as exceptions. */
sealed interface AgentApiResult<out T> {
    data class Success<T>(val value: T) : AgentApiResult<T>

    sealed interface Failure : AgentApiResult<Nothing>

    /** A well-formed [ApiErrorResponse] (or a client-side equivalent, with [httpStatus] null). */
    data class ApiError(
        val code: AgentErrorCode,
        val message: String,
        val retryable: Boolean,
        val httpStatus: Int?,
    ) : Failure

    data class NetworkFailure(val cause: Throwable) : Failure

    /** The server answered, but not with what the v1 contract allows. */
    data class ContractViolation(val detail: String) : Failure
}

/**
 * Confirm answers with one of two contract-legal bodies: 202 (an execution was dispatched) or 501
 * (execution is unavailable; the rollback mode of the frozen contract).
 */
sealed interface ConfirmProposalOutcome {
    data class ExecutionAccepted(val value: ProposalExecutionAccepted) : ConfirmProposalOutcome
    data class Unavailable(val value: ConfirmationUnavailableResponse) : ConfirmProposalOutcome
}

/**
 * Thin Ktor wrapper over the v1.0.0 Agent HTTP contract: one suspend function per endpoint.
 *
 * Every mutating call takes a caller-supplied `client_request_id` inside its request object; a retry
 * of the same logical action must reuse the same request object (and therefore the same id).
 */
class AgentApiClient(
    baseUrl: String,
    private val tokenProvider: suspend () -> String?,
    private val http: HttpClient,
    private val json: Json = AgentJson,
) {
    private val root = baseUrl.trim().trimEnd('/')

    suspend fun listSessions(cursor: String? = null, limit: Int? = null): AgentApiResult<ListSessionsResponse> =
        request(
            HttpMethod.Get,
            "/v1/sessions",
            query = listOfNotNull(
                cursor?.let { "cursor" to it },
                limit?.let { "limit" to it.toString() },
            ),
            responseSerializer = ListSessionsResponse.serializer(),
        )

    suspend fun createSession(body: CreateSessionRequest): AgentApiResult<CreateSessionResponse> =
        request(
            HttpMethod.Post,
            "/v1/sessions",
            body = json.encodeToString(CreateSessionRequest.serializer(), body),
            responseSerializer = CreateSessionResponse.serializer(),
        )

    suspend fun getSession(sessionId: String): AgentApiResult<SessionDetailResponse> =
        request(
            HttpMethod.Get,
            "/v1/sessions/${sessionId.encodeURLPathPart()}",
            responseSerializer = SessionDetailResponse.serializer(),
        )

    suspend fun submitTurn(sessionId: String, body: SubmitTurnRequest): AgentApiResult<SubmitTurnAccepted> =
        request(
            HttpMethod.Post,
            "/v1/sessions/${sessionId.encodeURLPathPart()}/turns",
            body = json.encodeToString(SubmitTurnRequest.serializer(), body),
            responseSerializer = SubmitTurnAccepted.serializer(),
        )

    suspend fun pollEvents(
        turnId: String,
        afterSeq: Int = 0,
        limit: Int? = null,
    ): AgentApiResult<PollEventsResponse> =
        request(
            HttpMethod.Get,
            "/v1/turns/${turnId.encodeURLPathPart()}/events",
            query = listOfNotNull(
                "after_seq" to afterSeq.toString(),
                limit?.let { "limit" to it.toString() },
            ),
            responseSerializer = PollEventsResponse.serializer(),
        )

    suspend fun cancelTurn(turnId: String, body: CancelTurnRequest): AgentApiResult<CancelTurnResponse> =
        request(
            HttpMethod.Post,
            "/v1/turns/${turnId.encodeURLPathPart()}/cancel",
            body = json.encodeToString(CancelTurnRequest.serializer(), body),
            responseSerializer = CancelTurnResponse.serializer(),
        )

    suspend fun resumeAuth(turnId: String, body: ResumeAuthRequest): AgentApiResult<TurnMutationAccepted> =
        request(
            HttpMethod.Post,
            "/v1/turns/${turnId.encodeURLPathPart()}/resume/auth",
            body = json.encodeToString(ResumeAuthRequest.serializer(), body),
            responseSerializer = TurnMutationAccepted.serializer(),
        )

    suspend fun resumeClarification(
        turnId: String,
        body: ResumeClarificationRequest,
    ): AgentApiResult<TurnMutationAccepted> =
        request(
            HttpMethod.Post,
            "/v1/turns/${turnId.encodeURLPathPart()}/resume/clarification",
            body = json.encodeToString(ResumeClarificationRequest.serializer(), body),
            responseSerializer = TurnMutationAccepted.serializer(),
        )

    suspend fun resumeProposalAdjust(
        turnId: String,
        body: ResumeProposalAdjustRequest,
    ): AgentApiResult<ProposalAdjustedAccepted> =
        request(
            HttpMethod.Post,
            "/v1/turns/${turnId.encodeURLPathPart()}/resume/proposal-adjust",
            body = json.encodeToString(ResumeProposalAdjustRequest.serializer(), body),
            responseSerializer = ProposalAdjustedAccepted.serializer(),
        )

    /**
     * In v1 the server answers 501 [ConfirmationUnavailableResponse] and never 2xx. The 501 body is
     * returned as [AgentApiResult.Success] (a typed "confirmation unavailable" outcome); any 2xx is a
     * [AgentApiResult.ContractViolation] because it would imply a business write the contract forbids.
     */
    suspend fun confirmProposal(
        proposalId: String,
        body: ConfirmProposalRequest,
    ): AgentApiResult<ConfirmProposalOutcome> {
        val raw = send(
            HttpMethod.Post,
            "/v1/proposals/${proposalId.encodeURLPathPart()}/confirm",
            body = json.encodeToString(ConfirmProposalRequest.serializer(), body),
        )
        return when (raw) {
            is RawOutcome.Failed -> raw.failure
            is RawOutcome.Received -> when (raw.status) {
                202 -> ifDecoded(raw.text, ProposalExecutionAccepted.serializer()) {
                    ConfirmProposalOutcome.ExecutionAccepted(it)
                }
                501 -> ifDecoded(raw.text, ConfirmationUnavailableResponse.serializer()) {
                    ConfirmProposalOutcome.Unavailable(it)
                }
                in 200..299 -> AgentApiResult.ContractViolation(
                    "confirm returned HTTP ${raw.status}; v1 allows only 202 or 501",
                )
                else -> raw.toApiError()
            }
        }
    }

    // -----------------------------------------------------------------------------------------

    private sealed interface RawOutcome {
        data class Received(val status: Int, val text: String) : RawOutcome
        data class Failed(val failure: AgentApiResult.Failure) : RawOutcome
    }

    private suspend fun <T> request(
        method: HttpMethod,
        path: String,
        responseSerializer: KSerializer<T>,
        query: List<Pair<String, String>> = emptyList(),
        body: String? = null,
    ): AgentApiResult<T> = when (val raw = send(method, path, query, body)) {
        is RawOutcome.Failed -> raw.failure
        is RawOutcome.Received ->
            if (raw.status in 200..299) decode(raw.text, responseSerializer) else raw.toApiError()
    }

    private suspend fun send(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>> = emptyList(),
        body: String? = null,
    ): RawOutcome {
        val token = try {
            tokenProvider()
        } catch (cancel: CancellationException) {
            throw cancel
        } catch (error: Exception) {
            return RawOutcome.Failed(AgentApiResult.NetworkFailure(error))
        }
        if (token.isNullOrBlank()) {
            return RawOutcome.Failed(
                AgentApiResult.ApiError(
                    code = AgentErrorCode.UNAUTHENTICATED,
                    message = "missing access token",
                    retryable = false,
                    httpStatus = null,
                ),
            )
        }
        return try {
            val response = http.request {
                this.method = method
                url {
                    // Assign via the string overload so the configured base path is preserved.
                    takeFrom("$root$path")
                    query.forEach { (name, value) -> parameters.append(name, value) }
                }
                header(HttpHeaders.Authorization, "Bearer $token")
                accept(ContentType.Application.Json)
                if (body != null) setBody(TextContent(body, ContentType.Application.Json))
            }
            RawOutcome.Received(response.status.value, response.bodyAsText())
        } catch (cancel: CancellationException) {
            throw cancel
        } catch (error: Exception) {
            RawOutcome.Failed(AgentApiResult.NetworkFailure(error))
        }
    }

    private fun <T> decode(text: String, serializer: KSerializer<T>): AgentApiResult<T> = try {
        AgentApiResult.Success(json.decodeFromString(serializer, text))
    } catch (error: SerializationException) {
        AgentApiResult.ContractViolation("cannot decode ${serializer.descriptor.serialName}: ${error.message}")
    } catch (error: IllegalArgumentException) {
        AgentApiResult.ContractViolation("cannot decode ${serializer.descriptor.serialName}: ${error.message}")
    }

    private fun <T, R> ifDecoded(
        text: String,
        serializer: KSerializer<T>,
        wrap: (T) -> R,
    ): AgentApiResult<R> = when (val decoded = decode(text, serializer)) {
        is AgentApiResult.Success -> AgentApiResult.Success(wrap(decoded.value))
        is AgentApiResult.Failure -> decoded
    }

    private fun RawOutcome.Received.toApiError(): AgentApiResult.Failure {
        val parsed = try {
            json.decodeFromString(ApiErrorResponse.serializer(), text)
        } catch (_: SerializationException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
        if (parsed != null) {
            return AgentApiResult.ApiError(parsed.code, parsed.message, parsed.retryable, status)
        }
        // Gateways and proxies answer 5xx with their own bodies; that is an outage, not a contract break.
        return if (status in 500..599) {
            AgentApiResult.ApiError(
                code = AgentErrorCode.DEPENDENCY_UNAVAILABLE,
                message = "HTTP $status",
                retryable = true,
                httpStatus = status,
            )
        } else {
            AgentApiResult.ContractViolation("HTTP $status without an ApiErrorResponse body")
        }
    }
}
