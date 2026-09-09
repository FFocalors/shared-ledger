package com.ffocalors.sharedledger.ui.profile

import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.data.activity.ActivityFinancialStatus
import com.ffocalors.sharedledger.data.activity.ActivityType

data class PersonalOverview(
    val initiatedCount: Int,
    val participatedCount: Int,
    val claimedIdentityCount: Int,
    val activeActivityCount: Int,
    val identities: List<CollaborationIdentity>,
)

data class CollaborationIdentity(
    val activityId: String,
    val activityName: String,
    val activityType: ActivityType,
    val isCreator: Boolean,
    val isParticipantBound: Boolean,
    val participantName: String?,
    val isArchived: Boolean,
)

data class PersonalOverviewUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val overview: PersonalOverview? = null,
    val errorMessage: String? = null,
)

internal fun mapPersonalOverview(
    currentUserId: String,
    activities: List<ActivityDetail>,
): PersonalOverview {
    val identities = activities.map { activity ->
        val currentMember = activity.members.firstOrNull { it.userId == currentUserId }
        val claimedParticipantId = currentMember?.claimedParticipantId
        CollaborationIdentity(
            activityId = activity.summary.id,
            activityName = activity.summary.name,
            activityType = activity.summary.type,
            isCreator = activity.summary.createdBy == currentUserId,
            isParticipantBound = claimedParticipantId != null,
            participantName = claimedParticipantId?.let { participantId ->
                activity.participants.firstOrNull { it.id == participantId }?.name
            },
            isArchived = activity.summary.archivedAt != null,
        )
    }
    return PersonalOverview(
        initiatedCount = activities.count { it.summary.createdBy == currentUserId },
        participatedCount = activities.count { it.summary.createdBy != currentUserId },
        claimedIdentityCount = identities.count { it.isParticipantBound },
        activeActivityCount = activities.count {
            it.summary.archivedAt == null && it.summary.status != ActivityFinancialStatus.Completed
        },
        identities = identities,
    )
}
