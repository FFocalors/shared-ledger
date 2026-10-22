package com.ffocalors.sharedledger.data.agent

import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.equalSplit
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.fxJson
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.manualSplit
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.previewJson
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.snapshotJson
import com.ffocalors.sharedledger.data.agent.AgentTestFixtures.turnJson
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentDtoDecodeTest {
    private fun poll(events: String, cards: String = "") = AgentJson.decodeFromString(
        PollEventsResponse.serializer(),
        """{"after_seq":0,"api_version":"1.0.0","events":[$events],"has_more":false,"next_after_seq":9,
            "proposal_cards":[$cards],"turn":$turnJson}""",
    )

    @Test
    fun decodesEveryEventType() {
        val response = poll(
            """
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"resume_state":null,"state":"WAIT_CONFIRM","state_revision":2,"step":"awaiting_user","wait_reason":"confirm_required"},"seq":1,"simulation":true,"type":"status"},
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"text":"hi","citations":["fact_expense_1","policy_fact_1"]},"seq":2,"simulation":true,"type":"message"},
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"missing_slots":["original_amount","split"],"prompt":"多少钱？","resume_state":"RUNNING"},"seq":3,"simulation":true,"type":"clarification"},
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"operation":"expense.create","proposal_id":"p1","revision":1},"seq":4,"simulation":true,"type":"proposal"},
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"execution":{"execution_id":"e1","operations_version":"1.0.0","proposal_id":"p1","proposal_revision":1},"resolution":"unknown","result_code":null,"result_summary":"s"},"seq":5,"simulation":false,"type":"execution_result"},
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"code":"rate_limited","message":"m","retryable":true},"seq":6,"simulation":false,"type":"error"}
            """,
        )
        val e = response.events
        assertEquals(6, e.size)
        val status = e[0] as StatusEvent
        assertEquals("status", status.type)
        assertEquals(TurnState.WAIT_CONFIRM, status.payload.state)
        assertEquals(TurnStep.AWAITING_USER, status.payload.step)
        assertEquals(WaitReason.CONFIRM_REQUIRED, status.payload.waitReason)
        assertNull(status.payload.resumeState)
        val message = e[1] as MessageEvent
        assertEquals(listOf("fact_expense_1", "policy_fact_1"), message.payload.citations)
        val clarification = e[2] as ClarificationEvent
        assertEquals(listOf(MissingSlot.ORIGINAL_AMOUNT, MissingSlot.SPLIT), clarification.payload.missingSlots)
        assertEquals(TurnState.RUNNING, clarification.payload.resumeState)
        val proposal = e[3] as ProposalEvent
        assertEquals(ProposalOperation.EXPENSE_CREATE, proposal.payload.operation)
        val exec = e[4] as ExecutionResultEvent
        assertEquals(ExecutionResolution.UNKNOWN, exec.payload.resolution)
        assertNull(exec.payload.resultCode)
        assertEquals("s", exec.payload.resultSummary)
        val error = e[5] as ErrorEvent
        assertEquals(AgentErrorCode.RATE_LIMITED, error.payload.code)
        assertTrue(error.payload.retryable)
        assertEquals(listOf(1, 2, 3, 4, 5, 6), e.map { it.seq })
        assertEquals("1.0.0", response.apiVersion)
        assertEquals(9, response.nextAfterSeq)
    }

    @Test
    fun unknownEventTypeBecomesUnknownAndDoesNotBreakTheRest() {
        val response = poll(
            """
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"anything":[1,2]},"seq":7,"simulation":false,"type":"future_thing"},
            {"occurred_at":"2026-10-07T00:00:00Z","payload":{"text":"after"},"seq":8,"simulation":false,"type":"message"}
            """,
        )
        val unknown = response.events[0] as UnknownEvent
        assertEquals(7, unknown.seq)
        assertEquals("future_thing", unknown.type)
        assertEquals("after", (response.events[1] as MessageEvent).payload.text)
    }

    @Test
    fun unknownTopLevelAndNestedKeysAreIgnoredAndUnknownEnumValuesFallBack() {
        val turn = turnJson.replace("\"awaiting_user\"", "\"teleporting\"").replace("confirm_required", "brand_new")
        val response = AgentJson.decodeFromString(
            PollEventsResponse.serializer(),
            """{"after_seq":0,"events":[
                 {"occurred_at":"t","payload":{"state":"PAUSED","state_revision":2,"step":"warp","extra":1},"seq":1,"simulation":true,"type":"status","new_field":"x"}
               ],"has_more":true,"next_after_seq":1,"proposal_cards":[],"future_top_level":{"a":1},
               "turn":$turn}""",
        )
        val status = response.events.single() as StatusEvent
        assertEquals(TurnState.UNKNOWN, status.payload.state)
        assertEquals(TurnStep.UNKNOWN, status.payload.step)
        assertEquals(TurnStep.UNKNOWN, response.turn.step)
        assertEquals(WaitReason.UNKNOWN, response.turn.waitReason)
        assertTrue(response.hasMore)
    }

    @Test
    fun decodesAllThreeCardKinds() {
        val preview = previewJson("""{"after":"Lunch","before":null,"field":"title"}""")
        val response = poll(
            events = "",
            cards = """
            {"card_kind":"simulation_pending","confirmation_enabled":false,"mode":"simulation","operation":"expense.create","preview":$preview,"proposal_id":"p1","revision":1,"simulation":true,"status":"pending"},
            {"card_kind":"backend_pending","command_digest":"${"a".repeat(64)}","confirmation_nonce":"${"N".repeat(32)}","expires_at":"2026-10-08T00:00:00Z","mode":"backend","operation":"expense.update","preview":$preview,"proposal_id":"p2","revision":2,"simulation":false,"status":"pending"},
            {"card_kind":"inactive","command_digest":null,"mode":"backend","operation":"expense.presentation.update","preview":null,"proposal_id":"p3","revision":3,"simulation":false,"status":"superseded"},
            {"card_kind":"hologram","proposal_id":"p4"}
            """,
        )
        assertEquals(4, response.proposalCards.size)
        val sim = response.proposalCards[0] as SimulationProposalCard
        assertEquals("simulation_pending", sim.cardKind)
        assertFalse(sim.confirmationEnabled)
        assertTrue(sim.simulation)
        assertEquals(ProposalMode.SIMULATION, sim.mode)
        assertEquals(ProposalStatus.PENDING, sim.status)
        val backend = response.proposalCards[1] as ConfirmableProposalCard
        assertEquals("backend_pending", backend.cardKind)
        assertEquals(ProposalOperation.EXPENSE_UPDATE, backend.operation)
        assertEquals("a".repeat(64), backend.commandDigest)
        assertEquals(2, backend.revision)
        val inactive = response.proposalCards[2] as InactiveProposalCard
        assertEquals(ProposalStatus.SUPERSEDED, inactive.status)
        assertEquals(ProposalOperation.EXPENSE_PRESENTATION_UPDATE, inactive.operation)
        assertNull(inactive.preview)
        assertNull(inactive.commandDigest)
        val unknown = response.proposalCards[3] as UnknownProposalCard
        assertEquals("hologram", unknown.cardKind)
    }

    @Test
    fun decodesEveryChangeKindIncludingBothAmountFields() {
        val changes = """
            {"after":"Lunch","before":"Dinner","field":"title"},
            {"after":"12.50","before":"10.00","field":"original_amount"},
            {"after":"88.00","before":null,"field":"base_amount"},
            {"after":"USD","before":"CNY","field":"original_currency"},
            {"after":"$LEDGER","before":null,"field":"ledger_unit_id"},
            {"after":[{"amount":"12.50","participant_id":"pa"}],"before":null,"field":"payment_allocations"},
            {"after":$manualSplit,"before":$equalSplit,"field":"split"},
            {"after":"note","before":null,"field":"note"},
            {"after":"2026-10-07T00:00:00Z","before":null,"field":"occurred_at"},
            {"after":"food","before":null,"field":"icon_key"},
            {"after":$fxJson,"before":null,"field":"fx_snapshot"},
            {"after":"?","field":"from_the_future"}
        """.trimIndent()
        val preview = AgentJson.decodeFromString(
            ExpensePreview.serializer(),
            previewJson(changes, before = snapshotJson(equalSplit, "Dinner")),
        )
        val c = preview.changes
        assertEquals(12, c.size)
        assertEquals("Dinner", (c[0] as ExpenseTitleChange).before)
        val original = c[1] as ExpenseAmountChange
        assertEquals(AmountField.ORIGINAL_AMOUNT, original.amountField)
        assertEquals("original_amount", original.field)
        assertEquals("10.00", original.before)
        val base = c[2] as ExpenseAmountChange
        assertEquals(AmountField.BASE_AMOUNT, base.amountField)
        assertEquals("base_amount", base.field)
        assertNull(base.before)
        assertEquals("USD", (c[3] as ExpenseCurrencyChange).after)
        assertEquals(LEDGER, (c[4] as ExpenseLedgerUnitChange).after)
        assertEquals("12.50", (c[5] as ExpensePaymentsChange).after.single().amount)
        val split = c[6] as ExpenseSplitChange
        assertTrue(split.after is CanonicalManualSplit)
        assertTrue(split.before is CanonicalEqualSplit)
        assertEquals("note", (c[7] as ExpenseNoteChange).after)
        assertEquals("2026-10-07T00:00:00Z", (c[8] as ExpenseOccurredAtChange).after)
        assertEquals("food", (c[9] as ExpenseIconChange).after)
        val fx = (c[10] as ExpenseFxChange).after!!
        assertEquals("7.1234567891", fx.rate)
        assertEquals(FxSource.ECB_SNAPSHOT, fx.source)
        assertEquals("from_the_future", (c[11] as UnknownExpenseChange).field)
        assertEquals("Dinner", preview.before!!.title)
        assertEquals("expense", preview.kind)
    }

    @Test
    fun decodesEqualAndManualSplitInSnapshots() {
        val equal = AgentJson.decodeFromString(ExpenseSnapshot.serializer(), snapshotJson(equalSplit))
        val equalResult = equal.split as CanonicalEqualSplit
        assertEquals("equal", equalResult.mode)
        assertEquals(2, equalResult.participantIds.size)

        val manual = AgentJson.decodeFromString(ExpenseSnapshot.serializer(), snapshotJson(manualSplit))
        val manualResult = manual.split as CanonicalManualSplit
        assertEquals("manual", manualResult.mode)
        assertEquals(listOf("5.00", "7.50"), manualResult.allocations.map { it.amount })
        assertEquals("12.50", manual.baseAmount)
    }

    @Test
    fun decodesTraceEventsAndCard() {
        val trace = AgentTestFixtures.trace("propose_wait_confirm_confirm_disabled")
        val events = AgentTestFixtures.steps(trace, "event").map {
            AgentJson.decodeFromJsonElement(AgentEvent.serializer(), it.getValue("event"))
        }
        assertEquals(listOf("status", "proposal"), events.map { it.type })
        val card = AgentJson.decodeFromJsonElement(
            ProposalCard.serializer(),
            AgentTestFixtures.steps(trace, "proposal_card").single().getValue("card"),
        ) as SimulationProposalCard
        assertEquals(8, card.preview.changes.size)
        assertEquals(
            listOf(AmountField.ORIGINAL_AMOUNT, AmountField.BASE_AMOUNT),
            card.preview.changes.filterIsInstance<ExpenseAmountChange>().map { it.amountField },
        )
        assertTrue(card.preview.after.split is CanonicalEqualSplit)
        assertEquals(AgentTestFixtures.PROPOSAL_ID, card.proposalId)
    }

    @Test
    fun decodesTraceResponsesAndRoundTripsTraceRequests() {
        val trace = AgentTestFixtures.trace("clarify_auth_cancel_reference_stability")
        val clarification = AgentTestFixtures.steps(trace, "resume_clarification").single()
        val accepted = AgentJson.decodeFromJsonElement(
            TurnMutationAccepted.serializer(),
            clarification.getValue("response"),
        )
        assertEquals(TurnState.RUNNING, accepted.state)
        assertEquals(3, accepted.eventCursor)
        assertRoundTrip(ResumeClarificationRequest.serializer(), clarification.getValue("request").jsonObject)

        for (step in AgentTestFixtures.steps(trace, "resume_auth")) {
            AgentJson.decodeFromJsonElement(TurnMutationAccepted.serializer(), step.getValue("response"))
            assertRoundTrip(ResumeAuthRequest.serializer(), step.getValue("request").jsonObject)
        }

        val cancel = AgentTestFixtures.steps(trace, "cancel").single()
        val response = AgentJson.decodeFromJsonElement(CancelTurnResponse.serializer(), cancel.getValue("response"))
        assertEquals(CancelResult.CANCELLED, response.result)
        assertEquals(TurnState.CANCELLED, response.turn.state)
        assertEquals(TurnStep.TERMINAL, response.turn.step)
        assertRoundTrip(CancelTurnRequest.serializer(), cancel.getValue("request").jsonObject)

        val confirm = AgentTestFixtures.steps(
            AgentTestFixtures.trace("propose_wait_confirm_confirm_disabled"),
            "confirm_disabled",
        ).single()
        assertRoundTrip(ConfirmProposalRequest.serializer(), confirm.getValue("request").jsonObject)
        val unavailable = AgentJson.decodeFromJsonElement(
            ConfirmationUnavailableResponse.serializer(),
            confirm.getValue("response"),
        )
        assertEquals(AgentErrorCode.EXECUTION_CAPABILITY_UNAVAILABLE, unavailable.code)
        assertFalse(unavailable.businessWritePerformed)
        assertFalse(unavailable.executionEnabled)
    }

    @Test
    fun decodesSessionResponses() {
        val detail = AgentJson.decodeFromString(
            SessionDetailResponse.serializer(),
            """{"api_version":"1.0.0","proposal_cards":[],"session":{"active_turn_count":1,"created_at":"a","session_id":"s","title":null,"updated_at":"b"},
                "turns":[{"created_at":"a","state":"WAIT_INPUT","state_revision":3,"turn_id":"t","updated_at":"b"}]}""",
        )
        assertNull(detail.session.title)
        assertEquals(TurnState.WAIT_INPUT, detail.turns.single().state)

        val list = AgentJson.decodeFromString(
            ListSessionsResponse.serializer(),
            """{"api_version":"1.0.0","items":[{"active_turn_count":0,"created_at":"a","session_id":"s","title":"T","updated_at":"b"}],"next_cursor":"c"}""",
        )
        assertEquals("c", list.nextCursor)
        assertEquals("T", list.items.single().title)
    }

    private fun <T> assertRoundTrip(serializer: KSerializer<T>, original: JsonObject) {
        val decoded = AgentJson.decodeFromJsonElement(serializer, original)
        // Schema default null == omitted, so explicit nulls in the trace are dropped on re-encode.
        val withoutNulls = JsonObject(original.filterValues { it !is JsonNull })
        assertEquals(withoutNulls, AgentJson.encodeToJsonElement(serializer, decoded))
    }

    private companion object {
        const val LEDGER = "d509605c-f599-54cc-9187-9fd40283f8f8"
    }
}
