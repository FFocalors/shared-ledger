package com.ffocalors.sharedledger.data.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** api 1.1.0 added the P5 preview kinds; a card must decode for every one and never crash on a newer kind. */
class AgentProposalPreviewDecodeTest {
    private fun card(operation: String, preview: String): ConfirmableProposalCard {
        val json = """
            {"card_kind":"backend_pending","command_digest":"${"a".repeat(64)}",
             "confirmation_nonce":"${"N".repeat(32)}","expires_at":"2026-10-27T00:00:00Z",
             "mode":"backend","operation":"$operation","preview":$preview,
             "proposal_id":"8bbb5b01-80ea-5996-9a00-1537b736a7df","revision":1,"simulation":false,"status":"pending"}
        """.trimIndent()
        return AgentJson.decodeFromString(ProposalCard.serializer(), json) as ConfirmableProposalCard
    }

    private fun preview(kind: String, body: String): String = """{"kind":"$kind",$body}"""

    @Test
    fun expensePreviewStillDecodes() {
        val decoded = card("expense.create", AgentTestFixtures.previewJson("""{"after":"Lunch","before":null,"field":"title"}"""))
        assertTrue(decoded.preview is ExpensePreview)
        assertEquals("Lunch", (decoded.preview as ExpensePreview).after.title)
    }

    @Test
    fun managementPreviewDecodesForTheNewActivityOperations() {
        val decoded = card(
            "activity.create",
            preview(
                "management",
                """"summary":"创建活动","generated_at":"2026-10-27T00:00:00Z","simulation":false,
                   "operation":"activity.create","activity_name":"周末露营","activity_type":"large",
                   "base_currency":"CNY","join_code":"CAMP-42","multi_currency_enabled":true""",
            ),
        )
        val management = decoded.preview as ManagementPreview
        assertEquals("周末露营", management.activityName)
        assertEquals("CAMP-42", management.joinCode)
        assertEquals(ProposalOperation.ACTIVITY_CREATE, management.operation)
    }

    @Test
    fun refundPreviewDecodes() {
        val decoded = card(
            "expense.refund",
            preview(
                "refund",
                """"summary":"退款 50","generated_at":"2026-10-27T00:00:00Z","simulation":false,
                   "activity_id":"a","original_expense_id":"e","original_title":"烧烤","refund_title":"烧烤退款",
                   "original_amount":"750.00","refunded_amount":"0.00","refund_amount":"50.00",
                   "remaining_amount":"700.00","currency":"CNY","expected_financial_version":"3",
                   "expected_original_version":"2","expected_original_financial_locked":false""",
            ),
        )
        val refund = decoded.preview as RefundPreview
        assertEquals("烧烤退款", refund.refundTitle)
        assertEquals("50.00", refund.refundAmount)
    }

    @Test
    fun prepaymentAndReturnPreviewsDecode() {
        val created = card(
            "prepayment.create",
            preview(
                "prepayment",
                """"summary":"预存","generated_at":"t","simulation":false,"activity_id":"a",
                   "owner_participant_id":"o","custodian_participant_id":"c","amount":"800.00",
                   "currency":"CNY","settlement_amount":"800.00","prepayment_amount":"800.00",
                   "new_balance":"800.00","expected_financial_version":"3"""",
            ),
        )
        assertEquals("800.00", (created.preview as PrepaymentPreview).newBalance)
        val returned = card(
            "prepayment.return",
            preview(
                "prepayment_return",
                """"summary":"返还","generated_at":"t","simulation":false,"activity_id":"a",
                   "owner_participant_id":"o","custodian_participant_id":"c","amount":"100.00",
                   "currency":"CNY","current_balance":"800.00","expected_financial_version":"3",
                   "post_balance_note":"以实际执行结果为准"""",
            ),
        )
        assertEquals("800.00", (returned.preview as PrepaymentReturnPreview).currentBalance)
    }

    @Test
    fun negativeAdjustmentPreviewDecodes() {
        val decoded = card(
            "expense.negative_adjustment",
            preview(
                "negative_adjustment",
                """"summary":"冲减","generated_at":"t","simulation":false,"activity_id":"a",
                   "title":"优惠冲减","amount":"20.00","currency":"CNY","expected_financial_version":"3"""",
            ),
        )
        assertEquals("优惠冲减", (decoded.preview as NegativeAdjustmentPreview).title)
    }

    @Test
    fun repaymentPreviewDecodesWithAllocations() {
        val decoded = card(
            "settlement.repayment",
            preview(
                "repayment",
                """"summary":"还款","generated_at":"t","simulation":false,"activity_id":"a",
                   "from_participant_id":"f","to_participant_id":"t","amount":"150.00","currency":"CNY",
                   "mode":"FIFO","expected_financial_version":"3",
                   "allocations":[{"allocation_mode":"FIFO","base_amount":"150.00","expense_id":"e",
                     "fx_rate":"1","ledger_unit_id":"l","original_amount":"150.00","original_currency":"CNY",
                     "payment_amount":"150.00","payment_currency":"CNY","remaining_base_amount":"0.00",
                     "remaining_original_amount":"0.00","source_financial_version":"2"}]""",
            ),
        )
        val repayment = decoded.preview as RepaymentPreview
        assertEquals("FIFO", repayment.mode)
        assertEquals(1, repayment.allocations.size)
    }

    @Test
    fun transferVoidPreviewDecodes() {
        val decoded = card(
            "transfer.void",
            preview(
                "transfer_void",
                """"summary":"作废","generated_at":"t","simulation":false,"activity_id":"a",
                   "transfer_id":"tr","transfer_type":"settlement","from_participant_id":"f",
                   "to_participant_id":"t","amount":"100.00","currency":"CNY","void_reason":"记错了",
                   "is_voided":true,"expected_financial_version":"3"""",
            ),
        )
        assertTrue((decoded.preview as TransferVoidPreview).isVoided)
    }

    @Test
    fun finalSettlementPreviewDecodesWithItsPlan() {
        val decoded = card(
            "settlement.final",
            preview(
                "final_settlement",
                """"summary":"最终结算","generated_at":"t","simulation":false,"activity_id":"a",
                   "mode":"base_unified","from_participant_id":"f","to_participant_id":"t",
                   "amount":"300.00","currency":"CNY","ordinary_amount":"200.00",
                   "prepayment_return_amount":"100.00","is_prepayment_return":true,
                   "expected_financial_version":"3",
                   "plan":[{"amount":"300.00","currency":"CNY","from_participant_id":"f",
                     "is_prepayment_return":true,"ordinary_amount":"200.00",
                     "prepayment_return_amount":"100.00","to_participant_id":"t"}]""",
            ),
        )
        val settlement = decoded.preview as FinalSettlementPreview
        assertEquals(1, settlement.plan.size)
        assertEquals("base_unified", settlement.mode)
    }

    @Test
    fun aPreviewKindFromANewerServerFallsBackInsteadOfFailing() {
        val decoded = card(
            "activity.delete",
            preview("future_kind", """"summary":"服务端的新变更摘要","generated_at":"t","simulation":false"""),
        )
        val unknown = decoded.preview as UnknownPreview
        assertEquals("future_kind", unknown.kind)
        assertEquals("服务端的新变更摘要", unknown.summary)
    }

    @Test
    fun anOperationFromANewerServerFallsBackToUnknown() {
        val decoded = card(
            "activity.teleport",
            AgentTestFixtures.previewJson("""{"after":"Lunch","before":null,"field":"title"}""",),
        )
        assertEquals(ProposalOperation.UNKNOWN, decoded.operation)
        assertTrue(decoded.preview is ExpensePreview)
    }

    @Test
    fun everyOperationInTheV110SnapshotDecodes() {
        val ops = listOf(
            "expense.create", "expense.update", "expense.presentation.update", "expense.delete",
            "settlement.repayment", "transfer.void", "prepayment.create", "prepayment.return",
            "settlement.final", "expense.refund", "expense.negative_adjustment", "activity.create",
            "activity.join", "participant.create", "participant.delete", "participant.claim",
            "participant.unclaim", "subactivity.create", "subactivity.delete", "subactivity.restore",
            "activity.member.remove", "activity.creator.transfer", "activity.archive",
            "activity.unarchive", "activity.delete",
        )
        val decoded = ops.map { AgentJson.decodeFromString(ProposalOperation.serializer(), "\"$it\"") }
        assertEquals(ops.size, decoded.size)
        assertTrue(decoded.none { it == ProposalOperation.UNKNOWN })
        assertEquals(ops.size, ProposalOperation.entries.count { it != ProposalOperation.UNKNOWN })
    }
}
