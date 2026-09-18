package com.ffocalors.sharedledger.data.activity

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.put

private const val MAX_CONCURRENT_ACTIVITY_READS = 4

/**
 * Runs independent reads with a bounded number of active operations while retaining input order.
 * A structured scope makes a failed read cancel its siblings and propagates cancellation.
 */
internal suspend fun <T, R> mapConcurrentlyPreservingOrder(
    items: List<T>,
    maxConcurrency: Int,
    block: suspend (T) -> R,
): List<R> {
    require(maxConcurrency > 0) { "maxConcurrency must be positive" }
    val permits = Semaphore(maxConcurrency)
    return coroutineScope {
        items.map { item ->
            async {
                permits.withPermit { block(item) }
            }
        }.awaitAll()
    }
}

/** A missing or logically deleted row confirms that the delete RPC took effect. */
internal fun isDeleteConfirmedByRows(rows: List<ActivityRowDto>): Boolean =
    rows.firstOrNull()?.isDeleted != false

/** Detail reads must reject a logically deleted activity even if RLS exposes its row. */
internal fun requireVisibleActivity(activity: ActivityRowDto): ActivityRowDto {
    if (activity.isDeleted) {
        throw ActivityOperationException(
            userMessage = "活动不存在或已被删除",
            kind = ActivityFailureKind.NotFound,
        )
    }
    return activity
}

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
    /** Returns active units by default; pass true for management/recovery views. */
    suspend fun listLedgerUnits(activityId: String, includeDeleted: Boolean = false): Result<List<LedgerUnit>> =
        getActivity(activityId).map { detail ->
            if (includeDeleted) detail.ledgerUnits + detail.deletedLedgerUnits else detail.ledgerUnits
        }
    suspend fun deleteSubActivity(subActivityId: String): Result<SubActivityLifecycleResult>
    suspend fun restoreSubActivity(subActivityId: String): Result<SubActivityLifecycleResult>
    suspend fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<Unit>
    suspend fun archiveActivity(activityId: String): Result<Unit>
    suspend fun unarchiveActivity(activityId: String): Result<Unit>
    suspend fun deleteActivity(activityId: String): Result<Unit>
    suspend fun removeMember(activityId: String, userId: String): Result<Unit>
    suspend fun transferCreator(activityId: String, newCreatorUserId: String): Result<Unit>
}

class SupabaseActivityRepository(private val client: SupabaseClient) : ActivityRepository {
    override suspend fun listActivities(): Result<List<ActivitySummary>> = runCatching {
        val activities = client.from("activities").select().decodeList<ActivityRowDto>()
            .filterNot { it.isDeleted }
        mapConcurrentlyPreservingOrder(activities, MAX_CONCURRENT_ACTIVITY_READS) { activity ->
            coroutineScope {
                val participantsRequest = async { loadParticipants(activity.id) }
                val statusRequest = async { loadFinancialStatus(activity.id) }
                val claimsRequest = async { loadClaims(activity.id) }
                val participants = participantsRequest.await()
                val claims = claimsRequest.await()
                val profiles = loadProfiles(claims.map { it.userId })
                toSummary(activity, participants, statusRequest.await(), claims, profiles)
            }
        }
    }.mapFailure()

    override suspend fun getActivity(activityId: String): Result<ActivityDetail> = runCatching {
        val activity = client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<ActivityRowDto>()
        requireVisibleActivity(activity)
        coroutineScope {
            // These reads only depend on the activity id and can run together.
            val participantsDeferred = async { loadParticipants(activityId) }
            val claimsDeferred = async { loadClaims(activityId) }
            val membersDeferred = async { loadMembers(activityId) }
            val unitsDeferred = async { loadLedgerUnits(activityId, includeDeleted = true) }
            val financialStatusDeferred = async { loadFinancialStatus(activityId) }

            val membersRows = membersDeferred.await()
            val profilesDeferred = async { loadProfiles(membersRows.map { it.userId }) }
            val participants = participantsDeferred.await()
            val claims = claimsDeferred.await()
            val profiles = profilesDeferred.await()
            val units = unitsDeferred.await()
            val financialStatus = financialStatusDeferred.await()
            val members = membersRows.map { member ->
                val claim = claims.firstOrNull { it.userId == member.userId }
                ActivityMember(
                    id = member.id,
                    userId = member.userId,
                    displayName = profiles[member.userId]?.displayName.orEmpty().ifBlank { "用户 ${member.userId.take(6)}" },
                    avatarStyle = profiles[member.userId]?.avatarStyle,
                    isCreator = member.userId == activity.createdBy,
                    claimedParticipantId = claim?.participantId,
                )
            }
            val role = if (activity.createdBy == client.auth.currentSessionOrNull()?.user?.id) ActivityRole.Creator else ActivityRole.Member
            ActivityDetail(
                summary = toSummary(activity, participants, financialStatus, claims, profiles),
                members = members,
                participants = participants.map { participant ->
                    val claim = claims.firstOrNull { it.participantId == participant.id }
                    Participant(
                        id = participant.id,
                        activityId = participant.activityId,
                        name = participant.name,
                        order = participant.participantOrder,
                        claimedUserId = claim?.userId,
                        claimedUserName = claim?.userId?.let { profiles[it]?.displayName.orEmpty() },
                        avatarStyle = claim?.userId?.let { profiles[it]?.avatarStyle },
                    )
                }.sortedBy { it.order },
                ledgerUnits = units.filterNot { it.isDeleted }.map(::toLedgerUnit),
                currentUserRole = role,
                permissions = ActivityPermissions.forRole(role),
                deletedLedgerUnits = units.filter { it.isDeleted }.map(::toLedgerUnit),
            )
        }
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

    override suspend fun deleteSubActivity(subActivityId: String): Result<SubActivityLifecycleResult> =
        runSubActivityLifecycle("delete_sub_activity", subActivityId, expectedDeleted = true)

    override suspend fun restoreSubActivity(subActivityId: String): Result<SubActivityLifecycleResult> =
        runSubActivityLifecycle("restore_sub_activity", subActivityId, expectedDeleted = false)

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
        val rpcResponse = client.postgrest.rpc("delete_activity", buildJsonObject { put("activity_id", activityId) })
        val deleted = runCatching { rpcResponse.decodeAs<Boolean>() }.getOrElse { decodeError ->
            // A committed RPC can still fail while decoding an unexpected scalar
            // response. Confirm the write before surfacing a failure. An empty
            // RLS result or a visible soft-deleted row both prove the write.
            if (ActivityErrorMapper.failureKind(decodeError) != ActivityFailureKind.Other) {
                throw decodeError
            }
            val confirmation = runCatching {
                client.from("activities").select {
                    filter { eq("id", activityId) }
                }.decodeList<ActivityRowDto>()
            }
            if (confirmation.isSuccess) {
                if (isDeleteConfirmedByRows(confirmation.getOrThrow())) true else throw decodeError
            } else {
                throw decodeError
            }
        }
        if (!deleted) {
            throw ActivityOperationException("删除未执行，服务器未确认删除")
        }
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

    private suspend fun loadLedgerUnits(activityId: String, includeDeleted: Boolean = false): List<LedgerUnitRowDto> = client.from("ledger_units").select {
        filter {
            eq("activity_id", activityId)
            if (!includeDeleted) eq("is_deleted", false)
        }
    }.decodeList<LedgerUnitRowDto>()

    private suspend fun loadLedgerUnit(subActivityId: String): LedgerUnitRowDto? = client.from("ledger_units").select {
        filter { eq("id", subActivityId) }
    }.decodeList<LedgerUnitRowDto>().firstOrNull()

    private suspend fun runSubActivityLifecycle(
        rpcName: String,
        subActivityId: String,
        expectedDeleted: Boolean,
    ): Result<SubActivityLifecycleResult> = runCatching {
        val response = client.postgrest.rpc(rpcName, buildJsonObject {
            // The public RPC signatures use sub_activity_id (not p_sub_activity_id).
            put("sub_activity_id", subActivityId)
        })
        val rpcResult = try {
            response.decodeSingle<SubActivityLifecycleRpcDto>()
        } catch (decodeError: Throwable) {
            // PostgREST can commit the function while a client fails to decode its
            // response. Confirm the target state by id before reporting a failure.
            val row = runCatching { loadLedgerUnit(subActivityId) }.getOrNull()
            if (row?.isDeleted == expectedDeleted) {
                return@runCatching SubActivityLifecycleResult(
                    subActivityId = row.id,
                    activityId = row.activityId,
                    changed = false,
                    isDeleted = row.isDeleted,
                    financialVersion = 0L,
                )
            }
            throw decodeError
        }
        if (rpcResult.subActivityId != subActivityId || rpcResult.isDeleted != expectedDeleted) {
            val row = runCatching { loadLedgerUnit(subActivityId) }.getOrNull()
            if (row?.isDeleted == expectedDeleted) {
                return@runCatching SubActivityLifecycleResult(
                    subActivityId = row.id,
                    activityId = row.activityId,
                    changed = false,
                    isDeleted = row.isDeleted,
                    financialVersion = rpcResult.financialVersion,
                )
            }
            throw ActivityOperationException("服务器未确认子活动状态")
        }
        SubActivityLifecycleResult(
            subActivityId = rpcResult.subActivityId,
            activityId = rpcResult.activityId,
            changed = rpcResult.changed,
            isDeleted = rpcResult.isDeleted,
            financialVersion = rpcResult.financialVersion,
        )
    }.mapFailure()

    private fun toLedgerUnit(row: LedgerUnitRowDto): LedgerUnit = LedgerUnit(
        id = row.id,
        activityId = row.activityId,
        name = row.name,
        type = row.type,
        createdAt = row.createdAt,
        isDeleted = row.isDeleted,
        deletedAt = row.deletedAt,
        deletedBy = row.deletedBy,
    )

    private suspend fun loadProfiles(userIds: List<String>): Map<String, ProfileRowDto> {
        if (userIds.isEmpty()) return emptyMap()
        return client.from("profiles").select {
            filter { isIn("id", userIds) }
        }.decodeList<ProfileRowDto>().associateBy { it.id }
    }

    private suspend fun loadFinancialStatus(activityId: String): FinancialStatusRowDto =
        client.from("activity_financial_status").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialStatusRowDto>().firstOrNull()
            ?: FinancialStatusRowDto(activityId, "active", false, null, null, 0)

    private fun toSummary(
        activity: ActivityRowDto,
        participants: List<ParticipantRowDto>,
        status: FinancialStatusRowDto,
        claims: List<ParticipantClaimRowDto> = emptyList(),
        profiles: Map<String, ProfileRowDto> = emptyMap(),
    ) = ActivitySummary(
        id = activity.id,
        name = activity.name,
        type = if (activity.type.equals("large", true)) ActivityType.Large else ActivityType.Normal,
        joinCode = activity.joinCode,
        baseCurrency = activity.baseCurrency.trim(),
        multiCurrencyEnabled = activity.multiCurrencyEnabled,
        createdBy = activity.createdBy,
        archivedAt = activity.archivedAt,
        participantsLockedAt = activity.participantsLockedAt,
        participantCount = participants.size,
        participantNames = participants.sortedBy { it.participantOrder }.map { it.name },
        participantAvatars = participants.sortedBy { it.participantOrder }.map { participant ->
            val claim = claims.firstOrNull { it.participantId == participant.id }
            ParticipantAvatarSummary(
                participantId = participant.id,
                name = participant.name,
                claimedUserId = claim?.userId,
                avatarStyle = claim?.userId?.let { profiles[it]?.avatarStyle },
            )
        },
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
        onFailure = {
            if (it is CancellationException) throw it
            if (it is ActivityOperationException) return@fold Result.failure(it)
            Result.failure(
                ActivityOperationException(
                    userMessage = ActivityErrorMapper.toUserMessage(it),
                    cause = it,
                    kind = ActivityErrorMapper.failureKind(it),
                ),
            )
        },
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
    override suspend fun deleteSubActivity(subActivityId: String) = unavailable<SubActivityLifecycleResult>()
    override suspend fun restoreSubActivity(subActivityId: String) = unavailable<SubActivityLifecycleResult>()
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
