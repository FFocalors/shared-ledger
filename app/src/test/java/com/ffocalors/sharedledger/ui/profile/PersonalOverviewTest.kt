package com.ffocalors.sharedledger.ui.profile

import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.data.activity.ActivityFinancialStatus
import com.ffocalors.sharedledger.data.activity.ActivityMember
import com.ffocalors.sharedledger.data.activity.ActivityPermissions
import com.ffocalors.sharedledger.data.activity.ActivityRole
import com.ffocalors.sharedledger.data.activity.ActivitySummary
import com.ffocalors.sharedledger.data.activity.ActivityType
import com.ffocalors.sharedledger.data.activity.Participant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonalOverviewTest {
    @Test
    fun mapsInitiatedParticipatedClaimedAndActiveCountsFromRealActivityDetails() {
        val createdAndActive = detail(
            id = "created",
            createdBy = CurrentUserId,
            status = ActivityFinancialStatus.Active,
            claimedParticipantId = "p-created",
            participantName = "我的旅行身份",
        )
        val joinedAndCompleted = detail(
            id = "completed",
            createdBy = "another-user",
            status = ActivityFinancialStatus.Completed,
        )
        val joinedAndArchived = detail(
            id = "archived",
            createdBy = "another-user",
            status = ActivityFinancialStatus.Active,
            archivedAt = "2026-09-09T08:00:00Z",
            claimedParticipantId = "p-archived",
            participantName = "归档身份",
        )

        val overview = mapPersonalOverview(
            currentUserId = CurrentUserId,
            activities = listOf(createdAndActive, joinedAndCompleted, joinedAndArchived),
        )

        assertEquals(1, overview.initiatedCount)
        assertEquals(2, overview.participatedCount)
        assertEquals(2, overview.claimedIdentityCount)
        assertEquals(1, overview.activeActivityCount)
        assertTrue(overview.identities[0].isCreator)
        assertEquals("我的旅行身份", overview.identities[0].participantName)
        assertFalse(overview.identities[1].isParticipantBound)
        assertNull(overview.identities[1].participantName)
        assertTrue(overview.identities[2].isArchived)
    }

    @Test
    fun keepsClaimedStateWhenParticipantDetailsAreTemporarilyMissing() {
        val inconsistentDetail = detail(
            id = "syncing",
            createdBy = "another-user",
            status = ActivityFinancialStatus.Active,
            claimedParticipantId = "missing-participant",
        )

        val identity = mapPersonalOverview(CurrentUserId, listOf(inconsistentDetail)).identities.single()

        assertTrue(identity.isParticipantBound)
        assertNull(identity.participantName)
    }

    private fun detail(
        id: String,
        createdBy: String,
        status: ActivityFinancialStatus,
        archivedAt: String? = null,
        claimedParticipantId: String? = null,
        participantName: String? = null,
    ): ActivityDetail {
        val summary = ActivitySummary(
            id = id,
            name = "活动 $id",
            type = ActivityType.Normal,
            joinCode = "12345678",
            baseCurrency = "CNY",
            multiCurrencyEnabled = false,
            createdBy = createdBy,
            archivedAt = archivedAt,
            participantCount = if (participantName == null) 0 else 1,
            status = status,
            totalDebt = "0.0",
            totalPrepayment = "0.0",
        )
        return ActivityDetail(
            summary = summary,
            members = listOf(
                ActivityMember(
                    id = "member-$id",
                    userId = CurrentUserId,
                    displayName = "当前用户",
                    isCreator = createdBy == CurrentUserId,
                    claimedParticipantId = claimedParticipantId,
                ),
            ),
            participants = participantName?.let {
                listOf(
                    Participant(
                        id = claimedParticipantId ?: "participant-$id",
                        activityId = id,
                        name = it,
                        order = 0,
                        claimedUserId = CurrentUserId.takeIf { claimedParticipantId != null },
                    ),
                )
            }.orEmpty(),
            ledgerUnits = emptyList(),
            currentUserRole = if (createdBy == CurrentUserId) ActivityRole.Creator else ActivityRole.Member,
            permissions = ActivityPermissions.forRole(
                if (createdBy == CurrentUserId) ActivityRole.Creator else ActivityRole.Member,
            ),
        )
    }

    private companion object {
        const val CurrentUserId = "current-user"
    }
}
