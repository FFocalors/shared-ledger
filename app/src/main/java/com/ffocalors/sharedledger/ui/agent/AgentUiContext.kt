package com.ffocalors.sharedledger.ui.agent

import com.ffocalors.sharedledger.data.agent.UiContext
import com.ffocalors.sharedledger.data.agent.UiEntityHint
import com.ffocalors.sharedledger.data.agent.UiEntityType
import com.ffocalors.sharedledger.data.agent.UiPageType
import java.math.BigDecimal

/** What the panel tells the Agent about the screen underneath, plus the "正在看：…" label. */
data class AgentPageContext(
    val uiContext: UiContext,
    /** Text after the "正在看：" prefix. */
    val label: String,
)

object AgentUiContextMapper {
    const val GENERIC_ACTIVITY_LABEL = "当前活动"

    /** Routes where the floating entry would sit on top of a text-entry keypad. */
    val HIDDEN_ENTRY_ROUTES: Set<String> = setOf(
        "new-expense",
        "transfer",
        "create-activity",
        "create-sub-activity",
        "join-activity",
    )

    /** `"new-expense/{activityId}?..."` -> `"new-expense"`. */
    fun routeKey(route: String?): String? =
        route?.substringBefore('?')?.substringBefore('/')?.takeIf { it.isNotBlank() }

    fun isEntryHidden(route: String?): Boolean = routeKey(route) in HIDDEN_ENTRY_ROUTES

    /**
     * @param route the nav route *pattern* of the current back-stack entry
     * @param args the entry's arguments by name (activityId, ledgerUnitId, expenseId)
     * @param activityName name of the activity if it is already loaded, else null
     */
    fun map(
        route: String?,
        args: Map<String, String?>,
        capturedAt: String,
        clientVersion: String,
        activityName: (String) -> String? = { null },
    ): AgentPageContext {
        val activityId = args["activityId"]?.takeIf { it.isNotBlank() }
        val ledgerUnitId = args["ledgerUnitId"]?.takeIf { it.isNotBlank() }
        val expenseId = args["expenseId"]?.takeIf { it.isNotBlank() }
        val activityLabel = activityId?.let { activityName(it)?.takeIf(String::isNotBlank) }
        val ofActivity: (String) -> String = { suffix ->
            if (activityLabel != null) "$activityLabel$suffix" else GENERIC_ACTIVITY_LABEL
        }

        fun context(
            page: UiPageType,
            withActivity: Boolean = true,
            withLedgerUnit: Boolean = false,
            selected: UiEntityHint? = null,
        ) = UiContext(
            capturedAt = capturedAt,
            clientVersion = clientVersion,
            pageType = page,
            activityId = activityId.takeIf { withActivity },
            ledgerUnitId = ledgerUnitId.takeIf { withLedgerUnit },
            selectedEntity = selected,
        )

        val (ui, label) = when (routeKey(route)) {
            "home" -> context(UiPageType.HOME, withActivity = false) to "首页"
            "normal-activity", "large-activity" ->
                context(UiPageType.ACTIVITY_OVERVIEW) to ofActivity("的账目")
            "ledger-unit" ->
                context(UiPageType.ACTIVITY_OVERVIEW, withLedgerUnit = true) to ofActivity("的账本")
            "expense-detail" -> context(
                UiPageType.EXPENSE_DETAIL,
                withLedgerUnit = true,
                selected = expenseId?.let { UiEntityHint(it, UiEntityType.EXPENSE) },
            ) to "一笔账目"
            "fund-records" -> context(UiPageType.EXPENSE_LIST, withLedgerUnit = true) to ofActivity("的资金记录")
            "final-settlement" -> context(UiPageType.SETTLEMENT) to ofActivity("的最终结算")
            "prepayment" -> context(UiPageType.PREPAYMENT) to ofActivity("的预存")
            "personal-info" -> context(UiPageType.SETTINGS, withActivity = false) to "个人信息"
            else -> context(UiPageType.HOME) to (if (activityId != null) ofActivity("") else "首页")
        }
        return AgentPageContext(ui, label)
    }
}

/** Display names the sheet can resolve from the already-loaded activity detail. */
data class AgentNameResolver(
    val participants: Map<String, String> = emptyMap(),
    val ledgerUnits: Map<String, String> = emptyMap(),
) {
    fun ledgerUnit(id: String): String = ledgerUnits[id]?.takeIf { it.isNotBlank() } ?: "另一个账本"

    /** Names joined with 、 when every id is known; otherwise a count. Never exposes an id. */
    fun participantGroup(ids: List<String>): String {
        if (ids.isEmpty()) return "0 位参与人"
        val names = ids.map { participants[it]?.takeIf(String::isNotBlank) }
        return if (names.all { it != null }) names.joinToString("、") else "${ids.size} 位参与人"
    }

    fun participant(id: String): String = participantGroup(listOf(id))

    /** "小王 750.00、小李 20.00", or "2 位参与人 共 770.00" when any name is unknown. */
    fun participantAmounts(entries: List<Pair<String, String>>): String {
        if (entries.isEmpty()) return "无"
        val names = entries.map { participants[it.first]?.takeIf(String::isNotBlank) }
        if (names.all { it != null }) {
            return entries.mapIndexed { i, e -> "${names[i]} ${e.second}" }.joinToString("、")
        }
        if (entries.size == 1) return "1 位参与人 ${entries[0].second}"
        val total = entries.fold(BigDecimal.ZERO) { acc, e -> acc + (e.second.toBigDecimalOrNull() ?: BigDecimal.ZERO) }
        return "${entries.size} 位参与人 共 ${total.toPlainString()}"
    }
}
