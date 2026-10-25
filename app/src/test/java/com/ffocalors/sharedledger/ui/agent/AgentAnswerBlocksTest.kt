package com.ffocalors.sharedledger.ui.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Uses the exact strings the Agent's grounded renderers produce (`p2_harness`, `p2_runtime`). */
class AgentAnswerBlocksTest {
    private fun parse(text: String) = AnswerBlocks.parse(text)

    private fun ledger(text: String): AnswerSegment.Ledger =
        parse(text).single() as AnswerSegment.Ledger

    @Test
    fun theScreenshotAnswerBecomesOneLedgerWithOneDebtRow() {
        val sheet = ledger("根据当前可信记录：\n债务记录：zhy → whr，1.3833 CNY")
        assertEquals("根据当前可信记录", sheet.lead)
        assertEquals(false, sheet.partial)
        assertEquals(
            listOf(LedgerEntry.Debt("zhy", "whr", Money("1.3833", "CNY"), null)),
            sheet.entries,
        )
    }

    @Test
    fun v1ExpenseCollectsItsPaymentAndSplitLines() {
        val sheet = ledger(
            "根据当前可信记录：\n消费记录：烧烤 — 750.00 CNY\n付款 小王：750.00 CNY\n分摊 小李：375.00 CNY\n分摊 小王：375.00 CNY",
        )
        val expense = sheet.entries.single() as LedgerEntry.Expense
        assertEquals("烧烤", expense.title)
        assertEquals(Money("750.00", "CNY"), expense.amount)
        assertEquals(
            listOf(
                ExpenseLine("付款", "小王", Money("750.00", "CNY")),
                ExpenseLine("分摊", "小李", Money("375.00", "CNY")),
                ExpenseLine("分摊", "小王", Money("375.00", "CNY")),
            ),
            expense.lines,
        )
    }

    @Test
    fun v1ActivityRow() {
        val sheet = ledger("根据当前可信记录：\n活动：周末露营（CNY）")
        assertEquals(listOf(LedgerEntry.Activity("周末露营", listOf("CNY"))), sheet.entries)
    }

    @Test
    fun v3ActivityListUsesTheHeaderToKnowItIsAnActivityList() {
        val sheet = ledger("已验证的活动：\n- 周末露营（large；进行中；基准币种 CNY）\n- 10.8火锅（normal；已归档；基准币种 CNY）")
        assertEquals("已验证的活动", sheet.lead)
        assertEquals(
            listOf(
                LedgerEntry.Activity("周末露营", listOf("large", "进行中", "基准币种 CNY")),
                LedgerEntry.Activity("10.8火锅", listOf("normal", "已归档", "基准币种 CNY")),
            ),
            sheet.entries,
        )
    }

    @Test
    fun partialHeaderIsFlaggedSoTheSheetCanWarn() {
        val sheet = ledger(
            "以下是本次已验证的部分活动记录；查询或投影未完成，列表可能不完整：\n- 周末露营（large；进行中）",
        )
        assertTrue(sheet.partial)
        assertTrue(sheet.lead!!.contains("不完整"))
    }

    @Test
    fun v3DebtKeepsTheBaseAmountAsANote() {
        val sheet = ledger("已验证的来源记录：\n- 欠款方向 zhy → whr：1.3833 CNY；基准 1.3833 CNY")
        assertEquals(
            listOf(LedgerEntry.Debt("zhy", "whr", Money("1.3833", "CNY"), "基准 1.3833 CNY")),
            sheet.entries,
        )
    }

    @Test
    fun v3DebtWithUnknownOriginalAmountKeepsTheTextInsteadOfAFigure() {
        val sheet = ledger("已验证的来源记录：\n- 欠款方向 zhy → whr：原币金额未知；基准 9.00 CNY")
        val debt = sheet.entries.single() as LedgerEntry.Debt
        assertNull(debt.amount)
        assertTrue(debt.note!!.contains("原币金额未知"))
        assertTrue(debt.note!!.contains("基准 9.00 CNY"))
    }

    @Test
    fun v3ExpenseTranslatesRolesAndKeepsSignedAmounts() {
        val sheet = ledger(
            "已验证的来源记录：\n- 消费「烧烤」：-750.00 CNY（基准 -750.00 CNY）；payer 小王: -750.00 CNY（基准 -750.00 CNY）；split 小李: 375.00 CNY（基准 375.00 CNY）",
        )
        val expense = sheet.entries.single() as LedgerEntry.Expense
        assertEquals(Money("-750.00", "CNY"), expense.amount)
        assertEquals(Money("-750.00", "CNY"), expense.base)
        assertEquals(
            listOf(
                ExpenseLine("付款", "小王", Money("-750.00", "CNY")),
                ExpenseLine("分摊", "小李", Money("375.00", "CNY")),
            ),
            expense.lines,
        )
    }

    @Test
    fun refundAndPrepaymentRowsBecomeFacts() {
        val sheet = ledger(
            "已验证的来源记录：\n- 预存账户余额 100.00 CNY；所有者 小王；保管人 小李\n- 退款：-12.00 CNY；基准 -12.00 CNY；关联状态 linked\n- 预存返还 5.00 CNY：custodian 小李 → 小王",
        )
        val balance = sheet.entries[0] as LedgerEntry.Fact
        assertEquals(FactKind.Prepayment, balance.kind)
        assertEquals("预存账户余额", balance.title)
        assertEquals(Money("100.00", "CNY"), balance.amount)
        assertEquals(listOf("所有者 小王", "保管人 小李"), balance.details)
        val refund = sheet.entries[1] as LedgerEntry.Fact
        assertEquals(FactKind.Refund, refund.kind)
        assertEquals(Money("-12.00", "CNY"), refund.amount)
        val returned = sheet.entries[2] as LedgerEntry.Fact
        assertEquals("预存返还", returned.title)
        assertEquals(listOf("custodian 小李 → 小王"), returned.details)
    }

    @Test
    fun emptyAndIncompleteStatementsStandAloneAsNotices() {
        assertEquals(
            listOf(AnswerSegment.Notice("当前查询范围内没有符合条件的活动记录。", incomplete = false)),
            parse("当前查询范围内没有符合条件的活动记录。"),
        )
        val incomplete = parse("本次查询结果不完整，当前没有可确认的记录；不能据此判断没有记录。").single() as AnswerSegment.Notice
        assertTrue(incomplete.incomplete)
    }

    @Test
    fun plainSentencesStayProse() {
        assertEquals(
            listOf(AnswerSegment.Prose("这个活动里目前没有人欠你钱。")),
            parse("这个活动里目前没有人欠你钱。"),
        )
        assertEquals(
            listOf(AnswerSegment.Prose("我已识别到一项提议意图；本阶段不会创建预览、确认卡或执行写入。")),
            parse("我已识别到一项提议意图；本阶段不会创建预览、确认卡或执行写入。"),
        )
    }

    @Test
    fun unknownLinesAreNeverDropped() {
        val segments = parse("根据当前可信记录：\n债务记录：zhy → whr，1.3833 CNY\n这是一条没有识别的策略说明。")
        assertEquals(2, segments.size)
        assertTrue(segments[0] is AnswerSegment.Ledger)
        assertEquals(AnswerSegment.Prose("这是一条没有识别的策略说明。"), segments[1])
    }

    @Test
    fun aHeaderWithNothingUnderItIsJustASentence() {
        assertEquals(
            listOf(AnswerSegment.Prose("根据当前可信记录：")),
            parse("根据当前可信记录："),
        )
    }

    @Test
    fun proseBeforeARecordKeepsReadingOrder() {
        val segments = parse("先说结论。\n债务记录：zhy → whr，1.00 CNY")
        assertEquals(AnswerSegment.Prose("先说结论。"), segments[0])
        val sheet = segments[1] as AnswerSegment.Ledger
        assertNull(sheet.lead)
        assertEquals(1, sheet.entries.size)
    }

    @Test
    fun noticeInsideASheetStaysInsideIt() {
        val sheet = ledger("已验证的活动：\n- 周末露营（large；进行中）\n本次查询结果不完整，当前没有可确认的活动记录；不能据此判断没有活动。")
        assertEquals(2, sheet.entries.size)
        assertTrue(sheet.entries[1] is LedgerEntry.Note)
    }

    @Test
    fun windowsLineEndingsAndBlankLinesAreTolerated() {
        val segments = parse("根据当前可信记录：\r\n债务记录：zhy → whr，1.3833 CNY\r\n\r\n补充一句。")
        assertEquals(2, segments.size)
        assertEquals(AnswerSegment.Prose("补充一句。"), segments[1])
    }

    @Test
    fun moneyParsingKeepsTheServersDigits() {
        assertEquals(Money("1.3833", "CNY"), AnswerBlocks.parseMoney("1.3833 CNY"))
        assertEquals(Money("-0.50", "USD"), AnswerBlocks.parseMoney("abc -0.50 USD xyz"))
        assertNull(AnswerBlocks.parseMoney("原币金额未知"))
    }
}
