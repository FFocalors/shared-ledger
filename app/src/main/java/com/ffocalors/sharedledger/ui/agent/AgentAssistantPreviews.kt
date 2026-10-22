package com.ffocalors.sharedledger.ui.agent

import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.runtime.Composable
import com.ffocalors.sharedledger.data.agent.CanonicalEqualSplit
import com.ffocalors.sharedledger.data.agent.CanonicalPayment
import com.ffocalors.sharedledger.data.agent.ConfirmableProposalCard
import com.ffocalors.sharedledger.data.agent.ExpenseAmountChange
import com.ffocalors.sharedledger.data.agent.AmountField
import com.ffocalors.sharedledger.data.agent.ExpensePaymentsChange
import com.ffocalors.sharedledger.data.agent.ExpensePreview
import com.ffocalors.sharedledger.data.agent.ExpenseSnapshot
import com.ffocalors.sharedledger.data.agent.ExpenseSplitChange
import com.ffocalors.sharedledger.data.agent.ExpenseTitleChange
import com.ffocalors.sharedledger.data.agent.InactiveProposalCard
import com.ffocalors.sharedledger.data.agent.MissingSlot
import com.ffocalors.sharedledger.data.agent.ProposalCard
import com.ffocalors.sharedledger.data.agent.ProposalMode
import com.ffocalors.sharedledger.data.agent.ProposalOperation
import com.ffocalors.sharedledger.data.agent.ProposalStatus
import com.ffocalors.sharedledger.data.agent.SimulationProposalCard
import com.ffocalors.sharedledger.data.agent.TurnState
import com.ffocalors.sharedledger.data.agent.TurnStep
import com.ffocalors.sharedledger.data.agent.TurnPublicStatus
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme

private const val XIAO_WANG = "p-1"
private const val XIAO_LI = "p-2"
private const val XIAO_ZHANG = "p-3"
private const val XIAO_ZHAO = "p-4"

internal val PreviewNames = AgentNameResolver(
    participants = mapOf(XIAO_WANG to "小王", XIAO_LI to "小李", XIAO_ZHANG to "小张", XIAO_ZHAO to "小赵"),
    ledgerUnits = mapOf("lu-1" to "周末露营"),
)

private fun previewPreview(): ExpensePreview {
    val payments = listOf(CanonicalPayment("750.00", XIAO_WANG))
    val split = CanonicalEqualSplit(listOf(XIAO_WANG, XIAO_LI, XIAO_ZHANG, XIAO_ZHAO))
    return ExpensePreview(
        activityFinancialVersion = "7",
        after = ExpenseSnapshot(
            baseAmount = "750.00",
            expenseVersion = "1",
            financialLocked = false,
            ledgerUnitId = "lu-1",
            originalAmount = "750.00",
            originalCurrency = "CNY",
            paymentAllocations = payments,
            split = split,
            title = "烧烤",
        ),
        changes = listOf(
            ExpenseTitleChange(after = "烧烤"),
            ExpenseAmountChange(AmountField.ORIGINAL_AMOUNT, after = "750.00"),
            ExpensePaymentsChange(after = payments),
            ExpenseSplitChange(after = split),
        ),
        generatedAt = "2026-10-22T08:00:00Z",
        simulation = false,
        summary = "新增账目：烧烤",
    )
}

private val backendCard: ProposalCard = ConfirmableProposalCard(
    proposalId = "pr-1",
    revision = 1,
    operation = ProposalOperation.EXPENSE_CREATE,
    preview = previewPreview(),
    commandDigest = "digest",
    confirmationNonce = "nonce",
    expiresAt = "2026-10-22T09:00:00Z",
)

private val simulationCard: ProposalCard = SimulationProposalCard(
    proposalId = "pr-2",
    revision = 1,
    operation = ProposalOperation.EXPENSE_CREATE,
    preview = previewPreview().copy(simulation = true),
)

private val inactiveCard: ProposalCard = InactiveProposalCard(
    proposalId = "pr-3",
    revision = 1,
    operation = ProposalOperation.EXPENSE_CREATE,
    mode = ProposalMode.BACKEND,
    status = ProposalStatus.SUPERSEDED,
    simulation = false,
    preview = previewPreview(),
)

private val runningTurn = TurnPublicStatus(
    turnId = "t-1",
    sessionId = "s-1",
    state = TurnState.RUNNING,
    stateRevision = 2,
    step = TurnStep.TOOL_READ,
    contextVersion = 1,
    executionAssigned = false,
)

private fun conversation(card: ProposalCard, turn: TurnPublicStatus? = null) = AgentUiState(
    pageLabel = "周末露营的账目",
    items = listOf(
        UserTextItem("u1", "昨天烧烤750，我付的，4个人平分"),
        AssistantMessageItem("a1", "好的，我按 4 人平分拟了一张草稿，你看看对不对。", simulation = false),
        ProposalItem("p1", "pr-1"),
    ),
    cards = mapOf("pr-1" to card),
    turn = turn,
)

internal fun agentPreviewState(name: String): AgentUiState? = when (name) {
    "empty" -> AgentUiState(pageLabel = "首页")
    "running" -> AgentUiState(
        pageLabel = "周末露营的账目",
        items = listOf(UserTextItem("u1", "这个活动现在谁还欠我钱？")),
        turn = runningTurn,
        composer = ComposerMode.Running,
    )
    "backend" -> conversation(backendCard).copy(
        turn = runningTurn.copy(state = TurnState.WAIT_CONFIRM, step = TurnStep.AWAITING_USER),
    )
    "simulation" -> conversation(simulationCard)
    "inactive" -> conversation(inactiveCard)
    "clarification" -> AgentUiState(
        pageLabel = "周末露营的账目",
        items = listOf(
            UserTextItem("u1", "昨天烧烤，我付的"),
            ClarificationItem("c1", "这笔烧烤一共花了多少钱？"),
        ),
        turn = runningTurn.copy(state = TurnState.WAIT_INPUT, step = TurnStep.AWAITING_USER),
        composer = ComposerMode.Clarification(listOf(MissingSlot.ORIGINAL_AMOUNT)),
    )
    "error" -> AgentUiState(
        pageLabel = "首页",
        items = listOf(UserTextItem("u1", "谁还欠我钱")),
        banner = AgentBanner("连不上助手服务，检查网络后点重试。", canRetry = true),
    )
    else -> null
}

@Composable
private fun PreviewSheet(state: AgentUiState) {
    SharedLedgerTheme {
        AgentAssistantContent(state = state, names = PreviewNames, actions = AgentSheetActions())
    }
}

@Preview(name = "空状态", showBackground = true, heightDp = 640)
@Composable
private fun AgentSheetEmptyPreview() = PreviewSheet(agentPreviewState("empty")!!)

@Preview(name = "思考中", showBackground = true, heightDp = 640)
@Composable
private fun AgentSheetRunningPreview() = PreviewSheet(agentPreviewState("running")!!)

@Preview(name = "真实草稿", showBackground = true, heightDp = 760)
@Composable
private fun AgentSheetBackendDraftPreview() = PreviewSheet(agentPreviewState("backend")!!)

@Preview(name = "演示草稿", showBackground = true, heightDp = 760)
@Composable
private fun AgentSheetSimulationDraftPreview() = PreviewSheet(agentPreviewState("simulation")!!)

@Preview(name = "已失效草稿", showBackground = true, heightDp = 760)
@Composable
private fun AgentSheetInactiveDraftPreview() = PreviewSheet(agentPreviewState("inactive")!!)

@Preview(name = "澄清", showBackground = true, heightDp = 640)
@Composable
private fun AgentSheetClarificationPreview() = PreviewSheet(agentPreviewState("clarification")!!)

@Preview(name = "错误提示", showBackground = true, heightDp = 640)
@Composable
private fun AgentSheetErrorPreview() = PreviewSheet(agentPreviewState("error")!!)
