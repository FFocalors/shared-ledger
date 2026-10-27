package com.ffocalors.sharedledger.data.agent

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class AgentRequestEncodeTest {
    private val rid = "5f3eaa7c-8302-5dbc-98bf-1337fb8389d7"

    private fun parse(text: String): JsonObject = Json.parseToJsonElement(text).jsonObject

    private fun assertVersions(obj: JsonObject) {
        val v = obj.getValue("versions").jsonObject
        assertEquals(setOf("api", "operations", "semantic"), v.keys)
        assertEquals("1.1.0", v.getValue("api").jsonPrimitive.content)
        // api 1.1.0 did not change the operation or semantic versions.
        assertEquals("1.0.0", v.getValue("operations").jsonPrimitive.content)
        assertEquals("1.0.0", v.getValue("semantic").jsonPrimitive.content)
    }

    @Test
    fun submitTurnWithoutUiContextOmitsIt() {
        val obj = parse(AgentJson.encodeToString(SubmitTurnRequest.serializer(), SubmitTurnRequest(rid, "午饭 12.5")))
        assertEquals(setOf("client_request_id", "text", "versions"), obj.keys)
        assertEquals(rid, obj.getValue("client_request_id").jsonPrimitive.content)
        assertEquals("午饭 12.5", obj.getValue("text").jsonPrimitive.content)
        assertVersions(obj)
    }

    @Test
    fun submitTurnWithUiContextUsesSnakeCaseAndDefaults() {
        val request = SubmitTurnRequest(
            clientRequestId = rid,
            text = "hi",
            uiContext = UiContext(
                capturedAt = "2026-10-07T00:00:00Z",
                clientVersion = "1.0",
                pageType = UiPageType.EXPENSE_DETAIL,
                activityId = "a1",
                selectedEntity = UiEntityHint("e1", UiEntityType.EXPENSE),
            ),
        )
        val ctx = parse(AgentJson.encodeToString(SubmitTurnRequest.serializer(), request))
            .getValue("ui_context").jsonObject
        assertEquals("expense_detail", ctx.getValue("page_type").jsonPrimitive.content)
        assertEquals("2026-10-07T00:00:00Z", ctx.getValue("captured_at").jsonPrimitive.content)
        assertEquals("1.0", ctx.getValue("client_version").jsonPrimitive.content)
        assertEquals("1", ctx.getValue("schema_version").jsonPrimitive.content)
        assertEquals("a1", ctx.getValue("activity_id").jsonPrimitive.content)
        assertFalse("ledger_unit_id" in ctx)
        assertEquals("[]", ctx.getValue("filters").jsonObject.getValue("participant_ids").toString())
        val entity = ctx.getValue("selected_entity").jsonObject
        assertEquals("expense", entity.getValue("entity_type").jsonPrimitive.content)
        assertEquals("e1", entity.getValue("entity_id").jsonPrimitive.content)
    }

    @Test
    fun cancelTurnShape() {
        val obj = parse(AgentJson.encodeToString(CancelTurnRequest.serializer(), CancelTurnRequest(rid, 3)))
        assertEquals(setOf("client_request_id", "expected_state_revision", "versions"), obj.keys)
        assertEquals("3", obj.getValue("expected_state_revision").jsonPrimitive.content)
        assertVersions(obj)

        val withReason = parse(
            AgentJson.encodeToString(CancelTurnRequest.serializer(), CancelTurnRequest(rid, 3, "算了")),
        )
        assertEquals("算了", withReason.getValue("reason").jsonPrimitive.content)
    }

    @Test
    fun resumeClarificationShape() {
        val obj = parse(
            AgentJson.encodeToString(
                ResumeClarificationRequest.serializer(),
                ResumeClarificationRequest(rid, 1, "我付的 12.50"),
            ),
        )
        assertEquals(setOf("client_request_id", "expected_state_revision", "text", "versions"), obj.keys)
        assertEquals("我付的 12.50", obj.getValue("text").jsonPrimitive.content)
        assertVersions(obj)
    }

    @Test
    fun otherRequestsShape() {
        val auth = parse(AgentJson.encodeToString(ResumeAuthRequest.serializer(), ResumeAuthRequest(rid, 4)))
        assertEquals(setOf("client_request_id", "expected_state_revision", "versions"), auth.keys)

        val adjust = parse(
            AgentJson.encodeToString(
                ResumeProposalAdjustRequest.serializer(),
                ResumeProposalAdjustRequest(rid, expectedProposalRevision = 2, expectedStateRevision = 5, text = "改成 15"),
            ),
        )
        assertEquals(
            setOf("client_request_id", "expected_proposal_revision", "expected_state_revision", "text", "versions"),
            adjust.keys,
        )

        val confirm = parse(
            AgentJson.encodeToString(
                ConfirmProposalRequest.serializer(),
                ConfirmProposalRequest(rid, "a".repeat(64), "N".repeat(32), 1),
            ),
        )
        assertEquals(
            setOf("client_request_id", "command_digest", "confirmation_nonce", "expected_proposal_revision", "versions"),
            confirm.keys,
        )

        val create = parse(AgentJson.encodeToString(CreateSessionRequest.serializer(), CreateSessionRequest(rid)))
        assertEquals(setOf("client_request_id", "api_version"), create.keys)
        assertEquals("1.1.0", create.getValue("api_version").jsonPrimitive.content)
    }
}
