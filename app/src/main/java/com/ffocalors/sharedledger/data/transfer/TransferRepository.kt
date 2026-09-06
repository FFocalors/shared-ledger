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
        val candidates = selectSettlementCandidates(currentClaim?.participantId, direction, debts, names)
        SettlementContext(
            activityId = activityId,
            currentParticipantId = currentClaim?.participantId,
            currentParticipantName = currentClaim?.participantId?.let(names::get),
            baseCurrency = activity.baseCurrency.trim().uppercase(),
            candidates = candidates,
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

    private fun <T> Result<T>.mapFailure(): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = { Result.failure(it.takeIf { error -> error is TransferOperationException } ?: TransferOperationException(TransferErrorMapper.toUserMessage(it), it)) },
    )
}

internal fun selectSettlementCandidates(
    currentParticipantId: String?,
    direction: SettlementDirection,
    debts: List<BilateralDebtRowDto>,
    participantNames: Map<String, String>,
): List<SettlementCandidate> = currentParticipantId?.let { currentId ->
    debts.mapNotNull { debt ->
        val candidateId = when (direction) {
            SettlementDirection.TRANSFER -> debt.creditorParticipantId.takeIf { debt.debtorParticipantId == currentId }
            SettlementDirection.RECEIVE -> debt.debtorParticipantId.takeIf { debt.creditorParticipantId == currentId }
        }
        val amount = debt.amount.toBigDecimalOrNull()
        candidateId?.let { id ->
            val name = participantNames[id]
            if (name != null && amount != null && amount > BigDecimal.ZERO) {
                SettlementCandidate(id, name, amount)
            } else null
        }
    }
}.orEmpty()

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
