package com.ffocalors.sharedledger.data.agent

import java.io.IOException
import java.time.Instant
import java.util.UUID
import kotlin.random.Random
import kotlinx.coroutines.delay

/**
 * Debug-only in-memory fake of the Agent service. Each turn is a timeline of events released by
 * wall-clock time since submit, so polling behaves like a server that is slowly working.
 */
class DemoAgentRepository(
    private val now: () -> Long = System::currentTimeMillis,
    private val latency: suspend () -> Unit = { delay(Random.nextLong(150, 301)) },
    private val newId: () -> String = { UUID.randomUUID().toString() },
    /** Gap between ordinary timeline steps. */
    private val stepMs: Long = 500,
) : AgentRepository {
    private class Entry(val at: Long, val event: AgentEvent, val statusAfter: TurnPublicStatus)

    private class Turn(val id: String, val sessionId: String, val startMs: Long, var text: String) {
        val entries = mutableListOf<Entry>()
        var lastAt = startMs
        val cards = mutableMapOf<String, ProposalCard>()
        var executionId: String? = null
        val createdAt: String = Instant.ofEpochMilli(startMs).toString()
    }

    private class Session(val id: String, val createdAt: String, var updatedAt: String, var title: String?) {
        val turns = mutableListOf<Turn>()
    }

    private val lock = Any()
    private val sessions = LinkedHashMap<String, Session>()
    private val turns = HashMap<String, Turn>()
    private val createRequests = HashMap<String, String>()
    private val turnRequests = HashMap<String, String>()
    private val offlineFailedRequests = HashSet<String>()
    private val userId = newId()
    private val ledgerUnitId = newId()

    private suspend fun <T> call(block: () -> T): T {
        latency()
        return synchronized(lock, block)
    }

    private fun iso(ms: Long = now()): String = Instant.ofEpochMilli(ms).toString()

    private fun err(code: AgentErrorCode, message: String, status: Int) =
        AgentApiResult.ApiError(code, message, retryable = false, httpStatus = status)

    // ---- sessions -----------------------------------------------------------------------------

    private fun Session.summary() = SessionSummary(
        sessionId = id,
        createdAt = createdAt,
        updatedAt = updatedAt,
        activeTurnCount = turns.count { !current(it).state.isTerminal },
        title = title,
    )

    override suspend fun listSessions(cursor: String?, limit: Int?): AgentApiResult<ListSessionsResponse> = call {
        val items = sessions.values.sortedByDescending { it.updatedAt }.map { it.summary() }
        AgentApiResult.Success(ListSessionsResponse(items = if (limit != null) items.take(limit) else items))
    }

    override suspend fun createSession(request: CreateSessionRequest): AgentApiResult<CreateSessionResponse> = call {
        val existing = createRequests[request.clientRequestId]?.let { sessions[it] }
        val session = existing ?: Session(newId(), iso(), iso(), request.title?.take(TITLE_LENGTH)).also {
            sessions[it.id] = it
            createRequests[request.clientRequestId] = it.id
        }
        AgentApiResult.Success(CreateSessionResponse(session.summary()))
    }

    override suspend fun getSession(sessionId: String): AgentApiResult<SessionDetailResponse> = call {
        val session = sessions[sessionId] ?: return@call err(AgentErrorCode.NOT_FOUND, "session not found", 404)
        AgentApiResult.Success(
            SessionDetailResponse(
                session = session.summary(),
                turns = session.turns.map {
                    val s = current(it)
                    TurnSummary(it.id, s.state, s.stateRevision, it.createdAt, iso(it.lastAt))
                },
                proposalCards = session.turns.flatMap { t -> released(t).mapNotNull { cardFor(t, it) } + currentCards(t) }
                    .distinctBy { "${it.proposalIdOrEmpty()}:${it.revisionOrZero()}" },
            ),
        )
    }

    // ---- turns --------------------------------------------------------------------------------

    override suspend fun submitTurn(sessionId: String, request: SubmitTurnRequest): AgentApiResult<SubmitTurnAccepted> =
        call {
            val session = sessions[sessionId] ?: return@call err(AgentErrorCode.NOT_FOUND, "session not found", 404)
            turnRequests[request.clientRequestId]?.let { id ->
                val t = turns.getValue(id)
                return@call AgentApiResult.Success(SubmitTurnAccepted(t.id, t.createdAt))
            }
            val script = DemoScripts.choose(request.text)
            if (script == DemoScript.OFFLINE && offlineFailedRequests.add(request.clientRequestId)) {
                return@call AgentApiResult.NetworkFailure(IOException("demo offline"))
            }
            val turn = Turn(newId(), sessionId, now(), request.text)
            turns[turn.id] = turn
            turnRequests[request.clientRequestId] = turn.id
            session.turns += turn
            if (session.title == null) session.title = request.text.trim().take(TITLE_LENGTH)
            session.updatedAt = iso()
            append(turn, TurnState.QUEUED, TurnStep.ACCEPTED, 0)
            play(turn, if (script == DemoScript.OFFLINE) DemoScript.ANSWER else script, request.text, resumed = false)
            AgentApiResult.Success(SubmitTurnAccepted(turn.id, turn.createdAt))
        }

    override suspend fun pollEvents(turnId: String, afterSeq: Int, limit: Int?): AgentApiResult<PollEventsResponse> =
        call {
            val turn = turns[turnId] ?: return@call err(AgentErrorCode.NOT_FOUND, "turn not found", 404)
            val newer = released(turn).filter { it.event.seq > afterSeq }
            val page = if (limit != null && limit > 0) newer.take(limit) else newer
            val events = page.map { it.event }
            AgentApiResult.Success(
                PollEventsResponse(
                    afterSeq = afterSeq,
                    nextAfterSeq = events.lastOrNull()?.seq ?: afterSeq,
                    hasMore = page.size < newer.size,
                    turn = current(turn),
                    events = events,
                    proposalCards = page.mapNotNull { cardFor(turn, it) } + currentCards(turn),
                ),
            )
        }

    override suspend fun cancelTurn(turnId: String, request: CancelTurnRequest): AgentApiResult<CancelTurnResponse> =
        call {
            val turn = turns[turnId] ?: return@call err(AgentErrorCode.NOT_FOUND, "turn not found", 404)
            if (current(turn).state.isTerminal) {
                return@call err(AgentErrorCode.STATE_REVISION_CONFLICT, "turn already finished", 409)
            }
            val t = now()
            turn.entries.removeAll { it.at > t }
            turn.lastAt = t
            append(turn, TurnState.CANCELLED, TurnStep.TERMINAL, 0)
            AgentApiResult.Success(CancelTurnResponse(CancelResult.CANCELLED, current(turn)))
        }

    override suspend fun resumeAuth(turnId: String, request: ResumeAuthRequest): AgentApiResult<TurnMutationAccepted> =
        call {
            val turn = turns[turnId] ?: return@call err(AgentErrorCode.NOT_FOUND, "turn not found", 404)
            val s = current(turn)
            AgentApiResult.Success(TurnMutationAccepted(turnId, s.state, s.stateRevision, turn.entries.size))
        }

    override suspend fun resumeClarification(
        turnId: String,
        request: ResumeClarificationRequest,
    ): AgentApiResult<TurnMutationAccepted> = call {
        val turn = turns[turnId] ?: return@call err(AgentErrorCode.NOT_FOUND, "turn not found", 404)
        if (current(turn).state != TurnState.WAIT_INPUT) {
            return@call err(AgentErrorCode.STATE_REVISION_CONFLICT, "turn is not waiting for input", 409)
        }
        val cursor = turn.entries.size
        turn.lastAt = maxOf(now(), turn.lastAt)
        turn.text = "${turn.text} ${request.text}"
        append(turn, TurnState.RUNNING, TurnStep.MODEL_DECISION, 0)
        val next = if (DemoScripts.parseAmount(turn.text) != null) DemoScript.DRAFT else DemoScript.CLARIFY
        play(turn, next, turn.text, resumed = true)
        sessions[turn.sessionId]?.updatedAt = iso()
        AgentApiResult.Success(
            TurnMutationAccepted(turnId, TurnState.RUNNING, last(turn, cursor).stateRevision, cursor),
        )
    }

    override suspend fun resumeProposalAdjust(
        turnId: String,
        request: ResumeProposalAdjustRequest,
    ): AgentApiResult<ProposalAdjustedAccepted> = call {
        err(AgentErrorCode.INVALID_REQUEST, "演示模式不支持调整草稿", 400)
    }

    override suspend fun confirmProposal(
        proposalId: String,
        request: ConfirmProposalRequest,
    ): AgentApiResult<ConfirmProposalOutcome> = call {
        val turn = turns.values.firstOrNull { proposalId in it.cards }
            ?: return@call err(AgentErrorCode.NOT_FOUND, "proposal not found", 404)
        val card = turn.cards.getValue(proposalId)
        val replayExecution = turn.executionId
        // A replayed confirm returns the original execution instead of dispatching a second one.
        if (replayExecution != null) {
            return@call AgentApiResult.Success(
                ConfirmProposalOutcome.ExecutionAccepted(
                    ProposalExecutionAccepted(
                        turn = current(turn),
                        execution = ExecutionReference(replayExecution, proposalId, request.expectedProposalRevision),
                        eventCursor = released(turn).size,
                    ),
                ),
            )
        }
        if (DemoScripts.confirmScenario(turn.text) == DemoConfirmScenario.UNAVAILABLE) {
            return@call AgentApiResult.Success(
                ConfirmProposalOutcome.Unavailable(
                    ConfirmationUnavailableResponse(
                        code = AgentErrorCode.EXECUTION_CAPABILITY_UNAVAILABLE,
                        message = "演示：执行暂不可用",
                    ),
                ),
            )
        }
        val executionId = newId()
        turn.executionId = executionId
        turn.lastAt = maxOf(now(), turn.lastAt)
        append(turn, TurnState.EXECUTING, TurnStep.DISPATCH, 0, assigned = true)
        val execution = ExecutionReference(executionId, proposalId, request.expectedProposalRevision)
        when (DemoScripts.confirmScenario(turn.text)) {
            // The effect may or may not have landed: report RECOVERING/unknown, never success.
            DemoConfirmScenario.RECOVERING -> {
                append(
                    turn, TurnState.RECOVERING, TurnStep.RECONCILE, 900,
                    wait = WaitReason.EXECUTION_RESULT_UNKNOWN,
                    assigned = true,
                    resolution = ExecutionResolution.UNKNOWN,
                )
            }
            else -> {
                emit(turn, 1_200) { seq, at ->
                    ExecutionResultEvent(
                        seq, at, true,
                        ExecutionResultPayload(
                            execution = execution,
                            resolution = ExecutionResolution.SUCCEEDED,
                            resultSummary = "已记入演示账本",
                        ),
                    )
                }
                append(turn, TurnState.COMPLETED, TurnStep.TERMINAL, 0, assigned = true, resolution = ExecutionResolution.SUCCEEDED)
            }
        }
        turn.cards[proposalId] = closedCard(card, proposalId)
        sessions[turn.sessionId]?.updatedAt = iso()
        AgentApiResult.Success(
            ConfirmProposalOutcome.ExecutionAccepted(
                ProposalExecutionAccepted(
                    turn = current(turn),
                    execution = execution,
                    eventCursor = released(turn).size,
                ),
            ),
        )
    }

    private fun closedCard(card: ProposalCard, proposalId: String): InactiveProposalCard {
        val preview = when (card) {
            is ConfirmableProposalCard -> card.preview
            is SimulationProposalCard -> card.preview
            is InactiveProposalCard -> card.preview
            else -> null
        }
        return InactiveProposalCard(
            proposalId = proposalId,
            revision = card.revisionOrZero(),
            operation = when (card) {
                is ConfirmableProposalCard -> card.operation
                is SimulationProposalCard -> card.operation
                is InactiveProposalCard -> card.operation
                else -> ProposalOperation.EXPENSE_CREATE
            },
            mode = ProposalMode.BACKEND,
            status = ProposalStatus.CONFIRMED,
            simulation = false,
            preview = preview,
        )
    }

    // ---- timeline -----------------------------------------------------------------------------

    private fun released(turn: Turn): List<Entry> {
        val t = now()
        return turn.entries.takeWhile { it.at <= t }
    }

    /** Status as a poller would see it right now. */
    private fun current(turn: Turn): TurnPublicStatus =
        released(turn).lastOrNull()?.statusAfter ?: pendingStatus(turn)

    /** Status after the entry at [index] (the revision a resumed turn starts from). */
    private fun last(turn: Turn, index: Int): TurnPublicStatus = turn.entries[index].statusAfter

    private fun pendingStatus(turn: Turn) = TurnPublicStatus(
        turnId = turn.id, sessionId = turn.sessionId, state = TurnState.QUEUED, stateRevision = 1,
        step = TurnStep.ACCEPTED, contextVersion = 1, executionAssigned = false,
    )

    private fun tail(turn: Turn): TurnPublicStatus = turn.entries.lastOrNull()?.statusAfter ?: pendingStatus(turn)

    private fun cardFor(turn: Turn, entry: Entry): ProposalCard? =
        (entry.event as? ProposalEvent)?.let { turn.cards[it.payload.proposalId] }

    /** Closed drafts are re-sent on every poll so a client that missed the transition catches up. */
    private fun currentCards(turn: Turn): List<ProposalCard> =
        turn.cards.values.filterIsInstance<InactiveProposalCard>()

    /** Appends a status event [gapMs] after the previous entry; bumps the revision on state change. */
    private fun append(
        turn: Turn,
        state: TurnState,
        step: TurnStep,
        gapMs: Long,
        wait: WaitReason? = null,
        resume: TurnState? = null,
        assigned: Boolean? = null,
        resolution: ExecutionResolution? = null,
    ) {
        val prev = tail(turn)
        val at = turn.lastAt + gapMs
        turn.lastAt = at
        val revision = when {
            turn.entries.isEmpty() -> 1
            prev.state != state -> prev.stateRevision + 1
            else -> prev.stateRevision
        }
        val after = prev.copy(
            state = state,
            stateRevision = revision,
            step = step,
            waitReason = wait,
            resumeState = resume,
            executionAssigned = assigned ?: prev.executionAssigned,
            executionResolution = resolution ?: prev.executionResolution,
        )
        val event = StatusEvent(
            seq = turn.entries.size + 1,
            occurredAt = iso(at),
            simulation = true,
            payload = StatusEventPayload(state, revision, step, resume, wait),
        )
        turn.entries += Entry(at, event, after)
    }

    private fun running(turn: Turn, step: TurnStep, gapMs: Long) = append(turn, TurnState.RUNNING, step, gapMs)

    private fun emit(turn: Turn, gapMs: Long, build: (seq: Int, occurredAt: String) -> AgentEvent) {
        val at = turn.lastAt + gapMs
        turn.lastAt = at
        turn.entries += Entry(at, build(turn.entries.size + 1, iso(at)), tail(turn))
    }

    private fun message(turn: Turn, gapMs: Long, text: String) =
        emit(turn, gapMs) { seq, at -> MessageEvent(seq, at, true, MessageEventPayload(text)) }

    private fun complete(turn: Turn) = append(turn, TurnState.COMPLETED, TurnStep.TERMINAL, 0)

    private fun play(turn: Turn, script: DemoScript, text: String, resumed: Boolean) {
        val gap = stepMs
        if (!resumed) running(turn, TurnStep.BUILD_CONTEXT, gap)
        when (script) {
            DemoScript.DRAFT -> draft(turn, text, resumed)
            DemoScript.CLARIFY -> {
                running(turn, TurnStep.MODEL_DECISION, gap + 100)
                emit(turn, gap) { seq, at ->
                    ClarificationEvent(
                        seq, at, true,
                        ClarificationEventPayload(
                            missingSlots = listOf(MissingSlot.ORIGINAL_AMOUNT),
                            prompt = "这笔一共花了多少钱？",
                            resumeState = TurnState.RUNNING,
                        ),
                    )
                }
                append(
                    turn, TurnState.WAIT_INPUT, TurnStep.AWAITING_USER, 0,
                    wait = WaitReason.MISSING_FIELDS, resume = TurnState.RUNNING,
                )
            }
            DemoScript.ANSWER, DemoScript.OFFLINE -> {
                running(turn, TurnStep.TOOL_READ, gap)
                running(turn, TurnStep.MODEL_DECISION, gap + 100)
                message(
                    turn, gap + 100,
                    "按演示数据算，这个活动里你一共垫付了 1,280.00 元，应摊 905.50 元，还有 374.50 元没收回来：" +
                        "小林欠你 150.00 元，阿杰欠你 224.50 元。这些都是演示数据，并不是你的真实账目。",
                )
                complete(turn)
            }
            DemoScript.SLOW -> {
                val steps = listOf(TurnStep.TOOL_READ, TurnStep.MODEL_DECISION, TurnStep.PREPARE_PROPOSAL)
                repeat(10) { running(turn, steps[it % steps.size], SLOW_STEP_MS) }
                message(turn, 600, "终于想好了。这是演示模式里的慢速场景，下次可以试试点停止。")
                complete(turn)
            }
            DemoScript.ERROR -> {
                running(turn, TurnStep.MODEL_DECISION, gap + 100)
                emit(turn, gap) { seq, at ->
                    ErrorEvent(
                        seq, at, true,
                        ErrorEventPayload(AgentErrorCode.DEPENDENCY_UNAVAILABLE, "演示：助手暂时连不上模型服务，请稍后重试。", true),
                    )
                }
                append(turn, TurnState.FAILED, TurnStep.TERMINAL, 0)
            }
            DemoScript.DEFAULT -> {
                running(turn, TurnStep.MODEL_DECISION, gap)
                message(turn, gap, "这是演示模式。试试：记一笔“昨天烧烤 750，我付的，四个人平分”，或者问“谁还欠我钱？”")
                complete(turn)
            }
        }
    }

    private fun draft(turn: Turn, text: String, resumed: Boolean) {
        val gap = stepMs
        if (!resumed) {
            running(turn, TurnStep.TOOL_READ, gap)
            running(turn, TurnStep.MODEL_DECISION, gap + 100)
        }
        running(turn, TurnStep.PREPARE_PROPOSAL, gap + 100)
        message(turn, gap, "我按你说的拟了一张草稿，看看对不对。")
        val card = buildCard(text, iso(turn.lastAt))
        turn.cards[card.proposalId] = card
        emit(turn, 0) { seq, at ->
            ProposalEvent(seq, at, true, ProposalEventPayload(ProposalOperation.EXPENSE_CREATE, card.proposalId, card.revision))
        }
        append(
            turn, TurnState.WAIT_CONFIRM, TurnStep.AWAITING_USER, 0,
            wait = WaitReason.CONFIRM_REQUIRED, resume = TurnState.RUNNING,
        )
    }

    private fun buildCard(text: String, generatedAt: String): ConfirmableProposalCard {
        val amount = DemoScripts.parseAmount(text) ?: "0.00"
        val count = DemoScripts.parseParticipantCount(text)
        val title = DemoScripts.guessTitle(text)
        val participants = listOf(userId) + List(count - 1) { newId() }
        val payments = listOf(CanonicalPayment(amount, userId))
        val split = CanonicalEqualSplit(participants)
        val snapshot = ExpenseSnapshot(
            baseAmount = amount,
            expenseVersion = "demo-1",
            financialLocked = false,
            ledgerUnitId = ledgerUnitId,
            originalAmount = amount,
            originalCurrency = "CNY",
            paymentAllocations = payments,
            split = split,
            title = title,
            fxSnapshot = FxSnapshot("CNY", generatedAt, "CNY", "1", FxSource.IDENTITY),
        )
        val digest = newId().replace("-", "") + newId().replace("-", "")
        return ConfirmableProposalCard(
            proposalId = newId(),
            revision = 1,
            operation = ProposalOperation.EXPENSE_CREATE,
            preview = ExpensePreview(
                activityFinancialVersion = "demo-1",
                after = snapshot,
                changes = listOf(
                    ExpenseTitleChange(after = title),
                    ExpenseAmountChange(AmountField.ORIGINAL_AMOUNT, amount),
                    ExpenseCurrencyChange("CNY"),
                    ExpensePaymentsChange(payments),
                    ExpenseSplitChange(split),
                ),
                generatedAt = generatedAt,
                simulation = false,
                summary = "$title $amount 元，我先付，$count 人平均分摊（演示模式）",
            ),
            // Demo values: a valid 64-hex digest and a nonce matching the contract's charset.
            commandDigest = digest.take(64).ifEmpty { "0".repeat(64) },
            confirmationNonce = (newId() + newId()).replace("-", ""),
            expiresAt = Instant.ofEpochMilli(now() + 5 * 60_000).toString(),
        )
    }

    private companion object {
        const val TITLE_LENGTH = 20
        const val SLOW_STEP_MS = 2_000L
    }
}

private fun ProposalCard.revisionOrZero(): Int = when (this) {
    is SimulationProposalCard -> revision
    is ConfirmableProposalCard -> revision
    is InactiveProposalCard -> revision
    else -> 0
}

private fun ProposalCard.proposalIdOrEmpty(): String = when (this) {
    is SimulationProposalCard -> proposalId
    is ConfirmableProposalCard -> proposalId
    is InactiveProposalCard -> proposalId
    else -> ""
}
