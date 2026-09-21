package com.ffocalors.sharedledger.data.financial

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.security.MessageDigest
import kotlinx.coroutines.flow.first
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Durable idempotency records for financial writes. This is intentionally separate from the
 * ordinary-transfer store so a pending prepayment/final-settlement payload can never be restored
 * into the normal transfer form.
 */
data class PendingFinancialRequest(
    val requestId: String,
    val activityId: String,
    val operationKey: String,
    val payloadFingerprint: String,
    val payload: String,
    val createdAtEpochMillis: Long = 0L,
)

interface FinancialRequestStore {
    suspend fun read(userId: String, activityId: String, operationKey: String): List<PendingFinancialRequest>
    suspend fun upsert(userId: String, request: PendingFinancialRequest)
    suspend fun remove(userId: String, request: PendingFinancialRequest)
}

private val Context.financialRequestDataStore by preferencesDataStore(name = "financial_request_cache")

@Serializable
private data class PendingFinancialRequestDto(
    val requestId: String,
    val activityId: String,
    val operationKey: String,
    val payloadFingerprint: String,
    val payload: String,
    val createdAtEpochMillis: Long = 0L,
)

private val financialRequestJson = Json { ignoreUnknownKeys = true }

class PreferencesFinancialRequestStore(context: Context) : FinancialRequestStore {
    private val applicationContext = context.applicationContext

    override suspend fun read(userId: String, activityId: String, operationKey: String): List<PendingFinancialRequest> =
        applicationContext.financialRequestDataStore.data
            .first()[preferenceKey(userId, activityId, operationKey)]
            .decodeFinancialRequests()
            .mapNotNull { it.toDomainOrNull() }

    override suspend fun upsert(userId: String, request: PendingFinancialRequest) {
        applicationContext.financialRequestDataStore.edit { preferences ->
            val key = preferenceKey(userId, request.activityId, request.operationKey)
            val existing = preferences[key].decodeFinancialRequests()
                .filterNot { it.requestId == request.requestId }
            preferences[key] = financialRequestJson.encodeToString(existing + request.toDto())
        }
    }

    override suspend fun remove(userId: String, request: PendingFinancialRequest) {
        applicationContext.financialRequestDataStore.edit { preferences ->
            val key = preferenceKey(userId, request.activityId, request.operationKey)
            val remaining = preferences[key].decodeFinancialRequests()
                .filterNot { it.requestId == request.requestId }
            if (remaining.isEmpty()) preferences.remove(key)
            else preferences[key] = financialRequestJson.encodeToString(remaining)
        }
    }

    private fun preferenceKey(userId: String, activityId: String, operationKey: String) =
        stringPreferencesKey("v1.${userId.trim()}.${activityId.trim()}.${operationKey.trim()}")
}

class InMemoryFinancialRequestStore : FinancialRequestStore {
    private val records = mutableMapOf<String, MutableList<PendingFinancialRequest>>()

    override suspend fun read(userId: String, activityId: String, operationKey: String): List<PendingFinancialRequest> =
        records[routeKey(userId, activityId, operationKey)].orEmpty().toList()

    override suspend fun upsert(userId: String, request: PendingFinancialRequest) {
        val values = records.getOrPut(routeKey(userId, request.activityId, request.operationKey)) { mutableListOf() }
        values.removeAll { it.requestId == request.requestId }
        values += request
    }

    override suspend fun remove(userId: String, request: PendingFinancialRequest) {
        val key = routeKey(userId, request.activityId, request.operationKey)
        records[key]?.removeAll { it.requestId == request.requestId }
        if (records[key].isNullOrEmpty()) records.remove(key)
    }

    private fun routeKey(userId: String, activityId: String, operationKey: String) =
        "${userId.trim()}:${activityId.trim()}:${operationKey.trim()}"
}

internal fun financialPayloadFingerprint(payload: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(payload.toByteArray(Charsets.UTF_8))
        .joinToString("") { byte -> "%02x".format(byte) }

private fun PendingFinancialRequest.toDto() = PendingFinancialRequestDto(
    requestId = requestId,
    activityId = activityId,
    operationKey = operationKey,
    payloadFingerprint = payloadFingerprint,
    payload = payload,
    createdAtEpochMillis = createdAtEpochMillis,
)

private fun PendingFinancialRequestDto.toDomainOrNull(): PendingFinancialRequest? = runCatching {
    PendingFinancialRequest(
        requestId = requestId,
        activityId = activityId,
        operationKey = operationKey,
        payloadFingerprint = payloadFingerprint,
        payload = payload,
        createdAtEpochMillis = createdAtEpochMillis,
    )
}.getOrNull()

private fun String?.decodeFinancialRequests(): List<PendingFinancialRequestDto> = this?.let { encoded ->
    runCatching { financialRequestJson.decodeFromString<List<PendingFinancialRequestDto>>(encoded) }
        .getOrDefault(emptyList())
}.orEmpty()
