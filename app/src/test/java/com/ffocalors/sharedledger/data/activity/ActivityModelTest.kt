package com.ffocalors.sharedledger.data.activity

import kotlinx.serialization.json.Json
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ActivityModelTest {
    @Test
    fun creatorPermissionsAreDifferentFromMemberPermissions() {
        val creator = ActivityPermissions.forRole(ActivityRole.Creator)
        val member = ActivityPermissions.forRole(ActivityRole.Member)

        assertTrue(creator.canManageParticipants)
        assertTrue(creator.canEditSettings)
        assertFalse(member.canManageParticipants)
        assertFalse(member.canEditSettings)
    }

    @Test
    fun participantAndMemberKeepDifferentIdentities() {
        val participant = Participant("participant-1", "activity-1", "Alex", 0)
        val member = ActivityMember("member-1", "user-1", "Alex", isCreator = false)

        assertTrue(participant.id != member.id)
        assertTrue(participant.activityId == "activity-1")
        assertTrue(member.userId == "user-1")
    }

    @Test
    fun financialStatusDecodesPostgrestNumericAmountsAndPreservesText() {
        val rows = Json.decodeFromString<List<FinancialStatusRowDto>>(
            """
            [{
              "activity_id":"activity-1",
              "financial_status":"active",
              "completed":false,
              "total_debt":0.0,
              "total_prepayment":12.50,
              "financial_version":3
            }]
            """.trimIndent(),
        )

        assertEquals("0.0", rows.single().totalDebt?.toString()?.removeSurrounding("\"") ?: "")
        assertEquals("12.50", rows.single().totalPrepayment?.toString()?.removeSurrounding("\"") ?: "")
    }

    @Test
    fun financialStatusAlsoDecodesLegacyQuotedAmounts() {
        val row = Json.decodeFromString<FinancialStatusRowDto>(
            """
            {
              "activity_id":"activity-1",
              "financial_status":"active",
              "completed":false,
              "total_debt":"8.25",
              "total_prepayment":null,
              "financial_version":1
            }
            """.trimIndent(),
        )

        assertEquals("\"8.25\"", row.totalDebt.toString())
        assertTrue(row.totalPrepayment == null)
    }
}
