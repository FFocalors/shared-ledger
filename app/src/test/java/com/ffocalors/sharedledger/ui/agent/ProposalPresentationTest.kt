package com.ffocalors.sharedledger.ui.agent

import com.ffocalors.sharedledger.data.agent.CanonicalEqualSplit
import com.ffocalors.sharedledger.data.agent.CanonicalPayment
import com.ffocalors.sharedledger.data.agent.ExpenseAmountChange
import com.ffocalors.sharedledger.data.agent.ExpensePreview
import com.ffocalors.sharedledger.data.agent.ExpenseSnapshot
import com.ffocalors.sharedledger.data.agent.FinalSettlementPlanItem
import com.ffocalors.sharedledger.data.agent.FinalSettlementPreview
import com.ffocalors.sharedledger.data.agent.ManagementPreview
import com.ffocalors.sharedledger.data.agent.NegativeAdjustmentPreview
import com.ffocalors.sharedledger.data.agent.PrepaymentPreview
import com.ffocalors.sharedledger.data.agent.PrepaymentReturnPreview
import com.ffocalors.sharedledger.data.agent.ProposalOperation
import com.ffocalors.sharedledger.data.agent.ProposalPreview
import com.ffocalors.sharedledger.data.agent.RefundPreview
import com.ffocalors.sharedledger.data.agent.RepaymentAllocation
import com.ffocalors.sharedledger.data.agent.RepaymentPreview
import com.ffocalors.sharedledger.data.agent.TransferVoidPreview
import com.ffocalors.sharedledger.data.agent.UnknownPreview
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Every preview kind api 1.1.0 can send must render; anything newer must fall back to a summary. */
class ProposalPresentationTest {
    private val names = AgentNameResolver(
        participants = mapOf("f" to "小王", "t" to "小李", "o" to "小王", "c" to "小李"),
    )

    private fun view(preview: ProposalPreview, operation: ProposalOperation = ProposalOperation.UNKNOWN) =
        ProposalPresentation.previewView(preview, operation, names)

    private fun snapshot() = ExpenseSnapshot(
        baseAmount = "12.50",
        expenseVersion = "1",
        financialLocked = false,
        ledgerUnitId = "l",
        originalAmount = "12.50",
        originalCurrency = "CNY",
        paymentAllocations = listOf(CanonicalPayment("12.50", "f")),
        split = CanonicalEqualSplit(listOf("f", "t")),
        title = "午饭",
    )

    private val expense = ExpensePreview(
        activityFinancialVersion = "1",
        after = snapshot(),
        changes = listOf(ExpenseAmountChange(com.ffocalors.sharedledger.data.agent.AmountField.ORIGINAL_AMOUNT, "12.50")),
        generatedAt = "2026-10-27T00:00:00Z",
        simulation = false,
        summary = "新增账目",
    )

    private fun management(operation: ProposalOperation = ProposalOperation.ACTIVITY_CREATE) = ManagementPreview(
        operation = operation,
        generatedAt = "2026-10-27T00:00:00Z",
        simulation = false,
        summary = "创建活动",
        activityName = "周末露营",
        activityType = "large",
        baseCurrency = "CNY",
        joinCode = "CAMP-42",
        multiCurrencyEnabled = true,
    )

    private fun refund() = RefundPreview(
        activityId = "a",
        originalExpenseId = "e",
        originalTitle = "烧烤",
        refundTitle = "烧烤退款",
        originalAmount = "750.00",
        refundedAmount = "0.00",
        refundAmount = "50.00",
        remainingAmount = "700.00",
        currency = "CNY",
        expectedFinancialVersion = "3",
        expectedOriginalVersion = "2",
        expectedOriginalFinancialLocked = false,
        generatedAt = "t",
        simulation = false,
        summary = "退款",
    )

    private fun prepayment() = PrepaymentPreview(
        activityId = "a", ownerParticipantId = "o", custodianParticipantId = "c",
        amount = "800.00", currency = "CNY", settlementAmount = "800.00",
        prepaymentAmount = "800.00", newBalance = "800.00", expectedFinancialVersion = "3",
        generatedAt = "t", simulation = false, summary = "预存",
    )

    private fun prepaymentReturn() = PrepaymentReturnPreview(
        activityId = "a", ownerParticipantId = "o", custodianParticipantId = "c",
        amount = "100.00", currency = "CNY", currentBalance = "800.00",
        expectedFinancialVersion = "3", generatedAt = "t", simulation = false,
        summary = "返还", postBalanceNote = "以实际执行结果为准",
    )

    private fun negativeAdjustment() = NegativeAdjustmentPreview(
        activityId = "a", title = "优惠冲减", amount = "20.00", currency = "CNY",
        expectedFinancialVersion = "3", generatedAt = "t", simulation = false, summary = "冲减",
    )

    private fun repayment() = RepaymentPreview(
        activityId = "a", fromParticipantId = "f", toParticipantId = "t", amount = "150.00",
        currency = "CNY", mode = "FIFO", expectedFinancialVersion = "3", generatedAt = "t",
        simulation = false, summary = "还款",
        allocations = listOf(
            RepaymentAllocation(
                allocationMode = "FIFO", baseAmount = "150.00", expenseId = "e", fxRate = "1",
                ledgerUnitId = "l", originalAmount = "150.00", originalCurrency = "CNY",
                paymentAmount = "150.00", paymentCurrency = "CNY", remainingBaseAmount = "0.00",
                remainingOriginalAmount = "0.00", sourceFinancialVersion = "2",
            ),
        ),
    )

    private fun transferVoid() = TransferVoidPreview(
        activityId = "a", transferId = "tr", transferType = "settlement",
        fromParticipantId = "f", toParticipantId = "t", amount = "100.00", currency = "CNY",
        voidReason = "记错了", isVoided = true, expectedFinancialVersion = "3",
        generatedAt = "t", simulation = false, summary = "作废",
    )

    private fun finalSettlement() = FinalSettlementPreview(
        activityId = "a", mode = "base_unified", fromParticipantId = "f", toParticipantId = "t",
        amount = "300.00", currency = "CNY", ordinaryAmount = "200.00",
        prepaymentReturnAmount = "100.00", isPrepaymentReturn = true,
        plan = listOf(
            FinalSettlementPlanItem(
                amount = "300.00", currency = "CNY", fromParticipantId = "f",
                isPrepaymentReturn = true, ordinaryAmount = "200.00",
                prepaymentReturnAmount = "100.00", toParticipantId = "t",
            ),
        ),
        expectedFinancialVersion = "3", generatedAt = "t", simulation = false, summary = "结算",
    )

    @Test
    fun everyOperationHasATitleAndSummary() {
        ProposalOperation.entries.forEach { operation ->
            val title = ProposalPresentation.operationTitle(operation)
            val summary = ProposalPresentation.operationSummary(operation)
            assertTrue("title for $operation", title.isNotBlank())
            assertTrue("summary for $operation", summary.isNotBlank())
            if (operation != ProposalOperation.UNKNOWN) {
                assertFalse("title for $operation should not be the fallback", title == ProposalPresentation.operationTitle(ProposalOperation.UNKNOWN))
            }
        }
    }

    @Test
    fun expensePreviewRendersItsRows() {
        val view = view(expense, ProposalOperation.EXPENSE_CREATE)
        assertEquals("午饭", view.title)
        assertEquals("12.50 CNY", view.amount)
        assertFalse(view.fallback)
    }

    @Test
    fun managementPreviewRendersTheActivityFacts() {
        val view = view(management(), ProposalOperation.ACTIVITY_CREATE)
        assertEquals("周末露营", view.title)
        assertTrue(view.rows.any { it.label == "加入码" && it.after == "CAMP-42" })
        assertTrue(view.rows.any { it.label == "类型" && it.after == "大型活动" })
        assertNotNull(view.note)
        assertFalse(view.fallback)
    }

    @Test
    fun refundPreviewRendersItsAmounts() {
        val view = view(refund(), ProposalOperation.EXPENSE_REFUND)
        assertEquals("烧烤退款", view.title)
        assertEquals("50.00 CNY", view.amount)
        assertTrue(view.rows.any { it.label == "退款后剩余" && it.after == "700.00 CNY" })
    }

    @Test
    fun prepaymentPreviewsRenderBalancesAndNames() {
        val created = view(prepayment(), ProposalOperation.PREPAYMENT_CREATE)
        assertEquals("800.00 CNY", created.amount)
        assertTrue(created.rows.any { it.label == "所有人" && it.after == "小王" })
        assertTrue(created.rows.any { it.label == "预存后余额" })
        val returned = view(prepaymentReturn(), ProposalOperation.PREPAYMENT_RETURN)
        assertTrue(returned.rows.any { it.label == "当前余额" && it.after == "800.00 CNY" })
        assertTrue(returned.rows.any { it.label == "余额说明" })
    }

    @Test
    fun negativeAdjustmentRendersTitleAndSummaryNote() {
        val view = view(negativeAdjustment(), ProposalOperation.EXPENSE_NEGATIVE_ADJUSTMENT)
        assertEquals("优惠冲减", view.title)
        assertEquals("20.00 CNY", view.amount)
        assertEquals(ProposalPresentation.operationSummary(ProposalOperation.EXPENSE_NEGATIVE_ADJUSTMENT), view.note)
    }

    @Test
    fun repaymentPreviewRendersParticipantsAndMode() {
        val view = view(repayment(), ProposalOperation.SETTLEMENT_REPAYMENT)
        assertTrue(view.rows.any { it.label == "付款人" && it.after == "小王" })
        assertTrue(view.rows.any { it.label == "冲抵方式" && it.after == "按先后顺序冲抵" })
        assertTrue(view.rows.any { it.label == "冲抵账目" && it.after == "1 笔" })
    }

    @Test
    fun transferVoidPreviewRendersStateAndReason() {
        val view = view(transferVoid(), ProposalOperation.TRANSFER_VOID)
        assertTrue(view.rows.any { it.label == "状态" && it.after == "已作废" })
        assertTrue(view.rows.any { it.label == "原因" && it.after == "记错了" })
    }

    @Test
    fun finalSettlementPreviewRendersItsPlan() {
        val view = view(finalSettlement(), ProposalOperation.SETTLEMENT_FINAL)
        assertTrue(view.rows.any { it.label == "结算方式" && it.after == "统一基准币种" })
        assertTrue(view.rows.any { it.label == "计划" && it.after.contains("小王 → 小李") })
    }

    @Test
    fun unknownPreviewFallsBackToTheServerSummary() {
        val view = view(UnknownPreview(kind = "future", summary = "服务端的新变更摘要"), ProposalOperation.ACTIVITY_DELETE)
        assertTrue(view.fallback)
        assertEquals(ProposalPresentation.UNKNOWN_PREVIEW_TITLE, view.title)
        assertEquals("服务端的新变更摘要", view.note)
        assertTrue(view.rows.isEmpty())
    }

    @Test
    fun unknownPreviewWithoutSummaryStillShowsGuidance() {
        val view = view(UnknownPreview(kind = "future"), ProposalOperation.UNKNOWN)
        assertTrue(view.fallback)
        assertEquals(ProposalPresentation.UNKNOWN_PREVIEW_NOTE, view.note)
    }

    @Test
    fun unknownOperationFallsBackToAGenericTitle() {
        assertEquals("变更草稿", ProposalPresentation.operationTitle(ProposalOperation.UNKNOWN))
        val view = view(management(ProposalOperation.UNKNOWN), ProposalOperation.ACTIVITY_DELETE)
        assertEquals("周末露营", view.title)
        assertNotNull(view.note)
    }
}
