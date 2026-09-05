package com.ffocalors.sharedledger.data.activity

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.put

interface ActivityRepository {
    suspend fun listActivities(): Result<List<ActivitySummary>>
    suspend fun getActivity(activityId: String): Result<ActivityDetail>
    suspend fun createActivity(name: String, type: ActivityType, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<ActivitySummary>
    suspend fun joinActivity(joinCode: String): Result<ActivityDetail>
    suspend fun createParticipant(activityId: String, name: String): Result<Participant>
    suspend fun claimParticipant(activityId: String, participantId: String): Result<Unit>
    suspend fun unclaimParticipant(activityId: String): Result<Unit>
    suspend fun deleteParticipant(participantId: String): Result<Unit>
    suspend fun createSubActivity(activityId: String, name: String): Result<LedgerUnit>
    suspend fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<Unit>
    suspend fun archiveActivity(activityId: String): Result<Unit>
    suspend fun unarchiveActivity(activityId: String): Result<Unit>
    suspend fun deleteActivity(activityId: String): Result<Unit>
    suspend fun removeMember(activityId: String, userId: String): Result<Unit>
    suspend fun transferCreator(activityId: String, newCreatorUserId: String): Result<Unit>
}

class SupabaseActivityRepository(private val client: SupabaseClient) : ActivityRepository {
    override suspend fun listActivities(): Result<List<ActivitySummary>> = runCatching {
        client.from("activities").select().decodeList<ActivityRowDto>()
            .filterNot { it.isDeleted }
            .map { activity -> toSummary(activity, loadParticipants(activity.id), loadFinancialStatus(activity.id)) }
    }.mapFailure()

    override suspend fun getActivity(activityId: String): Result<ActivityDetail> = runCatching {
        val activity = client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<ActivityRowDto>()
        val participants = loadParticipants(activityId)
        val claims = loadClaims(activityId)
        val membersRows = loadMembers(activityId)
        val profiles = loadProfiles(membersRows.map { it.userId })
        val units = client.from("ledger_units").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<LedgerUnitRowDto>().filterNot { it.isDeleted }
        val members = membersRows.map { member ->
            val claim = claims.firstOrNull { it.userId == member.userId }
            ActivityMember(
                id = member.id,
                userId = member.userId,
                displayName = profiles[member.userId].orEmpty().ifBlank { "用户 ${member.userId.take(6)}" },
                isCreator = member.userId == activity.createdBy,
                claimedParticipantId = claim?.participantId,
            )
        }
        val role = if (activity.createdBy == client.auth.currentSessionOrNull()?.user?.id) ActivityRole.Creator else ActivityRole.Member
        ActivityDetail(
            summary = toSummary(activity, participants, loadFinancialStatus(activityId)),
            members = members,
            participants = participants.map { participant ->
                val claim = claims.firstOrNull { it.participantId == participant.id }
                Participant(
                    id = participant.id,
                    activityId = participant.activityId,
                    name = participant.name,
                    order = participant.participantOrder,
                    claimedUserId = claim?.userId,
                    claimedUserName = claim?.userId?.let { profiles[it] },
                )
            }.sortedBy { it.order },
            ledgerUnits = units.map { LedgerUnit(it.id, it.activityId, it.name, it.type, it.createdAt) },
            currentUserRole = role,
            permissions = ActivityPermissions.forRole(role),
        )
    }.mapFailure()

    override suspend fun createActivity(name: String, type: ActivityType, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<ActivitySummary> = runCatching {
        val result = client.postgrest.rpc("create_activity", buildJsonObject {
            put("name", name.trim())
            put("type", type.backendValue)
            put("base_currency", baseCurrency.trim().uppercase())
            put("multi_currency_enabled", multiCurrencyEnabled)
        }).decodeSingle<CreateActivityRpcDto>()
        getActivity(result.activityId).getOrThrow().summary
    }.mapFailure()

    override suspend fun joinActivity(joinCode: String): Result<ActivityDetail> = runCatching {
        val result = client.postgrest.rpc("join_activity_by_code", buildJsonObject { put("join_code", joinCode.filter(Char::isDigit)) })
            .decodeSingle<JoinActivityRpcDto>()
        getActivity(result.activityId).getOrThrow()
    }.mapFailure()

    override suspend fun createParticipant(activityId: String, name: String): Result<Participant> = runCatching {
        val result = client.postgrest.rpc("create_participant", buildJsonObject {
            put("activity_id", activityId)
            put("name", name.trim())
        }).decodeSingle<CreateParticipantRpcDto>()
        Participant(result.participantId, activityId, result.participantName, result.participantOrder)
    }.mapFailure()

    override suspend fun claimParticipant(activityId: String, participantId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("claim_participant", buildJsonObject {
            put("activity_id", activityId)
            put("participant_id", participantId)
        }).decodeSingle<ClaimParticipantRpcDto>()
        Unit
    }.mapFailure()

    override suspend fun unclaimParticipant(activityId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("unclaim_participant", buildJsonObject { put("activity_id", activityId) }).decodeSingle<Boolean>()
        Unit
    }.mapFailure()

    override suspend fun deleteParticipant(participantId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("delete_participant", buildJsonObject { put("participant_id", participantId) })
            .decodeSingle<DeleteParticipantRpcDto>()
        Unit
    }.mapFailure()

    override suspend fun createSubActivity(activityId: String, name: String): Result<LedgerUnit> = runCatching {
        val result = client.postgrest.rpc("create_sub_activity", buildJsonObject {
            put("activity_id", activityId)
            put("name", name.trim())
        }).decodeSingle<CreateSubActivityRpcDto>()
        LedgerUnit(result.ledgerUnitId, activityId, result.createdName, result.createdType)
    }.mapFailure()

    override suspend fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<Unit> = runCatching {
        client.postgrest.rpc("update_activity_settings", buildJsonObject {
            put("activity_id", activityId)
            put("name", name.trim())
            put("base_currency", baseCurrency.trim().uppercase())
            put("multi_currency_enabled", multiCurrencyEnabled)
        }).decodeSingle<UpdateActivitySettingsRpcDto>()
        Unit
    }.mapFailure()

    override suspend fun archiveActivity(activityId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("archive_activity", buildJsonObject { put("p_activity_id", activityId) }).decodeSingle<ArchiveRpcDto>()
        Unit
    }.mapFailure()

    override suspend fun unarchiveActivity(activityId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("unarchive_activity", buildJsonObject { put("p_activity_id", activityId) })
            .decodeSingle<ArchiveRpcDto>()
        Unit
    }.mapFailure()

    override suspend fun deleteActivity(activityId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("delete_activity", buildJsonObject { put("activity_id", activityId) }).decodeSingle<Boolean>()
        Unit
    }.mapFailure()

    override suspend fun removeMember(activityId: String, userId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("remove_activity_member", buildJsonObject {
            put("activity_id", activityId)
            put("user_id", userId)
        }).decodeSingle<Boolean>()
        Unit
    }.mapFailure()

    override suspend fun transferCreator(activityId: String, newCreatorUserId: String): Result<Unit> = runCatching {
        client.postgrest.rpc("transfer_activity_creator", buildJsonObject {
            put("activity_id", activityId)
            put("new_creator_user_id", newCreatorUserId)
        }).decodeSingle<String>()
        Unit
    }.mapFailure()

    private suspend fun loadParticipants(activityId: String): List<ParticipantRowDto> = client.from("participants").select {
        filter { eq("activity_id", activityId) }
    }.decodeList<ParticipantRowDto>().filterNot { it.isDeleted }

    private suspend fun loadMembers(activityId: String): List<ActivityMemberRowDto> = client.from("activity_members").select {
        filter { eq("activity_id", activityId) }
    }.decodeList()

    private suspend fun loadClaims(activityId: String): List<ParticipantClaimRowDto> = client.from("participant_claims").select {
        filter { eq("activity_id", activityId) }
    }.decodeList()

    private suspend fun loadProfiles(userIds: List<String>): Map<String, String> {
        if (userIds.isEmpty()) return emptyMap()
        return client.from("profiles").select {
            filter { isIn("id", userIds) }
        }.decodeList<ProfileRowDto>().associate { it.id to it.displayName.orEmpty() }
    }

    private suspend fun loadFinancialStatus(activityId: String): FinancialStatusRowDto =
        client.from("activity_financial_status").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialStatusRowDto>().firstOrNull()
            ?: FinancialStatusRowDto(activityId, "active", false, null, null, 0)

    private fun toSummary(activity: ActivityRowDto, participants: List<ParticipantRowDto>, status: FinancialStatusRowDto) = ActivitySummary(
        id = activity.id,
        name = activity.name,
        type = if (activity.type.equals("large", true)) ActivityType.Large else ActivityType.Normal,
        joinCode = activity.joinCode,
        baseCurrency = activity.baseCurrency.trim(),
        multiCurrencyEnabled = activity.multiCurrencyEnabled,
        createdBy = activity.createdBy,
        archivedAt = activity.archivedAt,
        participantCount = participants.size,
        participantNames = participants.sortedBy { it.participantOrder }.map { it.name },
        status = if (status.completed) ActivityFinancialStatus.Completed else ActivityFinancialStatus.Active,
        totalDebt = status.totalDebt.toDecimalText(),
        totalPrepayment = status.totalPrepayment.toDecimalText(),
        financialVersion = status.financialVersion,
    )

    private fun JsonElement?.toDecimalText(): String = when (this) {
        null, JsonNull -> "0.0"
        is JsonPrimitive -> content.ifBlank { "0.0" }
        else -> "0.0"
    }

    private fun <T> Result<T>.mapFailure(): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = { Result.failure(ActivityOperationException(ActivityErrorMapper.toUserMessage(it), it)) },
    )
}

@kotlinx.serialization.Serializable
private data class ArchiveRpcDto(
    @kotlinx.serialization.SerialName("activity_id") val activityId: String,
    val archived: Boolean,
)

object ActivityRepositoryFactory {
    fun create(): ActivityRepository = com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider.createOrNull()
        ?.let(::SupabaseActivityRepository)
        ?: UnavailableActivityRepository()
}

class UnavailableActivityRepository : ActivityRepository {
    private fun <T> unavailable(): Result<T> = Result.failure(ActivityOperationException("尚未配置 Supabase，无法加载活动数据"))
    override suspend fun listActivities() = unavailable<List<ActivitySummary>>()
    override suspend fun getActivity(activityId: String) = unavailable<ActivityDetail>()
    override suspend fun createActivity(name: String, type: ActivityType, baseCurrency: String, multiCurrencyEnabled: Boolean) = unavailable<ActivitySummary>()
    override suspend fun joinActivity(joinCode: String) = unavailable<ActivityDetail>()
    override suspend fun createParticipant(activityId: String, name: String) = unavailable<Participant>()
    override suspend fun claimParticipant(activityId: String, participantId: String) = unavailable<Unit>()
    override suspend fun unclaimParticipant(activityId: String) = unavailable<Unit>()
    override suspend fun deleteParticipant(participantId: String) = unavailable<Unit>()
    override suspend fun createSubActivity(activityId: String, name: String) = unavailable<LedgerUnit>()
    override suspend fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrencyEnabled: Boolean) = unavailable<Unit>()
    override suspend fun archiveActivity(activityId: String) = unavailable<Unit>()
    override suspend fun unarchiveActivity(activityId: String) = unavailable<Unit>()
    override suspend fun deleteActivity(activityId: String) = unavailable<Unit>()
    override suspend fun removeMember(activityId: String, userId: String) = unavailable<Unit>()
    override suspend fun transferCreator(activityId: String, newCreatorUserId: String) = unavailable<Unit>()
}

@kotlinx.serialization.Serializable
private data class DeleteParticipantRpcDto(
    @kotlinx.serialization.SerialName("participant_id") val participantId: String,
    val deleted: Boolean,
)
