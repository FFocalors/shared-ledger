package com.ffocalors.sharedledger.ui.agent

import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.runtime.Composable
import com.ffocalors.sharedledger.data.agent.CanonicalEqualSplit
import com.ffocalors.sharedledger.data.agent.CanonicalPayment
import com.ffocalors.sharedledger.data.agent.ConfirmableProposalCard
import com.ffocalors.sharedledger.data.agent.ExecutionResolution
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
    "records" -> AgentUiState(
        pageLabel = "周末露营的账目",
        items = listOf(
            UserTextItem("u1", "这个活动现在谁还欠我钱？"),
            AssistantMessageItem("a1", PreviewTexts.Debts, simulation = false),
            UserTextItem("u2", "烧烤那笔是怎么分的？"),
            AssistantMessageItem("a2", PreviewTexts.Expense, simulation = false),
            UserTextItem("u3", "我参加了哪些活动？"),
            AssistantMessageItem("a3", PreviewTexts.Activities, simulation = false),
        ),
    )
    // Same messages as "records", but flagged live so the streamed prose and ledger reveal play on open.
    "live" -> agentPreviewState("records")!!.let { s ->
        s.copy(items = s.items.map { if (it is AssistantMessageItem) it.copy(animateEntrance = true) else it })
    }
    "notices" -> AgentUiState(
        pageLabel = "首页",
        items = listOf(
            UserTextItem("u1", "看看我的活动"),
            AssistantMessageItem("a1", PreviewTexts.PartialActivities, simulation = false),
            UserTextItem("u2", "上个月有退款吗？"),
            AssistantMessageItem("a2", PreviewTexts.Empty, simulation = false),
            UserTextItem("u3", "现在能确认没有欠款吗？"),
            AssistantMessageItem("a3", PreviewTexts.Incomplete, simulation = false),
            UserTextItem("u4", "你能帮我做什么？"),
            AssistantMessageItem("a4", "我可以查你的活动、账目和谁欠谁，也可以按你的描述拟一张记账草稿，等你确认后再记入账本。", simulation = false),
        ),
    )
    "results" -> AgentUiState(
        pageLabel = "周末露营的账目",
        items = listOf(
            ExecutionReceiptItem("r1", "t-1", "exec-3f2a9c1e-0000", 1, TurnState.EXECUTING),
            ExecutionReceiptItem("r2", "t-2", "exec-7b10d4aa-0000", 1, TurnState.RECOVERING),
            ExecutionResultItem("x1", "已记账", ExecutionResolution.SUCCEEDED),
            ExecutionResultItem("x2", "没有记账：这个活动已归档", ExecutionResolution.REJECTED),
            ExecutionResultItem("x3", "已关闭", ExecutionResolution.CLOSED),
            ExecutionResultItem("x4", "正在核对结果", ExecutionResolution.UNKNOWN),
        ),
    )
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
            ClarificationItem(
                "c1", "这笔烧烤一共花了多少钱？",
                missingSlots = listOf(MissingSlot.ORIGINAL_AMOUNT, MissingSlot.SPLIT_PARTICIPANT_REFS),
            ),
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

/** The exact text shapes the Agent's grounded renderers produce, so previews show real output. */
internal object PreviewTexts {
    const val Debts = "根据当前可信记录：\n债务记录：小李 → 小王，150.00 CNY\n债务记录：小张 → 小王，224.5000 CNY"
    const val Expense = "根据当前可信记录：\n消费记录：烧烤 — 750.00 CNY\n付款 小王：750.00 CNY\n分摊 小李：375.00 CNY\n分摊 小王：375.00 CNY"
    const val Activities = "已验证的活动：\n- 周末露营（large；进行中；基准币种 CNY）\n- 10.8火锅（normal；已归档；基准币种 CNY）"
    const val PartialActivities = "以下是本次已验证的部分活动记录；查询或投影未完成，列表可能不完整：\n- 周末露营（large；进行中；基准币种 CNY）"
    const val Empty = "当前查询范围内没有符合条件的记录。"
    const val Incomplete = "本次查询结果不完整，当前没有可确认的记录；不能据此判断没有记录。"
}

@Composable
private fun PreviewSheet(state: AgentUiState) {
    SharedLedgerTheme {
        AgentAssistantContent(state = state, names = PreviewNames, actions = AgentSheetActions())
    }
}

@Preview(name = "账页", showBackground = true, heightDp = 860)
@Composable
private fun AgentSheetRecordsPreview() = PreviewSheet(agentPreviewState("records")!!)

@Preview(name = "提示与正文", showBackground = true, heightDp = 860)
@Composable
private fun AgentSheetNoticesPreview() = PreviewSheet(agentPreviewState("notices")!!)

@Preview(name = "回执与结果", showBackground = true, heightDp = 640)
@Composable
private fun AgentSheetResultsPreview() = PreviewSheet(agentPreviewState("results")!!)

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
