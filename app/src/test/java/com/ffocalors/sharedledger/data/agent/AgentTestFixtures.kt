package com.ffocalors.sharedledger.data.agent

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal object AgentTestFixtures {
    fun trace(name: String): JsonObject {
        val path = "/agent-contract-v1.0.0/mock_traces/$name.json"
        val text = checkNotNull(AgentTestFixtures::class.java.getResourceAsStream(path)) { "missing $path" }
            .use { it.readBytes().toString(Charsets.UTF_8) }
        return Json.parseToJsonElement(text).jsonObject
    }

    fun steps(trace: JsonObject, kind: String): List<JsonObject> =
        trace.getValue("steps").jsonArray.map { it.jsonObject }
            .filter { it.getValue("kind").jsonPrimitive.content == kind }

    const val TURN_ID = "66a32511-91eb-5d92-950e-2cc10220c69f"
    const val SESSION_ID = "e2156f15-78a7-58cb-b502-8fad683c91d4"
    const val PARTICIPANT_A = "279a1dde-c45b-5c26-a00b-0ca57129cb7b"
    const val PARTICIPANT_B = "148c4cfb-4f09-55af-84d8-5008c08fa829"
    const val LEDGER_UNIT = "d509605c-f599-54cc-9187-9fd40283f8f8"
    const val PROPOSAL_ID = "8bbb5b01-80ea-5996-9a00-1537b736a7df"
    const val REQUEST_ID = "5f3eaa7c-8302-5dbc-98bf-1337fb8389d7"

    val turnJson = """
        {"context_version":1,"execution_assigned":false,"execution_resolution":null,"resume_state":null,
         "session_id":"$SESSION_ID","state":"WAIT_CONFIRM","state_revision":2,"step":"awaiting_user",
         "turn_id":"$TURN_ID","wait_reason":"confirm_required"}
    """.trimIndent()

    fun snapshotJson(split: String, title: String = "Lunch") = """
        {"base_amount":"12.50","expense_version":"1","financial_locked":false,"fx_snapshot":null,"icon_key":null,
         "ledger_unit_id":"$LEDGER_UNIT","note":null,"occurred_at":"2026-10-07T00:00:00Z",
         "original_amount":"12.50","original_currency":"CNY",
         "payment_allocations":[{"amount":"12.50","participant_id":"$PARTICIPANT_A"}],
         "split":$split,"title":"$title"}
    """.trimIndent()

    val equalSplit = """{"mode":"equal","participant_ids":["$PARTICIPANT_A","$PARTICIPANT_B"]}"""
    val manualSplit = """{"mode":"manual","allocations":[{"amount":"5.00","participant_id":"$PARTICIPANT_A"},{"amount":"7.50","participant_id":"$PARTICIPANT_B"}]}"""
    val fxJson = """{"base_currency":"CNY","observed_at":"2026-10-07T00:00:00Z","original_currency":"USD","rate":"7.1234567891","source":"ecb_snapshot"}"""

    fun previewJson(changes: String, split: String = equalSplit, before: String? = null) = """
        {"activity_financial_version":"3","after":${snapshotJson(split)},"before":${before ?: "null"},
         "changes":[$changes],"generated_at":"2026-10-07T00:00:00Z","kind":"expense","simulation":false,
         "summary":"summary"}
    """.trimIndent()
}
