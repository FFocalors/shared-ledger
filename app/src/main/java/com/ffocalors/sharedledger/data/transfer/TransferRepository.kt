package com.ffocalors.sharedledger.data.transfer

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.exception.PostgrestRestException
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import java.math.BigDecimal
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

interface TransferRepository {
    suspend fun loadContext(activityId: String, direction: SettlementDirection): Result<SettlementContext>
    suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult>

    /** Keeps the existing Result API while exposing ambiguous RPC outcomes to new callers. */
    suspend fun createSettlementWrite(input: CreateSettlementTransferInput): TransferWriteResult<SettlementTransferResult> =
        createSettlement(input).toTransferWriteResult()
}

class SupabaseTransferRepository(private val client: SupabaseClient) : TransferRepository {
    /** Null until the capability has been observed; false means the old server contract. */
    private var supportsMultiCurrencySettlement: Boolean? = null
    private var loadedBaseCurrency: String? = null

    override suspend fun loadContext(activityId: String, direction: SettlementDirection): Result<SettlementContext> = runCatching {
        val userId = client.auth.currentSessionOrNull()?.user?.id
            ?: throw TransferOperationException("登录状态已失效，请重新登录")
        val activity = client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<TransferActivityRowDto>()
        val baseCurrency = activity.baseCurrency.trim().uppercase()
        loadedBaseCurrency = baseCurrency
        val participants = client.from("participants").select {
            filter {
                eq("activity_id", activityId)
                eq("is_deleted", false)
            }
        }.decodeList<TransferParticipantRowDto>()
        val claims = client.from("participant_claims").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<TransferClaimRowDto>()
        val userIds = claims.mapNotNull { it.userId }.distinct()
        val profiles = if (userIds.isEmpty()) emptyMap() else client.from("profiles").select {
            filter { isIn("id", userIds) }
        }.decodeList<TransferProfileRowDto>().associateBy { it.id }
        val avatarInfo = claims.mapNotNull { claim ->
            val claimedUserId = claim.userId ?: return@mapNotNull null
            claim.participantId to SettlementAvatarInfo(claimedUserId, profiles[claimedUserId]?.avatarStyle)
        }.toMap()
        val currentClaim = client.from("participant_claims").select {
            filter {
                eq("activity_id", activityId)
                eq("user_id", userId)
            }
        }.decodeList<TransferClaimRowDto>().firstOrNull()
        // The options RPC is the authoritative, currency-aware read model. Do not filter
        // these rows by the currently enabled ECB currency list: old external debts remain
        // payable after the activity switch is turned off.
        val options = try {
            client.postgrest.rpc(
                "list_settlement_options",
                buildJsonObject { put("p_activity_id", activityId) },
            ).decodeList<SettlementOptionRowDto>().also {
                supportsMultiCurrencySettlement = true
            }
        } catch (error: Throwable) {
            if (!isMissingSettlementRpc(error)) throw error
            // The Android client can be upgraded before the linked Supabase migration.
            // Keep the old read model usable until the new RPC is deployed; it only exposes
            // the legacy base-currency debt and never fabricates external-currency options.
            supportsMultiCurrencySettlement = false
            client.from("bilateral_debts").select {
                filter { eq("activity_id", activityId) }
            }.decodeList<BilateralDebtRowDto>().map { debt ->
                SettlementOptionRowDto(
                    debtorParticipantId = debt.debtorParticipantId,
                    creditorParticipantId = debt.creditorParticipantId,
                    currency = baseCurrency,
                    originalAmount = debt.amount,
                    baseAmount = debt.amount,
                    financialVersion = 0L,
                    baseTotal = debt.amount,
                )
            }
        }
        val names = participants.associate { it.id to it.name }
        val claimedParticipantIds = claims.map { it.participantId }.toSet()
        val canActOnBehalf = activity.createdBy == userId
        val candidates = selectSettlementOptionCandidates(
            currentParticipantId = currentClaim?.participantId,
            direction = direction,
            options = options,
            participantNames = names,
            baseCurrency = baseCurrency,
            participantAvatars = avatarInfo,
        )
        val onBehalfCandidates = selectOnBehalfSettlementOptionCandidates(
            currentParticipantId = currentClaim?.participantId,
            direction = direction,
            options = options,
            participantNames = names,
            baseCurrency = baseCurrency,
            canActOnBehalf = canActOnBehalf,
            claimedParticipantIds = claimedParticipantIds,
            participantAvatars = avatarInfo,
        )
        SettlementContext(
            activityId = activityId,
            currentParticipantId = currentClaim?.participantId,
            currentParticipantName = currentClaim?.participantId?.let(names::get),
            baseCurrency = activity.baseCurrency.trim().uppercase(),
            multiCurrencyEnabled = activity.multiCurrencyEnabled,
            candidates = candidates,
            onBehalfCandidates = onBehalfCandidates,
            canActOnBehalf = canActOnBehalf,
        )
    }.mapFailure()

    override suspend fun createSettlement(input: CreateSettlementTransferInput): Result<SettlementTransferResult> = runCatching {
        require(input.amount > BigDecimal.ZERO) { "transfer amount must be positive" }
        val response = if (supportsMultiCurrencySettlement != false) {
            try {
                client.postgrest.rpc("create_settlement_transfer", SettlementRpcPayloadBuilder.create(input))
                    .decodeSingle<CreateSettlementTransferRpcDto>()
                    .also { supportsMultiCurrencySettlement = true }
            } catch (error: Throwable) {
                if (!isMissingSettlementRpc(error)) throw error
                supportsMultiCurrencySettlement = false
                createLegacySettlement(input)
            }
        } else {
            createLegacySettlement(input)
        }
        SettlementTransferResult(
            transferId = response.transferId,
            amount = response.amount.toBigDecimalOrNull() ?: input.amount,
            currency = response.currency,
            financialVersion = response.financialVersion,
        )
    }.mapFailure()

    private suspend fun createLegacySettlement(input: CreateSettlementTransferInput): CreateSettlementTransferRpcDto {
        val baseCurrency = loadedBaseCurrency
            ?: throw TransferOperationException("请先刷新转账页面")
        if (input.currency.trim().uppercase() != baseCurrency) {
            throw TransferOperationException("当前服务端尚未部署多币种转账，请使用 $baseCurrency 结算")
        }
        return client.postgrest.rpc(
            "create_settlement_transfer",
            SettlementRpcPayloadBuilder.createLegacy(input),
        ).decodeSingle()
    }

    override suspend fun createSettlementWrite(input: CreateSettlementTransferInput): TransferWriteResult<SettlementTransferResult> =
        createSettlement(input).toTransferWriteResult()

    private fun <T> Result<T>.mapFailure(): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = {
            if (it is CancellationException) throw it
            Result.failure(
                it.takeIf { error -> error is TransferOperationException }
                    ?: TransferOperationException(
                        TransferErrorMapper.toUserMessage(it),
                        it,
                        TransferErrorMapper.failureKind(it),
                    ),
            )
        },
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

/** PostgREST uses PGRST202 (HTTP 404) when an RPC is absent from the schema cache. */
internal fun isMissingSettlementRpc(error: Throwable): Boolean {
    var current: Throwable? = error
    while (current != null) {
        if (current is PostgrestRestException &&
            (current.code.equals("PGRST202", ignoreCase = true) || current.statusCode == 404)
        ) {
            return true
        }
        current = current.cause
    }
    return false
}

internal fun selectSettlementCandidates(
    currentParticipantId: String?,
    direction: SettlementDirection,
    debts: List<BilateralDebtRowDto>,
    participantNames: Map<String, String>,
    participantAvatars: Map<String, SettlementAvatarInfo> = emptyMap(),
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
                val fromId = debt.debtorParticipantId
                val toId = debt.creditorParticipantId
                SettlementCandidate(
                    participantId = id,
                    participantName = name,
                    amount = amount,
                    fromParticipantId = fromId,
                    fromParticipantName = participantNames[fromId] ?: return@let null,
                    toParticipantId = toId,
                    toParticipantName = participantNames[toId] ?: return@let null,
                    claimedUserId = participantAvatars[id]?.claimedUserId,
                    avatarStyle = participantAvatars[id]?.avatarStyle,
                )
            } else null
        }
    }
}.orEmpty()

internal fun selectOnBehalfSettlementCandidates(
    currentParticipantId: String?,
    direction: SettlementDirection,
    debts: List<BilateralDebtRowDto>,
    participantNames: Map<String, String>,
    canActOnBehalf: Boolean,
    claimedParticipantIds: Set<String>,
    participantAvatars: Map<String, SettlementAvatarInfo> = emptyMap(),
): List<SettlementCandidate> {
    if (!canActOnBehalf) return emptyList()
    return debts.mapNotNull { debt ->
        val fromId = debt.debtorParticipantId
        val toId = debt.creditorParticipantId
        if (currentParticipantId == fromId || currentParticipantId == toId) return@mapNotNull null
        val actingParticipantId = when (direction) {
            SettlementDirection.TRANSFER -> fromId
            SettlementDirection.RECEIVE -> toId
        }
        if (actingParticipantId in claimedParticipantIds) return@mapNotNull null
        val id = when (direction) {
            SettlementDirection.TRANSFER -> toId
            SettlementDirection.RECEIVE -> fromId
        }
        val amount = debt.amount.toBigDecimalOrNull() ?: return@mapNotNull null
        if (amount <= BigDecimal.ZERO) return@mapNotNull null
        val name = participantNames[id] ?: return@mapNotNull null
        val fromName = participantNames[fromId] ?: return@mapNotNull null
        val toName = participantNames[toId] ?: return@mapNotNull null
        SettlementCandidate(
            participantId = id,
            participantName = name,
            amount = amount,
            fromParticipantId = fromId,
            fromParticipantName = fromName,
            toParticipantId = toId,
            toParticipantName = toName,
            kind = SettlementCandidateKind.ON_BEHALF,
            onBehalfOptions = listOf(SettlementParticipant(actingParticipantId, participantNames.getValue(actingParticipantId))),
            claimedUserId = participantAvatars[id]?.claimedUserId,
            avatarStyle = participantAvatars[id]?.avatarStyle,
        )
    }
}

/**
 * Groups the server's currency-aware option rows into the existing candidate identity. The
 * candidate remains one directed pair (so two currencies do not collide), while its options
 * retain the server-provided per-currency caps used by the transfer form.
 */
internal fun selectSettlementOptionCandidates(
    currentParticipantId: String?,
    direction: SettlementDirection,
    options: List<SettlementOptionRowDto>,
    participantNames: Map<String, String>,
    baseCurrency: String,
    participantAvatars: Map<String, SettlementAvatarInfo> = emptyMap(),
): List<SettlementCandidate> = currentParticipantId?.let { currentId ->
    options
        .groupBy { it.debtorParticipantId to it.creditorParticipantId }
        .mapNotNull { (endpoints, rows) ->
            val (fromId, toId) = endpoints
            val candidateId = when (direction) {
                SettlementDirection.TRANSFER -> toId.takeIf { fromId == currentId }
                SettlementDirection.RECEIVE -> fromId.takeIf { toId == currentId }
            } ?: return@mapNotNull null
            settlementCandidateFromOptions(
                rows = rows,
                participantId = candidateId,
                participantNames = participantNames,
                baseCurrency = baseCurrency,
                participantAvatars = participantAvatars,
            )
        }
}.orEmpty()

internal fun selectOnBehalfSettlementOptionCandidates(
    currentParticipantId: String?,
    direction: SettlementDirection,
    options: List<SettlementOptionRowDto>,
    participantNames: Map<String, String>,
    baseCurrency: String,
    canActOnBehalf: Boolean,
    claimedParticipantIds: Set<String>,
    participantAvatars: Map<String, SettlementAvatarInfo> = emptyMap(),
): List<SettlementCandidate> {
    if (!canActOnBehalf) return emptyList()
    return options
        .groupBy { it.debtorParticipantId to it.creditorParticipantId }
        .mapNotNull { (endpoints, rows) ->
            val (fromId, toId) = endpoints
            if (currentParticipantId == fromId || currentParticipantId == toId) return@mapNotNull null
            val actingParticipantId = when (direction) {
                SettlementDirection.TRANSFER -> fromId
                SettlementDirection.RECEIVE -> toId
            }
            if (actingParticipantId in claimedParticipantIds) return@mapNotNull null
            val participantId = when (direction) {
                SettlementDirection.TRANSFER -> toId
                SettlementDirection.RECEIVE -> fromId
            }
            val candidate = settlementCandidateFromOptions(
                rows = rows,
                participantId = participantId,
                participantNames = participantNames,
                baseCurrency = baseCurrency,
                participantAvatars = participantAvatars,
            ) ?: return@mapNotNull null
            candidate.copy(
                kind = SettlementCandidateKind.ON_BEHALF,
                onBehalfOptions = listOf(
                    SettlementParticipant(
                        actingParticipantId,
                        participantNames[actingParticipantId] ?: return@mapNotNull null,
                    ),
                ),
            )
        }
}

private fun settlementCandidateFromOptions(
    rows: List<SettlementOptionRowDto>,
    participantId: String,
    participantNames: Map<String, String>,
    baseCurrency: String,
    participantAvatars: Map<String, SettlementAvatarInfo>,
): SettlementCandidate? {
    val first = rows.firstOrNull() ?: return null
    val fromName = participantNames[first.debtorParticipantId] ?: return null
    val toName = participantNames[first.creditorParticipantId] ?: return null
    val rowOptions = rows.mapNotNull { row ->
        val original = row.originalAmount.toBigDecimalOrNull() ?: return@mapNotNull null
        val base = row.baseAmount.toBigDecimalOrNull() ?: original
        val currency = row.currency.trim().uppercase()
        SettlementCurrencyOption(
            currencyCode = currency,
            amount = original,
            baseAmount = base,
            financialVersion = row.financialVersion,
            baseTotal = row.baseTotal.toBigDecimalOrNull(),
        )
    }.distinctBy { it.normalizedCurrencyCode }
    // base_total is the server-authoritative cap for settling the whole directed pair
    // in the activity base currency. Fall back only for older RPC responses.
    val baseAmount = rows.asSequence()
        .mapNotNull { it.baseTotal.toBigDecimalOrNull() }
        .firstOrNull()
        ?: rowOptions.sumOf { it.baseAmount ?: it.amount }
    val options = buildList {
        if (baseAmount > BigDecimal.ZERO) {
            add(
                SettlementCurrencyOption(
                    currencyCode = baseCurrency,
                    amount = baseAmount,
                    baseAmount = baseAmount,
                    financialVersion = rowOptions.mapNotNull { it.financialVersion }.maxOrNull(),
                ),
            )
        }
        rowOptions.filterNot { it.normalizedCurrencyCode == baseCurrency }
            .filter { it.amount > BigDecimal.ZERO }
            .forEach(::add)
    }
    if (options.isEmpty()) return null
    val baseOption = options.firstOrNull { it.normalizedCurrencyCode == baseCurrency }
    return SettlementCandidate(
        participantId = participantId,
        participantName = participantNames[participantId] ?: return null,
        amount = baseOption?.amount ?: options.sumOf { it.amount },
        fromParticipantId = first.debtorParticipantId,
        fromParticipantName = fromName,
        toParticipantId = first.creditorParticipantId,
        toParticipantName = toName,
        claimedUserId = participantAvatars[participantId]?.claimedUserId,
        avatarStyle = participantAvatars[participantId]?.avatarStyle,
        currencyOptions = options,
    )
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
