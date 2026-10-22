package com.ffocalors.sharedledger.ui.agent

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ffocalors.sharedledger.data.agent.AgentApiResult
import com.ffocalors.sharedledger.data.agent.AgentErrorMessages
import com.ffocalors.sharedledger.data.agent.AgentEvent
import com.ffocalors.sharedledger.data.agent.AgentRepository
import com.ffocalors.sharedledger.data.agent.CancelResult
import com.ffocalors.sharedledger.data.agent.CancelTurnRequest
import com.ffocalors.sharedledger.data.agent.ClarificationEvent
import com.ffocalors.sharedledger.data.agent.ConfirmProposalOutcome
import com.ffocalors.sharedledger.data.agent.ConfirmProposalRequest
import com.ffocalors.sharedledger.data.agent.CreateSessionRequest
import com.ffocalors.sharedledger.data.agent.ErrorEvent
import com.ffocalors.sharedledger.data.agent.ExecutionResolution
import com.ffocalors.sharedledger.data.agent.ExecutionResultEvent
import com.ffocalors.sharedledger.data.agent.MessageEvent
import com.ffocalors.sharedledger.data.agent.MissingSlot
import com.ffocalors.sharedledger.data.agent.PollEventsResponse
import com.ffocalors.sharedledger.data.agent.ProposalCard
import com.ffocalors.sharedledger.data.agent.ConfirmableProposalCard
import com.ffocalors.sharedledger.data.agent.InactiveProposalCard
import com.ffocalors.sharedledger.data.agent.SimulationProposalCard
import com.ffocalors.sharedledger.data.agent.ProposalEvent
import com.ffocalors.sharedledger.data.agent.ResumeAuthRequest
import com.ffocalors.sharedledger.data.agent.ResumeClarificationRequest
import com.ffocalors.sharedledger.data.agent.SessionSummary
import com.ffocalors.sharedledger.data.agent.SubmitTurnRequest
import com.ffocalors.sharedledger.data.agent.TurnPublicStatus
import com.ffocalors.sharedledger.data.agent.TurnState
import com.ffocalors.sharedledger.data.agent.TurnStep
import com.ffocalors.sharedledger.data.agent.UiContext
import com.ffocalors.sharedledger.data.agent.WaitReason
import java.util.UUID
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

// ---------------------------------------------------------------------------------------------
// UI state
// ---------------------------------------------------------------------------------------------

sealed interface TranscriptItem {
    val key: String
}

/**
 * [animateEntrance] is true only for items that arrived live (sent or polled in this run); items rebuilt
 * from history are false and render in their final state.
 */
data class UserTextItem(
    override val key: String,
    val text: String,
    val animateEntrance: Boolean = false,
) : TranscriptItem
data class AssistantMessageItem(
    override val key: String,
    val text: String,
    val simulation: Boolean,
    val animateEntrance: Boolean = false,
) : TranscriptItem
data class ClarificationItem(
    override val key: String,
    val prompt: String,
    val animateEntrance: Boolean = false,
) : TranscriptItem
data class ProposalItem(
    override val key: String,
    val proposalId: String,
    val animateEntrance: Boolean = false,
) : TranscriptItem
data class ExecutionResultItem(override val key: String, val line: String) : TranscriptItem

/**
 * Durable receipt for a confirmed draft: which execution was dispatched and how its turn is going.
 * While the turn reconciles it says 正在核对结果 and never claims success or failure.
 */
data class ExecutionReceiptItem(
    override val key: String,
    val turnId: String,
    val executionId: String,
    val proposalRevision: Int,
    val state: TurnState,
    val resolution: ExecutionResolution? = null,
) : TranscriptItem {
    val reconciling: Boolean get() = state == TurnState.RECOVERING || resolution == ExecutionResolution.UNKNOWN
}
data class ErrorItem(override val key: String, val message: String, val retryable: Boolean) : TranscriptItem

sealed interface ComposerMode {
    data object Normal : ComposerMode
    data class Clarification(val missingSlots: List<MissingSlot>) : ComposerMode

    /** A turn is in flight: the text box is disabled and the send button becomes 停止. */
    data object Running : ComposerMode
}

enum class AgentPanelView { Chat, History }

data class AgentBanner(val message: String, val canRetry: Boolean)

data class AgentUiState(
    val view: AgentPanelView = AgentPanelView.Chat,
    val sessions: List<SessionSummary> = emptyList(),
    val sessionsLoading: Boolean = false,
    val currentSessionId: String? = null,
    val items: List<TranscriptItem> = emptyList(),
    /** Latest revision per proposal_id. */
    val cards: Map<String, ProposalCard> = emptyMap(),
    val turn: TurnPublicStatus? = null,
    val composer: ComposerMode = ComposerMode.Normal,
    val banner: AgentBanner? = null,
    /** Neutral one-off result line, e.g. the outcome of 停止. */
    val notice: String? = null,
    val pageLabel: String = "",
    val panelOpen: Boolean = false,
    /** Item keys / proposal ids whose entrance animation already played; each plays at most once. */
    val playedEntrances: Set<String> = emptySet(),
    /** The draft whose confirm request is in flight, if any. */
    val confirmingProposalId: String? = null,
    /** Drafts whose confirm was answered with the contract's 501 "execution unavailable". */
    val confirmUnavailable: Set<String> = emptySet(),
    /** Drafts whose confirmation dispatched an execution; their button never comes back. */
    val submittedProposals: Set<String> = emptySet(),
) {
    val statusLine: String? get() = AgentStatusCopy.forTurn(turn)
    val isRunning: Boolean get() = composer == ComposerMode.Running
}

object AgentStatusCopy {
    fun forTurn(turn: TurnPublicStatus?): String? {
        if (turn == null) return null
        return when (turn.state) {
            TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED, TurnState.UNKNOWN -> null
            TurnState.WAIT_CONFIRM -> "草稿已拟好，等你确认"
            TurnState.EXECUTING -> "正在记账"
            // An unknown execution outcome stays here until the runtime reconciles it.
            TurnState.RECOVERING -> "正在核对结果"
            else -> forStep(turn.step)
        }
    }

    fun forStep(step: TurnStep): String? = when (step) {
        TurnStep.ACCEPTED -> "已收到"
        TurnStep.BUILD_CONTEXT, TurnStep.MODEL_DECISION -> "正在理解你的话"
        TurnStep.TOOL_READ -> "正在读取账目"
        TurnStep.PREPARE_PROPOSAL -> "正在拟草稿"
        TurnStep.AWAITING_USER -> "等你补充"
        TurnStep.AUTH_REQUIRED -> "需要重新登录"
        TurnStep.DISPATCH, TurnStep.RECONCILE, TurnStep.FINALIZE -> "正在处理"
        TurnStep.TERMINAL, TurnStep.UNKNOWN -> null
    }

    fun missingSlotLabel(slot: MissingSlot): String = when (slot) {
        MissingSlot.ACTIVITY_REF -> "活动"
        MissingSlot.LEDGER_UNIT_REF -> "账本"
        MissingSlot.EXPENSE_REF -> "哪笔账目"
        MissingSlot.ORIGINAL_AMOUNT -> "金额"
        MissingSlot.ORIGINAL_CURRENCY -> "币种"
        MissingSlot.PAYMENT_ALLOCATIONS -> "付款人"
        MissingSlot.TITLE -> "标题"
        MissingSlot.SPLIT -> "分摊方式"
        MissingSlot.SPLIT_PARTICIPANT_REFS -> "分摊的人"
        MissingSlot.NOTE -> "备注"
        MissingSlot.ICON_KEY -> "图标"
        MissingSlot.UPDATE_FIELDS -> "要改的内容"
        MissingSlot.UNKNOWN -> "信息"
    }

    fun executionLine(resolution: ExecutionResolution, summary: String?): String = when (resolution) {
        ExecutionResolution.SUCCEEDED -> "已记账"
        ExecutionResolution.REJECTED -> "没有记账：" + (summary?.takeIf { it.isNotBlank() } ?: "请求被拒绝")
        ExecutionResolution.CLOSED -> "已关闭"
        ExecutionResolution.UNKNOWN -> "正在核对结果"
    }

    fun cancelNotice(result: CancelResult): String = when (result) {
        CancelResult.CANCELLED -> "已停止"
        CancelResult.CANCEL_REQUESTED -> "正在停止…"
        CancelResult.RECONCILING -> "正在核对结果…"
        CancelResult.UNKNOWN -> "已发出停止请求"
    }
}

// ---------------------------------------------------------------------------------------------
// ViewModel
// ---------------------------------------------------------------------------------------------

private const val POLL_IDLE_DELAY_MS = 800L
private const val SESSION_TITLE_LENGTH = 20

class AgentAssistantViewModel(
    private val repository: AgentRepository,
    private val newId: () -> String = { UUID.randomUUID().toString() },
    dispatcher: CoroutineDispatcher = Dispatchers.Main.immediate,
    /** Wait between idle polls; tests replace it to avoid real time. */
    private val pollDelay: suspend (Long) -> Unit = { delay(it) },
) : ViewModel() {
    private val scope = CoroutineScope(SupervisorJob() + dispatcher)
    private val _state = MutableStateFlow(AgentUiState())
    val state: StateFlow<AgentUiState> = _state.asStateFlow()

    private var pollJob: Job? = null
    private var pending: PendingAction? = null
    private var lastSubmittedText: String? = null

    // Per-turn bookkeeping that never reaches the UI.
    private val cursors = mutableMapOf<String, Int>()
    private val seenSeqs = mutableMapOf<String, MutableSet<Int>>()
    private val authResumed = mutableSetOf<String>()
    private val clarificationSlots = mutableMapOf<String, List<MissingSlot>>()

    private sealed interface PendingAction {
        data class Submit(
            val text: String,
            val createRequest: CreateSessionRequest,
            val turnRequest: SubmitTurnRequest,
            var userItemAdded: Boolean = false,
        ) : PendingAction

        data class Poll(val turnId: String) : PendingAction
        data class Clarify(val turnId: String, val request: ResumeClarificationRequest, var userItemAdded: Boolean = false) :
            PendingAction
        data class Auth(val turnId: String, val request: ResumeAuthRequest) : PendingAction
        data class Cancel(val turnId: String, val request: CancelTurnRequest) : PendingAction

        data class Confirm(val proposalId: String, val request: ConfirmProposalRequest) : PendingAction
        data class OpenSession(val sessionId: String) : PendingAction
        data object LoadSessions : PendingAction
    }

    // ---- panel / context ----------------------------------------------------------------------

    fun setPageLabel(label: String) {
        if (_state.value.pageLabel != label) _state.update { it.copy(pageLabel = label) }
    }

    fun setPanelOpen(open: Boolean) {
        _state.update { it.copy(panelOpen = open) }
        if (open) {
            val turn = _state.value.turn
            if (turn != null && pollJob?.isActive != true && !shouldStopPolling(turn.state)) startPolling(turn.turnId)
        }
    }

    fun markEntrancePlayed(key: String) {
        if (key !in _state.value.playedEntrances) _state.update { it.copy(playedEntrances = it.playedEntrances + key) }
    }

    fun dismissBanner() = _state.update { it.copy(banner = null, notice = null) }

    // ---- submit -------------------------------------------------------------------------------

    fun submit(text: String, uiContext: UiContext?) {
        val trimmed = text.trim()
        val current = _state.value
        if (trimmed.isEmpty() || current.composer == ComposerMode.Running) return
        lastSubmittedText = trimmed
        val turn = current.turn
        if (current.composer is ComposerMode.Clarification && turn != null) {
            val action = PendingAction.Clarify(
                turnId = turn.turnId,
                request = ResumeClarificationRequest(
                    clientRequestId = newId(),
                    expectedStateRevision = turn.stateRevision,
                    text = trimmed,
                ),
            )
            pending = action
            scope.launch { runClarify(action, trimmed) }
            return
        }
        val action = PendingAction.Submit(
            text = trimmed,
            createRequest = CreateSessionRequest(
                clientRequestId = newId(),
                title = trimmed.take(SESSION_TITLE_LENGTH),
                uiContext = uiContext,
            ),
            turnRequest = SubmitTurnRequest(clientRequestId = newId(), text = trimmed, uiContext = uiContext),
        )
        pending = action
        scope.launch { runSubmit(action) }
    }

    private suspend fun runSubmit(action: PendingAction.Submit) {
        pollJob?.cancel()
        if (!action.userItemAdded) {
            action.userItemAdded = true
            appendItem(UserTextItem("u:${action.turnRequest.clientRequestId}", action.text, animateEntrance = true))
        }
        _state.update { it.copy(banner = null, notice = null, composer = ComposerMode.Running) }
        var sessionId = _state.value.currentSessionId
        if (sessionId == null) {
            when (val created = repository.createSession(action.createRequest)) {
                is AgentApiResult.Success -> {
                    sessionId = created.value.session.sessionId
                    _state.update { it.copy(currentSessionId = sessionId) }
                }
                is AgentApiResult.Failure -> return fail(created, canRetry = true)
            }
        }
        when (val accepted = repository.submitTurn(sessionId, action.turnRequest)) {
            is AgentApiResult.Success -> {
                val v = accepted.value
                pending = null
                _state.update {
                    it.copy(
                        turn = TurnPublicStatus(
                            turnId = v.turnId,
                            sessionId = sessionId,
                            state = v.state,
                            stateRevision = v.stateRevision,
                            step = TurnStep.ACCEPTED,
                            contextVersion = 0,
                            executionAssigned = false,
                        ),
                    )
                }
                startPolling(v.turnId)
            }
            is AgentApiResult.Failure -> fail(accepted, canRetry = true)
        }
    }

    private suspend fun runClarify(action: PendingAction.Clarify, text: String) {
        if (!action.userItemAdded) {
            action.userItemAdded = true
            appendItem(UserTextItem("u:${action.request.clientRequestId}", text, animateEntrance = true))
        }
        _state.update { it.copy(banner = null, notice = null, composer = ComposerMode.Running) }
        when (val result = repository.resumeClarification(action.turnId, action.request)) {
            is AgentApiResult.Success -> {
                pending = null
                _state.update { s ->
                    s.copy(turn = s.turn?.copy(state = result.value.state, stateRevision = result.value.stateRevision))
                }
                startPolling(action.turnId)
            }
            is AgentApiResult.Failure -> fail(result, canRetry = true)
        }
    }

    // ---- retry / cancel -----------------------------------------------------------------------

    /** Re-sends the very same request object (same `client_request_id`) that last failed. */
    fun retry() {
        val action = pending ?: return
        _state.update { it.copy(banner = null) }
        scope.launch {
            when (action) {
                is PendingAction.Submit -> runSubmit(action)
                is PendingAction.Clarify -> runClarify(action, lastSubmittedText.orEmpty())
                is PendingAction.Poll -> startPolling(action.turnId)
                is PendingAction.Auth -> runAuthResume(action)
                is PendingAction.Cancel -> runCancel(action)
                is PendingAction.Confirm -> runConfirm(action)
                is PendingAction.OpenSession -> openSessionInternal(action)
                PendingAction.LoadSessions -> loadSessionsInternal()
            }
        }
    }

    /** Retry for a retryable `error` event: a new user action, so it gets a new request id. */
    fun retryLastMessage(uiContext: UiContext?) {
        val text = lastSubmittedText ?: return
        submit(text, uiContext)
    }

    fun cancel() {
        val turn = _state.value.turn ?: return
        if (turn.state.isTerminal) return
        val action = PendingAction.Cancel(
            turn.turnId,
            CancelTurnRequest(clientRequestId = newId(), expectedStateRevision = turn.stateRevision),
        )
        pending = action
        scope.launch { runCancel(action) }
    }

    private suspend fun runCancel(action: PendingAction.Cancel) {
        when (val result = repository.cancelTurn(action.turnId, action.request)) {
            is AgentApiResult.Success -> {
                pending = null
                val turn = result.value.turn
                _state.update {
                    it.copy(turn = turn, notice = AgentStatusCopy.cancelNotice(result.value.result), banner = null)
                }
                applyTurnToComposer(turn)
                if (!shouldStopPolling(turn.state)) startPolling(turn.turnId)
            }
            is AgentApiResult.Failure -> fail(result, canRetry = true)
        }
    }

    // ---- confirm ------------------------------------------------------------------------------

    /**
     * Confirms a backend draft. The request object (and its `client_request_id`) is created once per
     * tap, so a retry never dispatches a second execution.
     */
    fun confirm(proposalId: String) {
        val current = _state.value
        if (current.confirmingProposalId != null) return
        if (proposalId in current.submittedProposals) return
        val card = current.cards[proposalId] as? ConfirmableProposalCard ?: return
        val action = PendingAction.Confirm(
            proposalId = proposalId,
            request = ConfirmProposalRequest(
                clientRequestId = newId(),
                commandDigest = card.commandDigest,
                confirmationNonce = card.confirmationNonce,
                expectedProposalRevision = card.revision,
            ),
        )
        pending = action
        scope.launch { runConfirm(action) }
    }

    private suspend fun runConfirm(action: PendingAction.Confirm) {
        _state.update {
            it.copy(
                confirmingProposalId = action.proposalId,
                confirmUnavailable = it.confirmUnavailable - action.proposalId,
                banner = null,
                notice = null,
            )
        }
        when (val result = repository.confirmProposal(action.proposalId, action.request)) {
            is AgentApiResult.Success -> {
                pending = null
                when (val outcome = result.value) {
                    is ConfirmProposalOutcome.ExecutionAccepted -> onExecutionAccepted(action.proposalId, outcome)
                    is ConfirmProposalOutcome.Unavailable -> _state.update {
                        it.copy(
                            confirmingProposalId = null,
                            confirmUnavailable = it.confirmUnavailable + action.proposalId,
                        )
                    }
                }
            }
            is AgentApiResult.Failure -> {
                _state.update { it.copy(confirmingProposalId = null) }
                fail(result, canRetry = true)
            }
        }
    }

    /** 202: one execution was dispatched. Follow the turn from the returned cursor, never assume success. */
    private fun onExecutionAccepted(proposalId: String, outcome: ConfirmProposalOutcome.ExecutionAccepted) {
        val value = outcome.value
        val turn = value.turn
        cursors[turn.turnId] = maxOf(cursors[turn.turnId] ?: 0, value.eventCursor)
        _state.update {
            it.copy(
                confirmingProposalId = null,
                submittedProposals = it.submittedProposals + proposalId,
                turn = turn,
            )
        }
        upsertReceipt(proposalId, turn.turnId, value.execution.executionId, value.execution.proposalRevision, turn)
        applyTurnToComposer(turn)
        if (!shouldStopPolling(turn.state)) startPolling(turn.turnId)
    }

    // ---- polling ------------------------------------------------------------------------------

    private fun startPolling(turnId: String) {
        pollJob?.cancel()
        pollJob = scope.launch { pollLoop(turnId) }
    }

    private suspend fun pollLoop(turnId: String) {
        while (true) {
            val after = cursors[turnId] ?: 0
            val response = when (val r = repository.pollEvents(turnId, after)) {
                is AgentApiResult.Success -> r.value
                is AgentApiResult.Failure -> {
                    pending = PendingAction.Poll(turnId)
                    return fail(r, canRetry = true)
                }
            }
            applyPoll(turnId, response)
            val turn = response.turn
            if (turn.waitReason == WaitReason.AUTH_REQUIRED && !turn.state.isTerminal) {
                if (authResumed.add(turnId)) {
                    val action = PendingAction.Auth(
                        turnId,
                        ResumeAuthRequest(clientRequestId = newId(), expectedStateRevision = turn.stateRevision),
                    )
                    pending = action
                    if (!runAuthResume(action, restartPolling = false)) return
                    continue
                }
                return
            }
            if (shouldStopPolling(turn.state)) return
            if (!response.hasMore) pollDelay(POLL_IDLE_DELAY_MS)
        }
    }

    private suspend fun runAuthResume(action: PendingAction.Auth, restartPolling: Boolean = true): Boolean =
        when (val result = repository.resumeAuth(action.turnId, action.request)) {
            is AgentApiResult.Success -> {
                pending = null
                _state.update { s ->
                    s.copy(turn = s.turn?.copy(state = result.value.state, stateRevision = result.value.stateRevision))
                }
                if (restartPolling) startPolling(action.turnId)
                true
            }
            is AgentApiResult.Failure -> {
                fail(result, canRetry = true)
                false
            }
        }

    private fun shouldStopPolling(state: TurnState): Boolean = when (state) {
        TurnState.WAIT_INPUT, TurnState.WAIT_CONFIRM, TurnState.COMPLETED, TurnState.CANCELLED,
        TurnState.FAILED, TurnState.UNKNOWN,
        -> true
        else -> false
    }

    private fun applyPoll(turnId: String, response: PollEventsResponse) {
        val newItems = collectItems(turnId, response.events, live = true)
        cursors[turnId] = maxOf(cursors[turnId] ?: 0, response.nextAfterSeq)
        _state.update { s ->
            s.copy(
                items = (s.items + newItems.filter { item -> item !is ProposalItem || s.items.none { it.sameProposal(item) } })
                    .map { refreshedReceipt(it, response.turn) },
                cards = mergeCards(s.cards, response.proposalCards),
                turn = response.turn,
            )
        }
        applyTurnToComposer(response.turn)
    }

    private fun TranscriptItem.sameProposal(other: ProposalItem) =
        this is ProposalItem && proposalId == other.proposalId

    /** Turns new events (not yet seen by seq) into transcript items. */
    private fun collectItems(turnId: String, events: List<AgentEvent>, live: Boolean): List<TranscriptItem> {
        val seen = seenSeqs.getOrPut(turnId) { mutableSetOf() }
        val out = mutableListOf<TranscriptItem>()
        for (event in events.sortedBy { it.seq }) {
            if (!seen.add(event.seq)) continue
            val key = "e:$turnId:${event.seq}"
            when (event) {
                is MessageEvent -> out += AssistantMessageItem(key, event.payload.text, event.simulation, live)
                is ClarificationEvent -> {
                    clarificationSlots[turnId] = event.payload.missingSlots
                    out += ClarificationItem(key, event.payload.prompt, live)
                }
                is ProposalEvent -> if (out.none { it is ProposalItem && it.proposalId == event.payload.proposalId }) {
                    out += ProposalItem(key, event.payload.proposalId, live)
                }
                is ExecutionResultEvent -> out += ExecutionResultItem(
                    key,
                    AgentStatusCopy.executionLine(event.payload.resolution, event.payload.resultSummary),
                )
                is ErrorEvent -> out += ErrorItem(
                    key,
                    AgentErrorMessages.forEvent(event.payload),
                    event.payload.retryable,
                )
                else -> Unit // status and unknown events carry no transcript content
            }
        }
        return out
    }

    private fun mergeCards(existing: Map<String, ProposalCard>, incoming: List<ProposalCard>): Map<String, ProposalCard> {
        if (incoming.isEmpty()) return existing
        val merged = existing.toMutableMap()
        for (card in incoming) {
            val id = card.proposalIdOrNull() ?: continue
            val old = merged[id]
            if (old == null || card.revisionOrZero() >= old.revisionOrZero()) merged[id] = card
        }
        return merged
    }

    private fun applyTurnToComposer(turn: TurnPublicStatus) {
        val mode = when {
            !shouldStopPolling(turn.state) -> ComposerMode.Running
            turn.state == TurnState.WAIT_INPUT && turn.waitReason != WaitReason.AUTH_REQUIRED ->
                ComposerMode.Clarification(clarificationSlots[turn.turnId].orEmpty())
            else -> ComposerMode.Normal
        }
        _state.update { it.copy(composer = mode) }
    }

    // ---- history ------------------------------------------------------------------------------

    fun openHistory() {
        _state.update { it.copy(view = AgentPanelView.History) }
        scope.launch { loadSessionsInternal() }
    }

    fun closeHistory() = _state.update { it.copy(view = AgentPanelView.Chat) }

    private suspend fun loadSessionsInternal() {
        _state.update { it.copy(sessionsLoading = true, banner = null) }
        when (val r = repository.listSessions()) {
            is AgentApiResult.Success -> {
                pending = null
                _state.update { it.copy(sessions = r.value.items, sessionsLoading = false) }
            }
            is AgentApiResult.Failure -> {
                _state.update { it.copy(sessionsLoading = false) }
                pending = PendingAction.LoadSessions
                fail(r, canRetry = true)
            }
        }
    }

    fun newConversation() {
        pollJob?.cancel()
        resetTranscript()
        _state.update { it.copy(currentSessionId = null, view = AgentPanelView.Chat, banner = null, notice = null) }
    }

    fun openSession(sessionId: String) {
        val action = PendingAction.OpenSession(sessionId)
        pending = action
        scope.launch { openSessionInternal(action) }
    }

    private suspend fun openSessionInternal(action: PendingAction.OpenSession) {
        pollJob?.cancel()
        _state.update { it.copy(banner = null, notice = null, sessionsLoading = true) }
        val detail = when (val r = repository.getSession(action.sessionId)) {
            is AgentApiResult.Success -> r.value
            is AgentApiResult.Failure -> {
                _state.update { it.copy(sessionsLoading = false) }
                return fail(r, canRetry = true)
            }
        }
        resetTranscript()
        val items = mutableListOf<TranscriptItem>()
        var cards: Map<String, ProposalCard> = mergeCards(emptyMap(), detail.proposalCards)
        var lastTurn: TurnPublicStatus? = null
        for (turnSummary in detail.turns) {
            var after = 0
            while (true) {
                val page = when (val r = repository.pollEvents(turnSummary.turnId, after)) {
                    is AgentApiResult.Success -> r.value
                    is AgentApiResult.Failure -> {
                        _state.update { it.copy(sessionsLoading = false) }
                        return fail(r, canRetry = true)
                    }
                }
                for (item in collectItems(turnSummary.turnId, page.events, live = false)) {
                    if (item !is ProposalItem || items.none { it.sameProposal(item) }) items += item
                }
                cards = mergeCards(cards, page.proposalCards)
                lastTurn = page.turn
                val next = maxOf(after, page.nextAfterSeq)
                cursors[turnSummary.turnId] = next
                if (!page.hasMore || next == after) break
                after = next
            }
        }
        pending = null
        _state.update {
            it.copy(
                currentSessionId = detail.session.sessionId,
                items = items,
                cards = cards,
                turn = lastTurn,
                view = AgentPanelView.Chat,
                sessionsLoading = false,
            )
        }
        lastTurn?.let { turn ->
            applyTurnToComposer(turn)
            if (!shouldStopPolling(turn.state)) startPolling(turn.turnId)
        } ?: _state.update { it.copy(composer = ComposerMode.Normal) }
    }

    // ---- helpers ------------------------------------------------------------------------------

    private fun resetTranscript() {
        cursors.clear()
        seenSeqs.clear()
        authResumed.clear()
        clarificationSlots.clear()
        pending = null
        _state.update {
            it.copy(
                items = emptyList(),
                cards = emptyMap(),
                turn = null,
                composer = ComposerMode.Normal,
                confirmingProposalId = null,
                confirmUnavailable = emptySet(),
                submittedProposals = emptySet(),
            )
        }
    }

    private fun appendItem(item: TranscriptItem) = _state.update { it.copy(items = it.items + item) }

    /** Receipts follow their turn's state, including a transition into RECOVERING. */
    private fun refreshedReceipt(item: TranscriptItem, turn: TurnPublicStatus): TranscriptItem =
        if (item is ExecutionReceiptItem && item.turnId == turn.turnId) {
            item.copy(state = turn.state, resolution = turn.executionResolution)
        } else {
            item
        }

    private fun upsertReceipt(
        proposalId: String,
        turnId: String,
        executionId: String,
        proposalRevision: Int,
        turn: TurnPublicStatus,
    ) {
        val key = "receipt:$proposalId"
        val item = ExecutionReceiptItem(
            key = key,
            turnId = turnId,
            executionId = executionId,
            proposalRevision = proposalRevision,
            state = turn.state,
            resolution = turn.executionResolution,
        )
        _state.update { s ->
            val index = s.items.indexOfFirst { it.key == key }
            s.copy(
                items = if (index >= 0) {
                    s.items.toMutableList().also { it[index] = item }
                } else {
                    s.items + item
                },
            )
        }
    }

    private fun fail(failure: AgentApiResult.Failure, canRetry: Boolean) {
        _state.update { s ->
            val turnStillActive = s.turn?.let { !shouldStopPolling(it.state) } == true
            s.copy(
                banner = AgentBanner(AgentErrorMessages.forFailure(failure), canRetry),
                // A failed send must leave the user able to type again; an active turn keeps 停止 available.
                composer = if (s.composer == ComposerMode.Running && !turnStillActive) restoredComposer(s) else s.composer,
            )
        }
    }

    /** After a failed call the user must be able to type again (or press 重试). */
    private fun restoredComposer(s: AgentUiState): ComposerMode {
        val turn = s.turn
        return if (turn != null && turn.state == TurnState.WAIT_INPUT && turn.waitReason != WaitReason.AUTH_REQUIRED) {
            ComposerMode.Clarification(clarificationSlots[turn.turnId].orEmpty())
        } else {
            ComposerMode.Normal
        }
    }

    override fun onCleared() {
        stop()
    }

    /** Stops polling and every in-flight call. Called when the ViewModel is cleared. */
    fun stop() {
        pollJob?.cancel()
        scope.cancel()
    }

    class Factory(
        private val repository: AgentRepository,
        private val newId: () -> String = { UUID.randomUUID().toString() },
        private val dispatcher: CoroutineDispatcher = Dispatchers.Main.immediate,
        private val pollDelay: suspend (Long) -> Unit = { delay(it) },
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            AgentAssistantViewModel(repository, newId, dispatcher, pollDelay) as T
    }
}

private fun ProposalCard.proposalIdOrNull(): String? = when (this) {
    is SimulationProposalCard -> proposalId
    is ConfirmableProposalCard -> proposalId
    is InactiveProposalCard -> proposalId
    else -> null // unknown cards are skipped
}

private fun ProposalCard.revisionOrZero(): Int = when (this) {
    is SimulationProposalCard -> revision
    is ConfirmableProposalCard -> revision
    is InactiveProposalCard -> revision
    else -> 0
}
