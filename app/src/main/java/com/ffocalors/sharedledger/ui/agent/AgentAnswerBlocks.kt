package com.ffocalors.sharedledger.ui.agent

/** A money figure exactly as the server wrote it; never rounded, regrouped or reinterpreted. */
internal data class Money(val amount: String, val currency: String)

/** One line under an expense: who paid or who shares, and how much. */
internal data class ExpenseLine(val role: String, val name: String, val amount: Money?)

internal enum class FactKind { Refund, Prepayment }

/** A single row inside a ledger sheet. */
internal sealed interface LedgerEntry {
    data class Debt(val debtor: String, val creditor: String, val amount: Money?, val note: String?) : LedgerEntry
    data class Expense(
        val title: String,
        val amount: Money?,
        val base: Money?,
        val lines: List<ExpenseLine>,
    ) : LedgerEntry

    data class Activity(val name: String, val details: List<String>) : LedgerEntry
    data class Fact(val kind: FactKind, val title: String, val amount: Money?, val details: List<String>) : LedgerEntry

    /** A statement about the result itself ("没有符合条件的记录", "列表可能不完整"). */
    data class Note(val text: String, val incomplete: Boolean) : LedgerEntry
}

/** What a reply is made of, in reading order. */
internal sealed interface AnswerSegment {
    /** Free text the parser did not recognise. Nothing is ever dropped: unknown lines land here. */
    data class Prose(val text: String) : AnswerSegment

    /** An optional header line plus record rows that render as one ledger sheet. */
    data class Ledger(val lead: String?, val partial: Boolean, val entries: List<LedgerEntry>) : AnswerSegment

    /** An "empty result" or "incomplete result" statement standing on its own. */
    data class Notice(val text: String, val incomplete: Boolean) : AnswerSegment
}

/**
 * Splits the Agent's templated answer text into segments. The formats come from the server's grounded
 * renderers (`p2_harness`, `p2_runtime`); anything that does not match falls back to [AnswerSegment.Prose].
 */
internal object AnswerBlocks {
    private val moneyAnywhere = Regex("""(-?\d+(?:\.\d+)?)\s+([A-Z]{3})""")
    private val debtV1 = Regex("""^债务记录[：:]\s*(.+?)\s*→\s*(.+?)\s*[，,]\s*(.+)$""")
    private val debtV3 = Regex("""^欠款方向\s+(.+?)\s*→\s*(.+?)\s*[：:]\s*(.+)$""")
    private val expenseV1 = Regex("""^消费记录[：:]\s*(.+?)\s+[—–-]+\s+(.+)$""")
    private val expenseV3 = Regex("""^消费「(.+?)」\s*[：:]\s*(.+)$""")
    private val subLineV1 = Regex("""^(付款|分摊)\s+(.+?)\s*[：:]\s*(.+)$""")
    private val subLineV3 = Regex("""^(\S+)\s+(.+?)\s*[：:]\s*(.+)$""")
    private val activityV1 = Regex("""^活动[：:]\s*(.+?)（(.+?)）$""")
    private val activityListed = Regex("""^(.+?)（(.+)）$""")
    private val factTitle = Regex("""^[^\s：:]+""")
    private val baseInParens = Regex("""（基准\s+(-?\d+(?:\.\d+)?)\s+([A-Z]{3})）""")

    fun parseMoney(text: String): Money? =
        moneyAnywhere.find(text)?.let { Money(it.groupValues[1], it.groupValues[2]) }

    fun parse(text: String): List<AnswerSegment> {
        val segments = mutableListOf<AnswerSegment>()
        val prose = StringBuilder()
        val entries = mutableListOf<LedgerEntry>()
        var lead: String? = null
        var leadPartial = false
        var activityMode = false

        fun flushProse() {
            val value = prose.toString().trim()
            if (value.isNotEmpty()) segments += AnswerSegment.Prose(value)
            prose.clear()
        }

        fun flushLedger() {
            if (entries.isNotEmpty()) {
                segments += AnswerSegment.Ledger(lead, leadPartial, entries.toList())
            } else if (lead != null) {
                // A header with nothing under it is just a sentence.
                if (prose.isNotEmpty()) prose.append('\n')
                prose.append(lead).append('：')
            }
            entries.clear()
            lead = null
            leadPartial = false
            activityMode = false
        }

        var seenContent = false
        for (raw in text.split('\n')) {
            val trimmed = raw.trim()
            val line = if (trimmed.startsWith("- ")) trimmed.substring(2).trim() else trimmed
            if (line.isEmpty()) {
                flushLedger()
                flushProse()
                continue
            }
            val isFirst = !seenContent
            seenContent = true

            if (isNotice(line)) {
                val incomplete = line.contains("不完整") || line.contains("不能据此")
                if (lead != null) {
                    entries += LedgerEntry.Note(line, incomplete)
                } else {
                    flushLedger()
                    flushProse()
                    segments += AnswerSegment.Notice(line, incomplete)
                }
                continue
            }

            // 付款 / 分摊 sub-lines belong to the expense row right above them.
            val sub = subLineV1.find(line)
            val last = entries.lastOrNull()
            if (sub != null && last is LedgerEntry.Expense) {
                val added = ExpenseLine(sub.groupValues[1], sub.groupValues[2], parseMoney(sub.groupValues[3]))
                entries[entries.lastIndex] = last.copy(lines = last.lines + added)
                continue
            }

            val entry = entryOf(line, activityMode)
            if (entry != null) {
                flushProse()
                entries += entry
                continue
            }

            if (isLead(line, isFirst)) {
                flushLedger()
                flushProse()
                lead = line.trimEnd('：', ':')
                leadPartial = line.contains("部分") || line.contains("不完整")
                activityMode = line.contains("活动")
                continue
            }

            // Plain text closes any open sheet so prose never gets glued into rows.
            flushLedger()
            if (prose.isNotEmpty()) prose.append('\n')
            prose.append(line)
        }
        flushLedger()
        flushProse()
        return segments
    }

    // ---- line classification -------------------------------------------------------------------

    private fun isNotice(line: String): Boolean =
        line.startsWith("当前查询范围内没有") || line.startsWith("本次查询结果不完整")

    private fun isLead(line: String, isFirst: Boolean): Boolean {
        if (!(line.endsWith("：") || line.endsWith(":"))) return false
        return isFirst || line.contains("已验证") || line.contains("可信") || line.contains("部分") || line.contains("不完整")
    }

    private fun entryOf(line: String, activityMode: Boolean): LedgerEntry? {
        debtV1.find(line)?.let { m ->
            return LedgerEntry.Debt(m.groupValues[1], m.groupValues[2], parseMoney(m.groupValues[3]), null)
        }
        debtV3.find(line)?.let { m ->
            val parts = splitDetails(m.groupValues[3])
            val amount = parts.firstOrNull()?.let(::parseMoney)
            val note = (if (amount == null) parts else parts.drop(1)).joinToString("；").ifEmpty { null }
            return LedgerEntry.Debt(m.groupValues[1], m.groupValues[2], amount, note)
        }
        expenseV1.find(line)?.let { m ->
            return LedgerEntry.Expense(m.groupValues[1], parseMoney(m.groupValues[2]), null, emptyList())
        }
        expenseV3.find(line)?.let { m ->
            val parts = splitDetails(m.groupValues[2])
            val head = parts.firstOrNull().orEmpty()
            val base = baseInParens.find(head)?.let { Money(it.groupValues[1], it.groupValues[2]) }
            val amount = parseMoney(head.replace(baseInParens, ""))
            return LedgerEntry.Expense(m.groupValues[1], amount, base, parts.drop(1).map(::expenseLineV3))
        }
        activityV1.find(line)?.let { m ->
            return LedgerEntry.Activity(m.groupValues[1], splitDetails(m.groupValues[2]))
        }
        if (line.startsWith("退款") || line.startsWith("预存")) return factOf(line)
        if (activityMode) {
            activityListed.find(line)?.let { m ->
                return LedgerEntry.Activity(m.groupValues[1], splitDetails(m.groupValues[2]))
            }
        }
        return null
    }

    private fun splitDetails(text: String): List<String> =
        text.split('；', ';').map { it.trim() }.filter { it.isNotEmpty() }

    private fun expenseLineV3(part: String): ExpenseLine {
        val m = subLineV3.find(part) ?: return ExpenseLine("", part, null)
        val role = when (m.groupValues[1]) {
            "payer" -> "付款"
            "split" -> "分摊"
            else -> m.groupValues[1]
        }
        return ExpenseLine(role, m.groupValues[2], parseMoney(m.groupValues[3].replace(baseInParens, "")))
    }

    private fun factOf(line: String): LedgerEntry.Fact {
        val title = factTitle.find(line)?.value ?: line
        val parts = splitDetails(line.removePrefix(title).trimStart('：', ':', ' '))
        val first = parts.firstOrNull().orEmpty()
        val match = moneyAnywhere.find(first)
        val amount = match?.let { Money(it.groupValues[1], it.groupValues[2]) }
        val details = mutableListOf<String>()
        if (match != null) {
            val remainder = first.removeRange(match.range).trim('：', ':', ' ')
            if (remainder.isNotEmpty()) details += remainder
        } else if (first.isNotEmpty()) {
            details += first
        }
        details += parts.drop(1)
        val kind = if (title.startsWith("退款")) FactKind.Refund else FactKind.Prepayment
        return LedgerEntry.Fact(kind, title, amount, details)
    }
}
