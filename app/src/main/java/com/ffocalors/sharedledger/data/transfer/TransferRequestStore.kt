package com.ffocalors.sharedledger.data.transfer

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.math.BigDecimal

/**
 * The complete client-side payload for a settlement write.  It is kept as a
 * separate record from [CreateSettlementTransferInput] because the timestamp
 * must survive a process restart even though the current transfer form does
 * not expose it as an editable field.
 */
data class PendingTransferRequest(
    val requestId: String,
    val activityId: String,
    val direction: SettlementDirection,
    val fromParticipantId: String,
    val toParticipantId: String,
    val amount: String,
    val currency: String,
    val type: String,
    val occurredAt: String,
    val onBehalfOfParticipantId: String?,
    val allocationMode: SettlementAllocationMode = SettlementAllocationMode.FIFO,
    val targetExpenseIds: List<String> = emptyList(),
    val expectedFinancialVersion: Long? = null,
    val createdAtEpochMillis: Long = 0L,
) {
    fun matches(
        activityId: String,
        direction: SettlementDirection,
        fromParticipantId: String,
        toParticipantId: String,
        amount: BigDecimal,
        currency: String,
        type: String,
        onBehalfOfParticipantId: String?,
        occurredAt: String?,
        allocationMode: SettlementAllocationMode = SettlementAllocationMode.FIFO,
        targetExpenseIds: List<String> = emptyList(),
    ): Boolean = this.activityId == activityId &&
        this.direction == direction &&
        this.fromParticipantId == fromParticipantId &&
        this.toParticipantId == toParticipantId &&
        this.amount.toBigDecimalOrNull()?.compareTo(amount) == 0 &&
        this.currency == currency.trim().uppercase() &&
        this.type == type &&
        this.onBehalfOfParticipantId == onBehalfOfParticipantId &&
        this.allocationMode == allocationMode &&
        this.targetExpenseIds.distinct().sorted() == targetExpenseIds.distinct().sorted() &&
        (occurredAt == null || this.occurredAt == occurredAt)
}

interface TransferRequestStore {
    suspend fun read(userId: String, activityId: String, direction: SettlementDirection): List<PendingTransferRequest>
    suspend fun upsert(userId: String, request: PendingTransferRequest)
    suspend fun remove(userId: String, request: PendingTransferRequest)
}

private val Context.transferRequestDataStore by preferencesDataStore(name = "transfer_request_cache")

@Serializable
private data class PendingTransferRequestDto(
    val requestId: String,
    val activityId: String,
    val direction: String,
    val fromParticipantId: String,
    val toParticipantId: String,
    val amount: String,
    val currency: String,
    val type: String,
    val occurredAt: String,
    val onBehalfOfParticipantId: String? = null,
    val allocationMode: String = SettlementAllocationMode.FIFO.name,
    val targetExpenseIds: List<String> = emptyList(),
    val expectedFinancialVersion: Long? = null,
    val createdAtEpochMillis: Long = 0L,
)

private val transferRequestJson = Json { ignoreUnknownKeys = true }

class PreferencesTransferRequestStore(context: Context) : TransferRequestStore {
    private val applicationContext = context.applicationContext

    override suspend fun read(
        userId: String,
        activityId: String,
        direction: SettlementDirection,
    ): List<PendingTransferRequest> = applicationContext.transferRequestDataStore.data
        .first()[preferenceKey(userId, activityId, direction)]
        .decodeRequests()
        .mapNotNull { it.toDomainOrNull() }

    override suspend fun upsert(userId: String, request: PendingTransferRequest) {
        applicationContext.transferRequestDataStore.edit { preferences ->
            val key = preferenceKey(userId, request.activityId, request.direction)
            val existing = preferences[key].decodeRequests()
                .filterNot { it.requestId == request.requestId }
            preferences[key] = transferRequestJson.encodeToString(
                (existing + request.toDto()).map { it },
            )
        }
    }

    override suspend fun remove(userId: String, request: PendingTransferRequest) {
        applicationContext.transferRequestDataStore.edit { preferences ->
            val key = preferenceKey(userId, request.activityId, request.direction)
            val remaining = preferences[key].decodeRequests()
                .filterNot { it.requestId == request.requestId }
            if (remaining.isEmpty()) preferences.remove(key)
            else preferences[key] = transferRequestJson.encodeToString(remaining)
        }
    }

    private fun preferenceKey(userId: String, activityId: String, direction: SettlementDirection) =
        stringPreferencesKey("v1.${userId.trim()}.${activityId.trim()}.${direction.name}")
}

/** Small deterministic store for JVM ViewModel tests and non-configured hosts. */
class InMemoryTransferRequestStore : TransferRequestStore {
    private val records = mutableMapOf<String, MutableList<PendingTransferRequest>>()

    override suspend fun read(userId: String, activityId: String, direction: SettlementDirection): List<PendingTransferRequest> =
        records[routeKey(userId, activityId, direction)].orEmpty().toList()

    override suspend fun upsert(userId: String, request: PendingTransferRequest) {
        val key = routeKey(userId, request.activityId, request.direction)
        val values = records.getOrPut(key) { mutableListOf() }
        values.removeAll { it.requestId == request.requestId }
        values += request
    }

    override suspend fun remove(userId: String, request: PendingTransferRequest) {
        val key = routeKey(userId, request.activityId, request.direction)
        records[key]?.removeAll { it.requestId == request.requestId }
        if (records[key].isNullOrEmpty()) records.remove(key)
    }

    private fun routeKey(userId: String, activityId: String, direction: SettlementDirection) =
        "${userId.trim()}:${activityId.trim()}:${direction.name}"
}

private fun PendingTransferRequest.toDto() = PendingTransferRequestDto(
    requestId = requestId,
    activityId = activityId,
    direction = direction.name,
    fromParticipantId = fromParticipantId,
    toParticipantId = toParticipantId,
    amount = amount,
    currency = currency,
    type = type,
    occurredAt = occurredAt,
    onBehalfOfParticipantId = onBehalfOfParticipantId,
    allocationMode = allocationMode.name,
    targetExpenseIds = targetExpenseIds,
    expectedFinancialVersion = expectedFinancialVersion,
    createdAtEpochMillis = createdAtEpochMillis,
)

private fun PendingTransferRequestDto.toDomainOrNull(): PendingTransferRequest? = runCatching {
    PendingTransferRequest(
        requestId = requestId,
        activityId = activityId,
        direction = SettlementDirection.valueOf(direction),
        fromParticipantId = fromParticipantId,
        toParticipantId = toParticipantId,
        amount = amount,
        currency = currency,
        type = type,
        occurredAt = occurredAt,
        onBehalfOfParticipantId = onBehalfOfParticipantId,
        allocationMode = runCatching { SettlementAllocationMode.valueOf(allocationMode.uppercase()) }
            .getOrDefault(SettlementAllocationMode.FIFO),
        targetExpenseIds = targetExpenseIds,
        expectedFinancialVersion = expectedFinancialVersion,
        createdAtEpochMillis = createdAtEpochMillis,
    )
}.getOrNull()

private fun String?.decodeRequests(): List<PendingTransferRequestDto> = this?.let { encoded ->
    runCatching { transferRequestJson.decodeFromString<List<PendingTransferRequestDto>>(encoded) }
        .getOrDefault(emptyList())
}.orEmpty()

private fun String.toBigDecimalOrNull(): BigDecimal? = runCatching { BigDecimal(this) }.getOrNull()
