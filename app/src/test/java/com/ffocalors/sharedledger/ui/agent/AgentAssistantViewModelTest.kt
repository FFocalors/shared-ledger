package com.ffocalors.sharedledger.ui.agent

import com.ffocalors.sharedledger.data.agent.AgentApiResult
import com.ffocalors.sharedledger.data.agent.AgentErrorCode
import com.ffocalors.sharedledger.data.agent.AgentErrorMessages
import com.ffocalors.sharedledger.data.agent.AgentEvent
import com.ffocalors.sharedledger.data.agent.AgentRepository
import com.ffocalors.sharedledger.data.agent.AmountField
import com.ffocalors.sharedledger.data.agent.CanonicalEqualSplit
import com.ffocalors.sharedledger.data.agent.CancelResult
import com.ffocalors.sharedledger.data.agent.CancelTurnRequest
import com.ffocalors.sharedledger.data.agent.CancelTurnResponse
import com.ffocalors.sharedledger.data.agent.ClarificationEvent
import com.ffocalors.sharedledger.data.agent.ClarificationEventPayload
import com.ffocalors.sharedledger.data.agent.ConfirmProposalRequest
import com.ffocalors.sharedledger.data.agent.ConfirmationUnavailableResponse
import com.ffocalors.sharedledger.data.agent.CreateSessionRequest
import com.ffocalors.sharedledger.data.agent.CreateSessionResponse
import com.ffocalors.sharedledger.data.agent.ExpenseAmountChange
import com.ffocalors.sharedledger.data.agent.ExpensePreview
import com.ffocalors.sharedledger.data.agent.ExpenseSnapshot
import com.ffocalors.sharedledger.data.agent.ListSessionsResponse
import com.ffocalors.sharedledger.data.agent.MessageEvent
import com.ffocalors.sharedledger.data.agent.MessageEventPayload
import com.ffocalors.sharedledger.data.agent.MissingSlot
import com.ffocalors.sharedledger.data.agent.PollEventsResponse
import com.ffocalors.sharedledger.data.agent.ProposalCard
import com.ffocalors.sharedledger.data.agent.ProposalEvent
import com.ffocalors.sharedledger.data.agent.ProposalEventPayload
import com.ffocalors.sharedledger.data.agent.ProposalOperation
import com.ffocalors.sharedledger.data.agent.ProposalAdjustedAccepted
import com.ffocalors.sharedledger.data.agent.ResumeAuthRequest
import com.ffocalors.sharedledger.data.agent.ResumeClarificationRequest
import com.ffocalors.sharedledger.data.agent.ResumeProposalAdjustRequest
import com.ffocalors.sharedledger.data.agent.SessionDetailResponse
import com.ffocalors.sharedledger.data.agent.SessionSummary
import com.ffocalors.sharedledger.data.agent.SimulationProposalCard
import com.ffocalors.sharedledger.data.agent.SubmitTurnAccepted
import com.ffocalors.sharedledger.data.agent.SubmitTurnRequest
import com.ffocalors.sharedledger.data.agent.TurnMutationAccepted
import com.ffocalors.sharedledger.data.agent.TurnPublicStatus
import com.ffocalors.sharedledger.data.agent.TurnState
import com.ffocalors.sharedledger.data.agent.TurnStep
import com.ffocalors.sharedledger.data.agent.TurnSummary
import com.ffocalors.sharedledger.data.agent.WaitReason
import java.io.IOException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

// ---- fakes & builders ---------------------------------------------------------------------------

private fun status(
    state: TurnState,
    step: TurnStep = TurnStep.TOOL_READ,
    revision: Int = 1,
    waitReason: WaitReason? = null,
    turnId: String = "t1",
) = TurnPublicStatus(
    turnId = turnId,
    sessionId = "s1",
    state = state,
    stateRevision = revision,
    step = step,
    contextVersion = 1,
    executionAssigned = false,
    waitReason = waitReason,
)

private fun message(seq: Int, text: String = "m$seq"): AgentEvent =
    MessageEvent(seq, "2026-10-22T08:00:00Z", false, MessageEventPayload(text))

private fun poll(
    after: Int,
    next: Int,
    turn: TurnPublicStatus,
    events: List<AgentEvent> = emptyList(),
    hasMore: Boolean = false,
    cards: List<ProposalCard> = emptyList(),
) = PollEventsResponse(after, next, hasMore, turn, events, cards)

private fun card(id: String = "pr1", revision: Int = 1): ProposalCard = SimulationProposalCard(
    proposalId = id,
    revision = revision,
    operation = ProposalOperation.EXPENSE_CREATE,
    preview = ExpensePreview(
        activityFinancialVersion = "1",
        after = ExpenseSnapshot(
            baseAmount = "10.00",
            expenseVersion = "1",
            financialLocked = false,
            ledgerUnitId = "lu",
            originalAmount = "10.00",
            originalCurrency = "CNY",
            paymentAllocations = emptyList(),
            split = CanonicalEqualSplit(listOf("a")),
            title = "t$revision",
        ),
        changes = listOf(ExpenseAmountChange(AmountField.ORIGINAL_AMOUNT, "10.00")),
        generatedAt = "2026-10-22T08:00:00Z",
        simulation = true,
        summary = "s",
    ),
)

private class FakeAgentRepository : AgentRepository {
    val createRequests = mutableListOf<CreateSessionRequest>()
    val submitRequests = mutableListOf<SubmitTurnRequest>()
    val pollAfter = mutableListOf<Pair<String, Int>>()
    val authRequests = mutableListOf<ResumeAuthRequest>()
    val clarifyRequests = mutableListOf<ResumeClarificationRequest>()
    val cancelRequests = mutableListOf<CancelTurnRequest>()
    var confirmCalls = 0

    var createResults = ArrayDeque<AgentApiResult<CreateSessionResponse>>()
    var submitResults = ArrayDeque<AgentApiResult<SubmitTurnAccepted>>()
    var pollResults = ArrayDeque<AgentApiResult<PollEventsResponse>>()
    var authResult: AgentApiResult<TurnMutationAccepted> =
        AgentApiResult.Success(TurnMutationAccepted("t1", TurnState.RUNNING, 4, 0))
    var clarifyResult: AgentApiResult<TurnMutationAccepted> =
        AgentApiResult.Success(TurnMutationAccepted("t1", TurnState.RUNNING, 6, 0))
    var cancelResult: AgentApiResult<CancelTurnResponse> =
        AgentApiResult.Success(CancelTurnResponse(CancelResult.CANCELLED, status(TurnState.CANCELLED)))
    var sessions: AgentApiResult<ListSessionsResponse> = AgentApiResult.Success(ListSessionsResponse(emptyList()))
    var sessionDetail: AgentApiResult<SessionDetailResponse>? = null
    val pollsByTurn = mutableMapOf<String, ArrayDeque<AgentApiResult<PollEventsResponse>>>()

    private fun summary() = SessionSummary("s1", "2026-10-22T08:00:00Z", "2026-10-22T08:00:00Z", 0)

    override suspend fun listSessions(cursor: String?, limit: Int?) = sessions
    override suspend fun createSession(request: CreateSessionRequest): AgentApiResult<CreateSessionResponse> {
        createRequests += request
        return createResults.removeFirstOrNull() ?: AgentApiResult.Success(CreateSessionResponse(summary()))
    }

    override suspend fun getSession(sessionId: String) = sessionDetail!!
    override suspend fun submitTurn(sessionId: String, request: SubmitTurnRequest): AgentApiResult<SubmitTurnAccepted> {
        submitRequests += request
        return submitResults.removeFirstOrNull()
            ?: AgentApiResult.Success(SubmitTurnAccepted("t${submitRequests.size}", "2026-10-22T08:00:00Z"))
    }

    override suspend fun pollEvents(turnId: String, afterSeq: Int, limit: Int?): AgentApiResult<PollEventsResponse> {
        pollAfter += turnId to afterSeq
        val queue = pollsByTurn[turnId] ?: pollResults
        return queue.removeFirstOrNull() ?: error("unexpected poll #${pollAfter.size} for $turnId")
    }

    override suspend fun cancelTurn(turnId: String, request: CancelTurnRequest): AgentApiResult<CancelTurnResponse> {
        cancelRequests += request
        return cancelResult
    }

    override suspend fun resumeAuth(turnId: String, request: ResumeAuthRequest): AgentApiResult<TurnMutationAccepted> {
        authRequests += request
        return authResult
    }

    override suspend fun resumeClarification(
        turnId: String,
        request: ResumeClarificationRequest,
    ): AgentApiResult<TurnMutationAccepted> {
        clarifyRequests += request
        return clarifyResult
    }

    override suspend fun resumeProposalAdjust(
        turnId: String,
        request: ResumeProposalAdjustRequest,
    ): AgentApiResult<ProposalAdjustedAccepted> = error("proposal adjust is out of scope")

    override suspend fun confirmProposal(
        proposalId: String,
        request: ConfirmProposalRequest,
    ): AgentApiResult<ConfirmationUnavailableResponse> {
        confirmCalls++
        error("confirmProposal must never be called in this phase")
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
private class Harness {
    val repo = FakeAgentRepository()
    val delays = mutableListOf<Long>()
    private var counter = 0
    val vm = AgentAssistantViewModel(
        repository = repo,
        newId = { "id-${++counter}" },
        dispatcher = UnconfinedTestDispatcher(),
        pollDelay = { delays += it },
    )
    val state get() = vm.state.value
}

class AgentAssistantViewModelTest {
    @Test
    fun submitCreatesSessionOnceThenTurn() {
        val h = Harness()
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED), listOf(message(1))))
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED, turnId = "t2"), listOf(message(1))))
        h.vm.submit("昨天烧烤750，我付的，4个人平分，记在周末露营里", null)
        h.vm.submit("再问一句", null)

        assertEquals(1, h.repo.createRequests.size)
        assertEquals("昨天烧烤750，我付的，4个人平分，记在周末露营里".take(20), h.repo.createRequests[0].title)
        assertEquals(2, h.repo.submitRequests.size)
        assertEquals("s1", h.state.currentSessionId)
        assertEquals(0, h.repo.confirmCalls)
    }

    @Test
    fun pollingAdvancesCursorDedupesSeqMergesCardsAndStopsOnWaitConfirm() {
        val h = Harness()
        val older = card(revision = 1)
        val newer = card(revision = 2)
        h.repo.pollResults += AgentApiResult.Success(
            poll(0, 2, status(TurnState.RUNNING), listOf(message(1), message(2)), cards = listOf(newer)),
        )
        h.repo.pollResults += AgentApiResult.Success(
            poll(
                2, 4, status(TurnState.WAIT_CONFIRM, TurnStep.AWAITING_USER),
                listOf(
                    message(2), // replayed
                    message(3),
                    ProposalEvent(4, "2026-10-22T08:00:00Z", true, ProposalEventPayload(ProposalOperation.EXPENSE_CREATE, "pr1", 2)),
                ),
                cards = listOf(older), // stale revision must not win
            ),
        )
        h.vm.submit("记一笔", null)

        assertEquals(listOf("t1" to 0, "t1" to 2), h.repo.pollAfter)
        val items = h.state.items
        assertEquals(1, items.count { it.key == "e:t1:2" })
        assertEquals(listOf("u:id-2", "e:t1:1", "e:t1:2", "e:t1:3", "e:t1:4"), items.map { it.key })
        assertEquals(newer, h.state.cards["pr1"])
        assertEquals(TurnState.WAIT_CONFIRM, h.state.turn?.state)
        assertEquals("草稿已拟好，等你确认", h.state.statusLine)
        assertEquals(ComposerMode.Normal, h.state.composer)
        assertEquals(2, h.repo.pollAfter.size) // stopped
        assertEquals(0, h.repo.confirmCalls)
    }

    @Test
    fun hasMorePollsImmediatelyOtherwiseWaits() {
        val h = Harness()
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.RUNNING), listOf(message(1)), hasMore = true))
        h.repo.pollResults += AgentApiResult.Success(poll(1, 2, status(TurnState.RUNNING), listOf(message(2))))
        h.repo.pollResults += AgentApiResult.Success(poll(2, 3, status(TurnState.COMPLETED), listOf(message(3))))
        h.vm.submit("hi", null)

        assertEquals(3, h.repo.pollAfter.size)
        assertEquals(listOf(800L), h.delays) // only after the response without has_more
    }

    @Test
    fun authRequiredTriggersExactlyOneResume() {
        val h = Harness()
        val auth = status(TurnState.WAIT_INPUT, TurnStep.AUTH_REQUIRED, revision = 3, waitReason = WaitReason.AUTH_REQUIRED)
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, auth, listOf(message(1))))
        h.repo.pollResults += AgentApiResult.Success(poll(1, 1, auth)) // still stale: must not resume again
        h.vm.submit("hi", null)

        assertEquals(1, h.repo.authRequests.size)
        assertEquals(3, h.repo.authRequests[0].expectedStateRevision)
        assertEquals(2, h.repo.pollAfter.size)
    }

    @Test
    fun authResumeFailureShowsErrorCopy() {
        val h = Harness()
        h.repo.authResult = AgentApiResult.ApiError(AgentErrorCode.UNAUTHENTICATED, "x", false, 401)
        h.repo.pollResults += AgentApiResult.Success(
            poll(0, 0, status(TurnState.WAIT_INPUT, TurnStep.AUTH_REQUIRED, 3, WaitReason.AUTH_REQUIRED)),
        )
        h.vm.submit("hi", null)

        assertEquals(AgentErrorMessages.UNAUTHENTICATED, h.state.banner?.message)
        assertEquals(1, h.repo.authRequests.size)
    }

    @Test
    fun clarificationResumeSendsExpectedStateRevision() {
        val h = Harness()
        val wait = status(TurnState.WAIT_INPUT, TurnStep.AWAITING_USER, revision = 5, waitReason = WaitReason.MISSING_FIELDS)
        h.repo.pollResults += AgentApiResult.Success(
            poll(
                0, 1, wait,
                listOf(ClarificationEvent(1, "2026-10-22T08:00:00Z", false,
                    ClarificationEventPayload(listOf(MissingSlot.ORIGINAL_AMOUNT), "多少钱？", TurnState.RUNNING))),
            ),
        )
        h.repo.pollResults += AgentApiResult.Success(poll(1, 2, status(TurnState.COMPLETED, revision = 7), listOf(message(2))))
        h.vm.submit("烧烤", null)

        assertEquals(ComposerMode.Clarification(listOf(MissingSlot.ORIGINAL_AMOUNT)), h.state.composer)
        h.vm.submit("750", null)

        assertEquals(1, h.repo.clarifyRequests.size)
        assertEquals(5, h.repo.clarifyRequests[0].expectedStateRevision)
        assertEquals("750", h.repo.clarifyRequests[0].text)
        assertEquals(1, h.repo.submitRequests.size) // not a new turn
        assertEquals(listOf("t1" to 0, "t1" to 1), h.repo.pollAfter)
        assertEquals(ComposerMode.Normal, h.state.composer)
    }

    @Test
    fun retryReusesTheSameRequestObject() {
        val h = Harness()
        h.repo.submitResults += AgentApiResult.NetworkFailure(IOException("down"))
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED), listOf(message(1))))
        h.vm.submit("hi", null)

        assertEquals(AgentErrorMessages.NETWORK_FAILURE, h.state.banner?.message)
        assertTrue(h.state.banner!!.canRetry)
        assertEquals(ComposerMode.Normal, h.state.composer)

        h.vm.retry()

        assertEquals(2, h.repo.submitRequests.size)
        assertSame(h.repo.submitRequests[0], h.repo.submitRequests[1])
        assertEquals(1, h.repo.createRequests.size)
        assertNull(h.state.banner)
        assertEquals(1, h.state.items.count { it is UserTextItem })
    }

    @Test
    fun createSessionFailureRetryReusesCreateRequestToo() {
        val h = Harness()
        h.repo.createResults += AgentApiResult.ApiError(AgentErrorCode.RATE_LIMITED, "slow", true, 429)
        h.repo.pollResults += AgentApiResult.Success(poll(0, 0, status(TurnState.COMPLETED)))
        h.vm.submit("hi", null)
        assertEquals(AgentErrorMessages.RATE_LIMITED, h.state.banner?.message)
        h.vm.retry()

        assertEquals(2, h.repo.createRequests.size)
        assertSame(h.repo.createRequests[0], h.repo.createRequests[1])
        assertEquals(1, h.repo.submitRequests.size)
    }

    @Test
    fun failuresMapToChineseCopy() {
        val cases = mapOf(
            AgentErrorCode.UNAUTHENTICATED to AgentErrorMessages.UNAUTHENTICATED,
            AgentErrorCode.FORBIDDEN to AgentErrorMessages.FORBIDDEN,
            AgentErrorCode.AGENT_DISABLED to AgentErrorMessages.AGENT_DISABLED,
            AgentErrorCode.DEPENDENCY_UNAVAILABLE to AgentErrorMessages.DEPENDENCY_UNAVAILABLE,
        )
        for ((code, copy) in cases) {
            val h = Harness()
            h.repo.createResults += AgentApiResult.ApiError(code, "raw", false, 400)
            h.vm.submit("hi", null)
            assertEquals(copy, h.state.banner?.message)
        }
        val h = Harness()
        h.repo.createResults += AgentApiResult.ApiError(AgentErrorCode.INVALID_REQUEST, "服务端说明", false, 400)
        h.vm.submit("hi", null)
        assertEquals("服务端说明", h.state.banner?.message)
    }

    @Test
    fun pollFailureShowsRetryThatResumesPolling() {
        val h = Harness()
        h.repo.pollResults += AgentApiResult.NetworkFailure(IOException("x"))
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED), listOf(message(1))))
        h.vm.submit("hi", null)
        assertEquals(AgentErrorMessages.NETWORK_FAILURE, h.state.banner?.message)
        h.vm.retry()
        assertEquals(listOf("t1" to 0, "t1" to 0), h.repo.pollAfter)
        assertNull(h.state.banner)
    }

    @Test
    fun cancelSendsExpectedStateRevisionAndShowsResult() {
        val h = Harness()
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.RUNNING, revision = 2), listOf(message(1))))
        // Stop after one poll by failing the next one so the turn stays RUNNING.
        h.repo.pollResults += AgentApiResult.NetworkFailure(IOException("x"))
        h.vm.submit("hi", null)
        h.vm.dismissBanner()
        h.vm.cancel()

        assertEquals(2, h.repo.cancelRequests[0].expectedStateRevision)
        assertEquals("已停止", h.state.notice)
        assertEquals(ComposerMode.Normal, h.state.composer)
    }

    @Test
    fun openSessionRebuildsTranscriptFromEveryTurnRespectingHasMore() {
        val h = Harness()
        val summary = SessionSummary("s1", "c", "u", 0, "标题")
        h.repo.sessionDetail = AgentApiResult.Success(
            SessionDetailResponse(
                summary,
                turns = listOf(
                    TurnSummary("tA", TurnState.COMPLETED, 3, "c", "u"),
                    TurnSummary("tB", TurnState.COMPLETED, 3, "c", "u"),
                ),
                proposalCards = listOf(card()),
            ),
        )
        h.repo.pollsByTurn["tA"] = ArrayDeque(
            listOf(
                AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED, turnId = "tA"), listOf(message(1)), hasMore = true)),
                AgentApiResult.Success(poll(1, 2, status(TurnState.COMPLETED, turnId = "tA"), listOf(message(2)))),
            ),
        )
        h.repo.pollsByTurn["tB"] = ArrayDeque(
            listOf(AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED, turnId = "tB"), listOf(message(1))))),
        )
        h.vm.openSession("s1")

        assertEquals(listOf("tA" to 0, "tA" to 1, "tB" to 0), h.repo.pollAfter)
        assertEquals(listOf("e:tA:1", "e:tA:2", "e:tB:1"), h.state.items.map { it.key })
        assertEquals("s1", h.state.currentSessionId)
        assertEquals(AgentPanelView.Chat, h.state.view)
        assertTrue(h.state.cards.containsKey("pr1"))
        assertEquals(0, h.delays.size)
        assertTrue(h.state.items.none { it is AssistantMessageItem && it.animateEntrance })
    }

    @Test
    fun liveItemsAnimateAndPlayedEntrancesAreTrackedOnce() {
        val h = Harness()
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED), listOf(message(1))))
        h.vm.submit("hi", null)

        val user = h.state.items.filterIsInstance<UserTextItem>().single()
        val reply = h.state.items.filterIsInstance<AssistantMessageItem>().single()
        assertTrue(user.animateEntrance)
        assertTrue(reply.animateEntrance)
        assertTrue(h.state.playedEntrances.isEmpty())
        h.vm.markEntrancePlayed(reply.key)
        h.vm.markEntrancePlayed(reply.key)
        assertEquals(setOf(reply.key), h.state.playedEntrances)
    }

    @Test
    fun terminalTurnDoesNotPollAndPanelOpenDoesNotRestartIt() {
        val h = Harness()
        h.repo.pollResults += AgentApiResult.Success(poll(0, 1, status(TurnState.COMPLETED), listOf(message(1))))
        h.vm.submit("hi", null)
        h.vm.setPanelOpen(true)
        assertEquals(1, h.repo.pollAfter.size)
        assertFalse(h.state.composer == ComposerMode.Running)
    }

    @Test
    fun statusCopyMapsEveryStep() {
        fun line(state: TurnState, step: TurnStep) = AgentStatusCopy.forTurn(status(state, step))
        assertEquals("已收到", line(TurnState.QUEUED, TurnStep.ACCEPTED))
        assertEquals("正在理解你的话", line(TurnState.RUNNING, TurnStep.BUILD_CONTEXT))
        assertEquals("正在理解你的话", line(TurnState.RUNNING, TurnStep.MODEL_DECISION))
        assertEquals("正在读取账目", line(TurnState.RUNNING, TurnStep.TOOL_READ))
        assertEquals("正在拟草稿", line(TurnState.RUNNING, TurnStep.PREPARE_PROPOSAL))
        assertEquals("等你补充", line(TurnState.WAIT_INPUT, TurnStep.AWAITING_USER))
        assertEquals("需要重新登录", line(TurnState.WAIT_INPUT, TurnStep.AUTH_REQUIRED))
        assertEquals("正在处理", line(TurnState.EXECUTING, TurnStep.DISPATCH))
        assertEquals("正在处理", line(TurnState.EXECUTING, TurnStep.RECONCILE))
        assertEquals("正在处理", line(TurnState.EXECUTING, TurnStep.FINALIZE))
        assertEquals("草稿已拟好，等你确认", line(TurnState.WAIT_CONFIRM, TurnStep.AWAITING_USER))
        assertNull(line(TurnState.COMPLETED, TurnStep.TERMINAL))
        assertNull(line(TurnState.FAILED, TurnStep.TERMINAL))
        assertNull(line(TurnState.CANCELLED, TurnStep.TERMINAL))
    }
}
