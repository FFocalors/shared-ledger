package com.ffocalors.sharedledger.data.transfer

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import java.math.BigDecimal
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

interface TransferRepository {
    suspend fun loadContext(activityId: String, direction: SettlementDirection): Result<SettlementContext>
    suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult>

    /** Keeps the existing Result API while exposing ambiguous RPC outcomes to new callers. */
    suspend fun createSettlementWrite(input: CreateSettlementTransferInput): TransferWriteResult<SettlementTransferResult> =
        createSettlement(input).toTransferWriteResult()
}

class SupabaseTransferRepository(private val client: SupabaseClient) : TransferRepository {
    override suspend fun loadContext(activityId: String, direction: SettlementDirection): Result<SettlementContext> = runCatching {
        val userId = client.auth.currentSessionOrNull()?.user?.id
            ?: throw TransferOperationException("登录状态已失效，请重新登录")
        val activity = client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<TransferActivityRowDto>()
        val participants = client.from("participants").select {
            filter {
                eq("activity_id", activityId)
                eq("is_deleted", false)
            }
        }.decodeList<TransferParticipantRowDto>()
        val claims = client.from("participant_claims").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<TransferClaimRowDto>()
        val currentClaim = client.from("participant_claims").select {
            filter {
                eq("activity_id", activityId)
                eq("user_id", userId)
            }
        }.decodeList<TransferClaimRowDto>().firstOrNull()
        val debts = client.from("bilateral_debts").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<BilateralDebtRowDto>()
        val names = participants.associate { it.id to it.name }
        val claimedParticipantIds = claims.map { it.participantId }.toSet()
        val canActOnBehalf = activity.createdBy == userId
        val candidates = selectSettlementCandidates(
            currentParticipantId = currentClaim?.participantId,
            direction = direction,
            debts = debts,
            participantNames = names,
            canActOnBehalf = canActOnBehalf,
            claimedParticipantIds = claimedParticipantIds,
        )
        SettlementContext(
            activityId = activityId,
            currentParticipantId = currentClaim?.participantId,
            currentParticipantName = currentClaim?.participantId?.let(names::get),
            baseCurrency = activity.baseCurrency.trim().uppercase(),
            candidates = candidates,
            canActOnBehalf = canActOnBehalf,
        )
    }.mapFailure()

    override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> = runCatching {
        require(input.amount > BigDecimal.ZERO) { "transfer amount must be positive" }
        val response = client.postgrest.rpc("create_settlement_transfer", SettlementRpcPayloadBuilder.create(input))
            .decodeSingle<CreateSettlementTransferRpcDto>()
        SettlementTransferResult(
            transferId = response.transferId,
            amount = response.amount.toBigDecimalOrNull() ?: input.amount,
            currency = response.currency,
            financialVersion = response.financialVersion,
        )
    }.mapFailure()

    override suspend fun createSettlementWrite(input: CreateSettlementTransferInput): TransferWriteResult<SettlementTransferResult> =
        createSettlement(input).toTransferWriteResult()

    private fun <T> Result<T>.mapFailure(): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = { Result.failure(it.takeIf { error -> error is TransferOperationException } ?: TransferOperationException(TransferErrorMapper.toUserMessage(it), it)) },
    )
}

internal fun <T> Result<T>.toTransferWriteResult(): TransferWriteResult<T> = fold(
    onSuccess = { TransferWriteResult.success(it) },
    onFailure = {
        if (TransferErrorMapper.isTransferNetworkFailure(it)) {
            TransferWriteResult.unknown("转账写入结果未知，请先刷新资金记录确认，勿重复提交")
        } else {
            TransferWriteResult.failure(TransferErrorMapper.toUserMessage(it))
        }
    },
)

internal fun selectSettlementCandidates(
    currentParticipantId: String?,
    direction: SettlementDirection,
    debts: List<BilateralDebtRowDto>,
    participantNames: Map<String, String>,
    canActOnBehalf: Boolean = false,
    claimedParticipantIds: Set<String> = emptySet(),
): List<SettlementCandidate> = currentParticipantId?.let { currentId ->
    debts.mapNotNull { debt ->
        val candidateId = when (direction) {
            SettlementDirection.TRANSFER -> debt.creditorParticipantId.takeIf { canActOnBehalf || debt.debtorParticipantId == currentId }
            SettlementDirection.RECEIVE -> debt.debtorParticipantId.takeIf { canActOnBehalf || debt.creditorParticipantId == currentId }
        }
        val amount = debt.amount.toBigDecimalOrNull()
        candidateId?.let { id ->
            val name = participantNames[id]
            if (name != null && amount != null && amount > BigDecimal.ZERO) {
                val fromId = debt.debtorParticipantId
                val toId = debt.creditorParticipantId
                SettlementCandidate(
                    participantId = id,
                    participantName = name,
                    amount = amount,
                    fromParticipantId = fromId,
                    fromParticipantName = participantNames[fromId],
                    toParticipantId = toId,
                    toParticipantName = participantNames[toId],
                    onBehalfOptions = listOf(fromId, toId).distinct()
                        .filter { it !in claimedParticipantIds }
                        .mapNotNull { participantId -> participantNames[participantId]?.let { SettlementParticipant(participantId, it) } },
                )
            } else null
        }
    }
}.orEmpty().let { claimedCandidates ->
    if (currentParticipantId != null || !canActOnBehalf) claimedCandidates
    else debts.mapNotNull { debt ->
        val fromId = debt.debtorParticipantId
        val toId = debt.creditorParticipantId
        val id = toId
        val amount = debt.amount.toBigDecimalOrNull() ?: return@mapNotNull null
        val name = participantNames[id] ?: return@mapNotNull null
        SettlementCandidate(
            participantId = id,
            participantName = name,
            amount = amount,
            fromParticipantId = fromId,
            fromParticipantName = participantNames[fromId],
            toParticipantId = toId,
            toParticipantName = participantNames[toId],
            onBehalfOptions = listOf(fromId, toId).distinct()
                .filter { it !in claimedParticipantIds }
                .mapNotNull { participantId -> participantNames[participantId]?.let { SettlementParticipant(participantId, it) } },
        ).takeIf { it.onBehalfOptions.isNotEmpty() }
    }
}

object TransferRepositoryFactory {
    fun create(): TransferRepository = SupabaseClientProvider.createOrNull()?.let(::SupabaseTransferRepository)
        ?: UnavailableTransferRepository()
}

class UnavailableTransferRepository : TransferRepository {
    private fun <T> unavailable(): Result<T> = Result.failure(TransferOperationException("尚未配置 Supabase，无法加载转账数据"))
    override suspend fun loadContext(activityId: String, direction: SettlementDirection) = unavailable<SettlementContext>()
    override suspend fun createSettlement(input: CreateSettlementTransferInput) = unavailable<SettlementTransferResult>()
}

private fun JsonElement?.toBigDecimalOrNull(): BigDecimal? = when (this) {
    null, JsonNull -> null
    is JsonPrimitive -> content.toBigDecimalOrNull()
    else -> null
}
