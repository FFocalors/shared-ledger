package com.ffocalors.sharedledger.data.agent

import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.REQUEST_ID
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.SESSION_ID
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.TURN_ID
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import java.io.IOException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentApiClientTest {
    private val requests = mutableListOf<HttpRequestData>()

    private fun client(
        token: String? = "tok-123",
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): AgentApiClient {
        val engine = MockEngine { request ->
            requests += request
            handler(request)
        }
        return AgentApiClient("http://10.0.2.2:8000/", { token }, HttpClient(engine))
    }

    private fun MockRequestHandleScope.json(status: HttpStatusCode, body: String) = respond(
        content = body,
        status = status,
        headers = headersOf(HttpHeaders.ContentType, "application/json"),
    )

    private val acceptedBody =
        """{"accepted_at":"2026-10-07T00:00:00Z","api_version":"1.0.0","state":"QUEUED","state_revision":1,"turn_id":"$TURN_ID"}"""

    private fun confirmRequest() = ConfirmProposalRequest(REQUEST_ID, "a".repeat(64), "N".repeat(32), 1)

    @Test
    fun sendsBearerTokenJsonBodyAndDecodes202() = runBlocking {
        val api = client { json(HttpStatusCode.Accepted, acceptedBody) }
        val result = api.submitTurn(SESSION_ID, SubmitTurnRequest(REQUEST_ID, "你好"))

        val success = result as AgentApiResult.Success
        assertEquals(TURN_ID, success.value.turnId)
        assertEquals(TurnState.QUEUED, success.value.state)

        val sent = requests.single()
        assertEquals("Bearer tok-123", sent.headers[HttpHeaders.Authorization])
        assertEquals(HttpMethod.Post, sent.method)
        assertEquals("http://10.0.2.2:8000/v1/sessions/$SESSION_ID/turns", sent.url.toString())
        val body = (sent.body as TextContent).text
        assertTrue(body.contains("\"client_request_id\":\"$REQUEST_ID\""))
        assertTrue(body.contains("\"text\":\"你好\""))
    }

    @Test
    fun getEndpointsBuildQueryStrings() = runBlocking {
        val api = client { request ->
            if (request.url.encodedPath.endsWith("/events")) {
                json(
                    HttpStatusCode.OK,
                    """{"after_seq":2,"events":[],"has_more":false,"next_after_seq":2,"proposal_cards":[],"turn":${AgentTestFixtures.turnJson}}""",
                )
            } else {
                json(HttpStatusCode.OK, """{"api_version":"1.0.0","items":[],"next_cursor":null}""")
            }
        }
        assertTrue(api.listSessions(cursor = "c 1", limit = 20) is AgentApiResult.Success)
        assertTrue(api.pollEvents(TURN_ID, afterSeq = 2, limit = 50) is AgentApiResult.Success)

        val list = requests[0]
        assertEquals(HttpMethod.Get, list.method)
        assertEquals("/v1/sessions", list.url.encodedPath)
        assertEquals("c 1", list.url.parameters["cursor"])
        assertEquals("20", list.url.parameters["limit"])
        val poll = requests[1]
        assertEquals("/v1/turns/$TURN_ID/events", poll.url.encodedPath)
        assertEquals("2", poll.url.parameters["after_seq"])
        assertEquals("50", poll.url.parameters["limit"])
    }

    @Test
    fun decodes409AsApiError() = runBlocking {
        val api = client {
            json(
                HttpStatusCode.Conflict,
                """{"api_version":"1.0.0","code":"state_revision_conflict","message":"状态已变化","retryable":false}""",
            )
        }
        val result = api.cancelTurn(TURN_ID, CancelTurnRequest(REQUEST_ID, 1))
        val error = result as AgentApiResult.ApiError
        assertEquals(AgentErrorCode.STATE_REVISION_CONFLICT, error.code)
        assertEquals("状态已变化", error.message)
        assertFalse(error.retryable)
        assertEquals(409, error.httpStatus)
        assertEquals("状态已变化", AgentErrorMessages.forFailure(error))
    }

    @Test
    fun confirm501IsTypedUnavailableResult() = runBlocking {
        val api = client {
            json(
                HttpStatusCode.NotImplemented,
                """{"api_version":"1.0.0","business_write_performed":false,"code":"execution_capability_unavailable","execution_enabled":false,"message":"not enabled"}""",
            )
        }
        val result = api.confirmProposal(AgentTestFixtures.PROPOSAL_ID, confirmRequest())
        val value = (result as AgentApiResult.Success).value as ConfirmProposalOutcome.Unavailable
        assertEquals(AgentErrorCode.EXECUTION_CAPABILITY_UNAVAILABLE, value.value.code)
        assertFalse(value.value.businessWritePerformed)
        assertFalse(value.value.executionEnabled)
        assertEquals("/v1/proposals/${AgentTestFixtures.PROPOSAL_ID}/confirm", requests.single().url.encodedPath)
    }

    @Test
    fun confirm202DecodesTheDispatchedExecution() = runBlocking {
        val api = client {
            json(
                HttpStatusCode.Accepted,
                """
                {"api_version":"1.0.0","event_cursor":7,
                 "execution":{"execution_id":"e1","proposal_id":"p1","proposal_revision":2,"operations_version":"1.0.0"},
                 "turn":{"turn_id":"t1","session_id":"s1","state":"EXECUTING","state_revision":4,
                         "step":"dispatch","context_version":1,"execution_assigned":true}}
                """.trimIndent(),
            )
        }
        val result = api.confirmProposal("p1", confirmRequest())
        val accepted = (result as AgentApiResult.Success).value as ConfirmProposalOutcome.ExecutionAccepted
        assertEquals(7, accepted.value.eventCursor)
        assertEquals("e1", accepted.value.execution.executionId)
        assertEquals(2, accepted.value.execution.proposalRevision)
        assertEquals(TurnState.EXECUTING, accepted.value.turn.state)
        assertTrue(accepted.value.turn.executionAssigned)
    }

    @Test
    fun confirmWithOther2xxIsContractViolation() = runBlocking {
        val api = client { json(HttpStatusCode.OK, """{"anything":true}""") }
        assertTrue(api.confirmProposal("p", confirmRequest()) is AgentApiResult.ContractViolation)
    }

    @Test
    fun confirmOtherErrorsStayApiErrors() = runBlocking {
        val api = client {
            json(HttpStatusCode.Forbidden, """{"code":"forbidden","message":"no","retryable":false}""")
        }
        val result = api.confirmProposal("p", confirmRequest())
        assertEquals(AgentErrorCode.FORBIDDEN, (result as AgentApiResult.ApiError).code)
    }

    @Test
    fun missingTokenMakesNoRequest() = runBlocking {
        for (token in listOf(null, "", "  ")) {
            val api = client(token = token) { json(HttpStatusCode.OK, "{}") }
            val error = api.getSession(SESSION_ID) as AgentApiResult.ApiError
            assertEquals(AgentErrorCode.UNAUTHENTICATED, error.code)
            assertNull(error.httpStatus)
            assertEquals(AgentErrorMessages.UNAUTHENTICATED, AgentErrorMessages.forFailure(error))
        }
        assertTrue(requests.isEmpty())
    }

    @Test
    fun ioExceptionBecomesNetworkFailure() = runBlocking {
        val api = client { throw IOException("offline") }
        val failure = api.listSessions() as AgentApiResult.NetworkFailure
        assertEquals("offline", failure.cause.message)
        assertEquals(AgentErrorMessages.NETWORK_FAILURE, AgentErrorMessages.forFailure(failure))
    }

    @Test
    fun malformedSuccessBodyIsContractViolation() = runBlocking {
        val bad = client { json(HttpStatusCode.Accepted, """{"turn_id":"x"}""") }
            .submitTurn(SESSION_ID, SubmitTurnRequest(REQUEST_ID, "x"))
        assertTrue(bad is AgentApiResult.ContractViolation)

        val notJson = client { json(HttpStatusCode.OK, "<html>proxy</html>") }.listSessions()
        assertTrue(notJson is AgentApiResult.ContractViolation)
        assertEquals(
            AgentErrorMessages.CONTRACT_VIOLATION,
            AgentErrorMessages.forFailure(notJson as AgentApiResult.ContractViolation),
        )
    }

    @Test
    fun gatewayErrorWithForeignBodyIsRetryableDependencyError() = runBlocking {
        val error = client { json(HttpStatusCode.BadGateway, "<html>bad gateway</html>") }
            .listSessions() as AgentApiResult.ApiError
        assertEquals(AgentErrorCode.DEPENDENCY_UNAVAILABLE, error.code)
        assertTrue(error.retryable)
        assertEquals(502, error.httpStatus)

        val client4xx = client { json(HttpStatusCode.NotFound, "nope") }.listSessions()
        assertTrue(client4xx is AgentApiResult.ContractViolation)
    }

    @Test
    fun resumeAndCreateEndpointsUseTheirPaths() = runBlocking {
        val mutation =
            """{"api_version":"1.0.0","event_cursor":3,"state":"RUNNING","state_revision":2,"turn_id":"$TURN_ID"}"""
        val api = client { request ->
            when {
                request.url.encodedPath == "/v1/sessions" -> json(
                    HttpStatusCode.Created,
                    """{"api_version":"1.0.0","session":{"active_turn_count":0,"created_at":"a","session_id":"$SESSION_ID","updated_at":"b"}}""",
                )
                request.url.encodedPath.endsWith("proposal-adjust") -> json(
                    HttpStatusCode.Accepted,
                    """{"api_version":"1.0.0","event_cursor":4,"proposal_id":"p","proposal_revision":2,"state":"WAIT_CONFIRM","state_revision":3,"turn_id":"$TURN_ID"}""",
                )
                else -> json(HttpStatusCode.Accepted, mutation)
            }
        }
        val created = api.createSession(CreateSessionRequest(REQUEST_ID)) as AgentApiResult.Success
        assertEquals(SESSION_ID, created.value.session.sessionId)
        val clarified = api.resumeClarification(TURN_ID, ResumeClarificationRequest(REQUEST_ID, 1, "t"))
        assertEquals(3, (clarified as AgentApiResult.Success).value.eventCursor)
        assertTrue(api.resumeAuth(TURN_ID, ResumeAuthRequest(REQUEST_ID, 1)) is AgentApiResult.Success)
        val adjusted = api.resumeProposalAdjust(TURN_ID, ResumeProposalAdjustRequest(REQUEST_ID, 1, 2, "t"))
        assertEquals(2, (adjusted as AgentApiResult.Success).value.proposalRevision)
        assertEquals(
            listOf(
                "/v1/sessions",
                "/v1/turns/$TURN_ID/resume/clarification",
                "/v1/turns/$TURN_ID/resume/auth",
                "/v1/turns/$TURN_ID/resume/proposal-adjust",
            ),
            requests.map { it.url.encodedPath },
        )
    }
}
