package com.ffocalors.sharedledger.data.activity

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

enum class ActivityType(val backendValue: String) {
    Normal("normal"),
    Large("large"),
}

enum class ActivityFinancialStatus { Active, Completed }

enum class ActivityRole { Creator, Member }

data class ActivityPermissions(
    val role: ActivityRole,
    val canManageParticipants: Boolean,
    val canManageMembers: Boolean,
    val canEditSettings: Boolean,
    val canCreateSubActivity: Boolean,
    val canArchive: Boolean,
    val canDelete: Boolean,
) {
    companion object {
        fun forRole(role: ActivityRole): ActivityPermissions = when (role) {
            ActivityRole.Creator -> ActivityPermissions(role, true, true, true, true, true, true)
            ActivityRole.Member -> ActivityPermissions(role, false, false, false, false, false, false)
        }
    }
}

@Serializable
data class ActivityRowDto(
    val id: String,
    val name: String,
    val type: String,
    @SerialName("join_code") val joinCode: String,
    @SerialName("base_currency") val baseCurrency: String,
    @SerialName("multi_currency_enabled") val multiCurrencyEnabled: Boolean,
    @SerialName("created_by") val createdBy: String,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("archived_at") val archivedAt: String? = null,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
    @SerialName("financial_version") val financialVersion: Long = 0,
)

@Serializable
data class ActivityMemberRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("user_id") val userId: String,
    @SerialName("joined_at") val joinedAt: String? = null,
)

@Serializable
data class ParticipantRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    val name: String,
    @SerialName("participant_order") val participantOrder: Int,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
data class ParticipantClaimRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("participant_id") val participantId: String,
    @SerialName("user_id") val userId: String,
    @SerialName("claimed_at") val claimedAt: String? = null,
)

@Serializable
data class LedgerUnitRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    val name: String,
    val type: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class ProfileRowDto(
    val id: String,
    @SerialName("display_name") val displayName: String? = null,
)

@Serializable
data class CreateActivityRpcDto(
    @SerialName("activity_id") val activityId: String,
    @SerialName("join_code") val joinCode: String,
    @SerialName("activity_name") val activityName: String,
    @SerialName("activity_type") val activityType: String,
    @SerialName("activity_base_currency") val activityBaseCurrency: String,
    @SerialName("activity_multi_currency_enabled") val activityMultiCurrencyEnabled: Boolean,
)

@Serializable
data class JoinActivityRpcDto(
    @SerialName("activity_id") val activityId: String,
    @SerialName("is_new") val isNew: Boolean,
)

@Serializable
data class CreateSubActivityRpcDto(
    @SerialName("parent_activity_id") val parentActivityId: String,
    @SerialName("ledger_unit_id") val ledgerUnitId: String,
    @SerialName("created_name") val createdName: String,
    @SerialName("created_type") val createdType: String,
)

@Serializable
data class CreateParticipantRpcDto(
    @SerialName("participant_id") val participantId: String,
    @SerialName("participant_name") val participantName: String,
    @SerialName("participant_order") val participantOrder: Int,
)

@Serializable
data class ClaimParticipantRpcDto(
    @SerialName("claim_id") val claimId: String,
    @SerialName("claimed_participant_id") val claimedParticipantId: String,
    @SerialName("is_new") val isNew: Boolean,
)

@Serializable
data class UpdateActivitySettingsRpcDto(
    @SerialName("activity_id") val activityId: String,
    @SerialName("activity_name") val activityName: String,
    @SerialName("activity_base_currency") val activityBaseCurrency: String,
    @SerialName("activity_multi_currency_enabled") val activityMultiCurrencyEnabled: Boolean,
)

@Serializable
data class FinancialStatusRowDto(
    @SerialName("activity_id") val activityId: String,
    @SerialName("financial_status") val financialStatus: String,
    val completed: Boolean,
    // PostgREST returns numeric columns as JSON numbers. Keep the raw JSON at
    // the transport boundary so both numeric and legacy quoted values decode.
    @SerialName("total_debt") val totalDebt: JsonElement? = null,
    @SerialName("total_prepayment") val totalPrepayment: JsonElement? = null,
    @SerialName("financial_version") val financialVersion: Long = 0,
)

data class ActivitySummary(
    val id: String,
    val name: String,
    val type: ActivityType,
    val joinCode: String,
    val baseCurrency: String,
    val multiCurrencyEnabled: Boolean,
    val createdBy: String,
    val archivedAt: String?,
    val participantCount: Int,
    val participantNames: List<String> = emptyList(),
    val status: ActivityFinancialStatus,
    val totalDebt: String,
    val totalPrepayment: String,
    val financialVersion: Long = 0,
)

data class ActivityMember(
    val id: String,
    val userId: String,
    val displayName: String,
    val isCreator: Boolean,
    val claimedParticipantId: String? = null,
)

data class Participant(
    val id: String,
    val activityId: String,
    val name: String,
    val order: Int,
    val claimedUserId: String? = null,
    val claimedUserName: String? = null,
)

data class LedgerUnit(
    val id: String,
    val activityId: String,
    val name: String,
    val type: String,
    val createdAt: String? = null,
)

data class ActivityDetail(
    val summary: ActivitySummary,
    val members: List<ActivityMember>,
    val participants: List<Participant>,
    val ledgerUnits: List<LedgerUnit>,
    val currentUserRole: ActivityRole,
    val permissions: ActivityPermissions,
)

class ActivityOperationException(val userMessage: String, cause: Throwable? = null) : RuntimeException(userMessage, cause)

fun ActivityType.toUiKind(): com.ffocalors.sharedledger.ui.components.ActivityKind = when (this) {
    ActivityType.Normal -> com.ffocalors.sharedledger.ui.components.ActivityKind.Standard
    ActivityType.Large -> com.ffocalors.sharedledger.ui.components.ActivityKind.Large
}
