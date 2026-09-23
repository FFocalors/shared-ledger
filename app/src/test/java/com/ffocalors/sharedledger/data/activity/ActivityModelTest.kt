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
        assertTrue(member.canCreateSubActivity)
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
    fun activityMemberErrorsClearAsPermissionFailures() {
        assertEquals(
            ActivityFailureKind.PermissionDenied,
            ActivityErrorMapper.failureKind(IllegalStateException("user is not an activity member")),
        )
    }

    @Test
    fun activityRowDecodesParticipantListLockTimestamp() {
        val row = Json.decodeFromString<ActivityRowDto>(
            """
            {
              "id":"activity-1",
              "name":"旅行",
              "type":"normal",
              "join_code":"12345678",
              "base_currency":"JPY",
              "multi_currency_enabled":true,
              "created_by":"user-1",
              "participants_locked_at":"2026-09-07T10:00:00Z"
            }
            """.trimIndent(),
        )

        assertEquals("JPY", row.baseCurrency)
        assertEquals("2026-09-07T10:00:00Z", row.participantsLockedAt)
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
              "financial_version":3,
              "has_unsettled_debt":true,
              "prepayment_by_currency":[
                {"currency":"CNY","balance":12.50},
                {"currency":"USD","balance":4.0}
              ]
            }]
            """.trimIndent(),
        )

        assertEquals("0.0", rows.single().totalDebt?.toString()?.removeSurrounding("\"") ?: "")
        assertEquals("12.50", rows.single().totalPrepayment?.toString()?.removeSurrounding("\"") ?: "")
        assertEquals(listOf("CNY", "USD"), rows.single().prepaymentByCurrency?.map { it.currency })
        assertEquals("4.0", rows.single().prepaymentByCurrency?.last()?.balance?.toString())
        assertEquals(true, rows.single().hasUnsettledDebt)
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
