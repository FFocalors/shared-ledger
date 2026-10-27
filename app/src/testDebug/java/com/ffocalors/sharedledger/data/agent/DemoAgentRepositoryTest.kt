package com.ffocalors.sharedledger.data.agent

import com.ffocalors.sharedledger.ui.agent.AnswerBlocks
import com.ffocalors.sharedledger.ui.agent.AnswerSegment
import com.ffocalors.sharedledger.ui.agent.LedgerEntry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DemoAgentRepositoryTest {
    private var clock = 1_000_000L
    private var ids = 0
    private val repo = DemoAgentRepository(
        now = { clock },
        latency = {},
        newId = { "00000000-0000-4000-8000-%012d".format(++ids) },
    )

    private fun <T> ok(r: AgentApiResult<T>): T = (r as AgentApiResult.Success<T>).value

    private fun sessionId(): String =
        ok(runBlocking { repo.createSession(CreateSessionRequest("c-${++ids}")) }).session.sessionId

    private fun submit(sid: String, text: String, requestId: String = "r-$text") =
        runBlocking { repo.submitTurn(sid, SubmitTurnRequest(requestId, text)) }

    private fun poll(turnId: String, after: Int = 0) = ok(runBlocking { repo.pollEvents(turnId, after) })

    private fun runTurn(text: String, advanceMs: Long): PollEventsResponse {
        val turn = ok(submit(sessionId(), text)).turnId
        clock += advanceMs
        return poll(turn)
    }

    // ---- pure helpers -------------------------------------------------------------------------

    @Test fun scriptChoiceByKeyword() {
        assertEquals(DemoScript.DRAFT, DemoScripts.choose("昨天烧烤 750，我付的"))
        assertEquals(DemoScript.DRAFT, DemoScripts.choose("100 AA"))
        assertEquals(DemoScript.CLARIFY, DemoScripts.choose("帮我记一笔烧烤"))
        assertEquals(DemoScript.ANSWER, DemoScripts.choose("谁还欠我钱？"))
        assertEquals(DemoScript.ANSWER, DemoScripts.choose("总共花了多少"))
        assertEquals(DemoScript.SLOW, DemoScripts.choose("来个慢的"))
        assertEquals(DemoScript.ERROR, DemoScripts.choose("出错"))
        assertEquals(DemoScript.OFFLINE, DemoScripts.choose("断网"))
        assertEquals(DemoScript.DEFAULT, DemoScripts.choose("你好"))
    }

    @Test fun demoAnswersParseIntoTheSameBlocksAsTheRealAgentOutput() {
        fun segments(text: String) = AnswerBlocks.parse(DemoScripts.answerText(text))
        val debts = segments("谁还欠我钱？").single() as AnswerSegment.Ledger
        assertEquals(2, debts.entries.count { it is LedgerEntry.Debt })
        val expense = (segments("总共花了多少").single() as AnswerSegment.Ledger).entries.single() as LedgerEntry.Expense
        // One 付款 line plus three 分摊 lines.
        assertEquals(4, expense.lines.size)
        val activities = segments("有哪些活动").single() as AnswerSegment.Ledger
        assertEquals(2, activities.entries.count { it is LedgerEntry.Activity })
        assertTrue((segments("部分活动").single() as AnswerSegment.Ledger).partial)
        assertTrue(segments("没有记录吗？").single() is AnswerSegment.Notice)
        assertEquals(DemoScript.ANSWER, DemoScripts.choose("有哪些活动"))
    }

    @Test fun amountAndCountParsing() {
        val text = "记一笔“昨天烧烤 750，我付的，四个人平分”"
        assertEquals("750.00", DemoScripts.parseAmount(text))
        assertEquals(4, DemoScripts.parseParticipantCount(text))
        assertEquals("12.50", DemoScripts.parseAmount("打车12.5"))
        assertEquals("80.00", DemoScripts.parseAmount("3个人 吃饭付80"))
        assertEquals(3, DemoScripts.parseParticipantCount("3人"))
        assertEquals(2, DemoScripts.parseParticipantCount("两个人"))
        assertEquals(2, DemoScripts.parseParticipantCount("我付了50"))
        assertEquals("烧烤", DemoScripts.guessTitle(text))
        assertEquals("这笔支出", DemoScripts.guessTitle("200"))
    }

    // ---- repository ---------------------------------------------------------------------------

    @Test fun eventsAreReleasedByTime() {
        val sid = sessionId()
        val turn = ok(submit(sid, "你好")).turnId
        val first = poll(turn)
        assertEquals(listOf(1), first.events.map { it.seq })
        assertEquals(TurnState.QUEUED, first.turn.state)
        clock += 10_000
        val all = poll(turn)
        assertEquals(TurnState.COMPLETED, all.turn.state)
        assertTrue(all.events.any { it is MessageEvent })
        val seqs = all.events.map { it.seq }
        assertEquals(seqs.indices.map { it + 1 }, seqs)
        assertEquals(seqs.last(), all.nextAfterSeq)
        assertFalse(all.hasMore)
        val tail = poll(turn, after = 1)
        assertEquals(seqs.drop(1), tail.events.map { it.seq })
        assertEquals(seqs.last(), poll(turn, after = seqs.last()).nextAfterSeq)
        assertTrue(poll(turn, after = seqs.last()).events.isEmpty())
    }

    @Test fun draftProducesConfirmableCardAndWaitsForConfirm() {
        val r = runTurn("记一笔“昨天烧烤 750，我付的，四个人平分”", 20_000)
        assertEquals(TurnState.WAIT_CONFIRM, r.turn.state)
        assertEquals(WaitReason.CONFIRM_REQUIRED, r.turn.waitReason)
        val card = r.proposalCards.single() as ConfirmableProposalCard
        val preview = card.preview as ExpensePreview
        assertEquals("750.00", preview.after.originalAmount)
        assertEquals("烧烤", preview.after.title)
        assertEquals(4, (preview.after.split as CanonicalEqualSplit).participantIds.size)
        assertFalse(card.simulation || preview.simulation)
        assertTrue(r.events.all { it.isSimulated() })
        assertTrue(r.events.filterIsInstance<StatusEvent>().last().payload.stateRevision >= 1)
    }

    @Test fun clarificationResumeLeadsToDraft() {
        val sid = sessionId()
        val turn = ok(submit(sid, "帮我记一笔烧烤")).turnId
        clock += 20_000
        val ask = poll(turn)
        assertEquals(TurnState.WAIT_INPUT, ask.turn.state)
        assertEquals(WaitReason.MISSING_FIELDS, ask.turn.waitReason)
        val clar = ask.events.filterIsInstance<ClarificationEvent>().single()
        assertEquals(listOf(MissingSlot.ORIGINAL_AMOUNT), clar.payload.missingSlots)
        val accepted = ok(
            runBlocking {
                repo.resumeClarification(turn, ResumeClarificationRequest("c2", ask.turn.stateRevision, "300"))
            },
        )
        assertEquals(ask.nextAfterSeq, accepted.eventCursor)
        clock += 20_000
        val done = poll(turn, ask.nextAfterSeq)
        assertEquals(TurnState.WAIT_CONFIRM, done.turn.state)
        assertTrue(done.turn.stateRevision > ask.turn.stateRevision)
        val doneCard = done.proposalCards.single() as ConfirmableProposalCard
        assertEquals("300.00", (doneCard.preview as ExpensePreview).after.originalAmount)
        assertEquals(ask.nextAfterSeq + 1, done.events.first().seq)
    }

    @Test fun cancelEndsSlowTurn() {
        val sid = sessionId()
        val turn = ok(submit(sid, "慢")).turnId
        clock += 5_000
        val running = poll(turn)
        assertEquals(TurnState.RUNNING, running.turn.state)
        val cancel = ok(runBlocking { repo.cancelTurn(turn, CancelTurnRequest("x", running.turn.stateRevision)) })
        assertEquals(CancelResult.CANCELLED, cancel.result)
        assertEquals(TurnState.CANCELLED, cancel.turn.state)
        clock += 60_000
        val after = poll(turn)
        assertEquals(TurnState.CANCELLED, after.turn.state)
        assertTrue(after.events.none { it is MessageEvent })
    }

    @Test fun errorTurnFails() {
        val r = runTurn("出错", 20_000)
        assertEquals(TurnState.FAILED, r.turn.state)
        val e = r.events.filterIsInstance<ErrorEvent>().single()
        assertEquals(AgentErrorCode.DEPENDENCY_UNAVAILABLE, e.payload.code)
        assertTrue(e.payload.retryable)
    }

    @Test fun offlineFailsFirstThenRetrySucceeds() {
        val sid = sessionId()
        assertTrue(submit(sid, "断网", "same") is AgentApiResult.NetworkFailure)
        val retry = ok(submit(sid, "断网", "same")).turnId
        clock += 20_000
        val r = poll(retry)
        assertEquals(TurnState.COMPLETED, r.turn.state)
        assertTrue(r.events.any { it is MessageEvent })
    }

    @Test fun historyKeepsSessionsAndCards() {
        val sid = sessionId()
        val turn = ok(submit(sid, "昨天烧烤 750，我付的，四个人平分，这是很长的标题用来截断")).turnId
        clock += 20_000
        val detail = ok(runBlocking { repo.getSession(sid) })
        assertEquals(1, detail.turns.size)
        assertEquals(1, detail.proposalCards.size)
        assertEquals(turn, detail.turns.single().turnId)
        val list = ok(runBlocking { repo.listSessions() })
        assertEquals(20, list.items.single().title!!.length)
        assertNotNull(list.items.single().updatedAt)
    }

    @Test fun confirmScenarioByKeyword() {
        assertEquals(DemoConfirmScenario.EXECUTE, DemoScripts.confirmScenario("昨天烧烤 750，我付的"))
        assertEquals(DemoConfirmScenario.RECOVERING, DemoScripts.confirmScenario("烧烤 750 核对一下"))
        assertEquals(DemoConfirmScenario.UNAVAILABLE, DemoScripts.confirmScenario("烧烤 750 不可用"))
    }

    @Test fun adjustIsRejected() {
        val turn = ok(submit(sessionId(), "你好")).turnId
        val adjust = runBlocking { repo.resumeProposalAdjust(turn, ResumeProposalAdjustRequest("a", 1, 1, "改")) }
        assertEquals(AgentErrorCode.INVALID_REQUEST, (adjust as AgentApiResult.ApiError).code)
    }

    @Test fun confirmDispatchesOnceAndReplayReturnsTheSameExecution() {
        val sid = sessionId()
        val turn = ok(submit(sid, "昨天烧烤 750，我付的")).turnId
        clock += 10_000
        val card = poll(turn).proposalCards.filterIsInstance<ConfirmableProposalCard>().single()
        val request = ConfirmProposalRequest("confirm-1", card.commandDigest, card.confirmationNonce, card.revision)

        val first = ok(runBlocking { repo.confirmProposal(card.proposalId, request) })
        val accepted = first as ConfirmProposalOutcome.ExecutionAccepted
        assertEquals(TurnState.EXECUTING, accepted.value.turn.state)
        assertTrue(accepted.value.turn.executionAssigned)

        val replay = ok(runBlocking { repo.confirmProposal(card.proposalId, request) })
        val replayed = replay as ConfirmProposalOutcome.ExecutionAccepted
        assertEquals(accepted.value.execution.executionId, replayed.value.execution.executionId)

        clock += 2_000
        val later = poll(turn, accepted.value.eventCursor)
        val result = later.events.filterIsInstance<ExecutionResultEvent>().single()
        assertEquals(ExecutionResolution.SUCCEEDED, result.payload.resolution)
        assertEquals(accepted.value.execution.executionId, result.payload.execution.executionId)
        assertEquals(TurnState.COMPLETED, later.turn.state)
        val closed = later.proposalCards.filterIsInstance<InactiveProposalCard>().single()
        assertEquals(ProposalStatus.CONFIRMED, closed.status)
    }

    @Test fun confirmWithUnavailableKeywordReturnsFrozen501() {
        val turn = ok(submit(sessionId(), "记 750 不可用")).turnId
        clock += 10_000
        val card = poll(turn).proposalCards.filterIsInstance<ConfirmableProposalCard>().single()
        val outcome = ok(runBlocking {
            repo.confirmProposal(card.proposalId, ConfirmProposalRequest("c", card.commandDigest, card.confirmationNonce, 1))
        })
        val unavailable = outcome as ConfirmProposalOutcome.Unavailable
        assertEquals(AgentErrorCode.EXECUTION_CAPABILITY_UNAVAILABLE, unavailable.value.code)
        assertFalse(unavailable.value.businessWritePerformed)
    }

    @Test fun confirmWithReconcileKeywordNeverClaimsSuccess() {
        val turn = ok(submit(sessionId(), "记 750 核对一下")).turnId
        clock += 10_000
        val card = poll(turn).proposalCards.filterIsInstance<ConfirmableProposalCard>().single()
        val accepted = ok(runBlocking {
            repo.confirmProposal(card.proposalId, ConfirmProposalRequest("c", card.commandDigest, card.confirmationNonce, 1))
        }) as ConfirmProposalOutcome.ExecutionAccepted
        assertEquals(TurnState.EXECUTING, accepted.value.turn.state)

        clock += 2_000
        val later = poll(turn, accepted.value.eventCursor)
        assertEquals(TurnState.RECOVERING, later.turn.state)
        assertEquals(ExecutionResolution.UNKNOWN, later.turn.executionResolution)
        assertTrue(later.events.none { it is ExecutionResultEvent })
    }

    private fun AgentEvent.isSimulated(): Boolean = when (this) {
        is StatusEvent -> simulation
        is MessageEvent -> simulation
        is ClarificationEvent -> simulation
        is ProposalEvent -> simulation
        is ErrorEvent -> simulation
        else -> true
    }
}
