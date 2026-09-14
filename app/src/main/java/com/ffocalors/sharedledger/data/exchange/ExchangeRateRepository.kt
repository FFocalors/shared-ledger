package com.ffocalors.sharedledger.data.exchange

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.ffocalors.sharedledger.BuildConfig
import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpHeaders
import io.ktor.http.isSuccess
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.math.BigDecimal

private val Context.exchangeRateDataStore by preferencesDataStore(name = "exchange_rate_cache")

data class SupportedExchangeCurrency(
    val code: String,
    val displayName: String,
    val observedAt: String?,
)

data class ExchangeRate(
    val baseCurrency: String,
    val quoteCurrency: String,
    val rate: BigDecimal,
    val observedAt: String?,
    val source: String,
)

data class ExchangeRateSyncStatus(
    val lastAttemptedAt: String?,
    val lastSucceededAt: String?,
    val lastEcbObservedAt: String?,
    val nextAttemptAt: String?,
    val lastErrorCode: String?,
)

@Serializable
private data class SupportedCurrencyDto(
    @SerialName("currency_code") val currencyCode: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("observed_at") val observedAt: String? = null,
)

@Serializable
internal data class ExchangeRateDto(
    @SerialName("base_currency") val baseCurrency: String,
    @SerialName("quote_currency") val quoteCurrency: String,
    val rate: JsonElement,
    @SerialName("observed_at") val observedAt: String? = null,
    val source: String,
)

internal fun JsonElement.toExchangeBigDecimalOrNull(): BigDecimal? = when (this) {
    is JsonPrimitive -> content.toBigDecimalOrNull()
    else -> null
}

@Serializable
private data class SupportedCurrencyCacheDto(
    @SerialName("currency_code") val currencyCode: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("observed_at") val observedAt: String? = null,
)

private val exchangeRateJson = Json { ignoreUnknownKeys = true }

internal fun exchangeRatePreferencePrefix(base: String, quote: String): String =
    "${base.trim().uppercase()}_${quote.trim().uppercase()}"

@Serializable
private data class ExchangeRateSyncStatusDto(
    @SerialName("last_attempted_at") val lastAttemptedAt: String? = null,
    @SerialName("last_succeeded_at") val lastSucceededAt: String? = null,
    @SerialName("last_ecb_observed_at") val lastEcbObservedAt: String? = null,
    @SerialName("next_attempt_at") val nextAttemptAt: String? = null,
    @SerialName("last_error_code") val lastErrorCode: String? = null,
)

interface ExchangeRateCache {
    suspend fun read(baseCurrency: String, quoteCurrency: String): ExchangeRate?
    suspend fun readAll(baseCurrency: String): List<ExchangeRate>
    suspend fun write(rate: ExchangeRate)
    suspend fun readSupportedCurrencies(): List<SupportedExchangeCurrency>?
    suspend fun writeSupportedCurrencies(currencies: List<SupportedExchangeCurrency>)
}

class PreferencesExchangeRateCache(private val context: Context) : ExchangeRateCache {
    override suspend fun read(baseCurrency: String, quoteCurrency: String): ExchangeRate? {
        val values = context.exchangeRateDataStore.data.map { prefs ->
            val prefix = exchangeRatePreferencePrefix(baseCurrency, quoteCurrency)
            val rate = prefs[stringPreferencesKey("$prefix.rate")] ?: return@map null
            ExchangeRate(
                baseCurrency = baseCurrency,
                quoteCurrency = quoteCurrency,
                rate = rate.toBigDecimalOrNull() ?: return@map null,
                source = prefs[stringPreferencesKey("$prefix.source")] ?: "legacy_manual",
                observedAt = prefs[stringPreferencesKey("$prefix.observed_at")],
            )
        }.first()
        return values
    }

    override suspend fun write(rate: ExchangeRate) {
        val prefix = exchangeRatePreferencePrefix(rate.baseCurrency, rate.quoteCurrency)
        context.exchangeRateDataStore.edit { prefs ->
            prefs[stringPreferencesKey("$prefix.rate")] = rate.rate.toPlainString()
            prefs[stringPreferencesKey("$prefix.source")] = rate.source
            rate.observedAt?.let { prefs[stringPreferencesKey("$prefix.observed_at")] = it }
        }
    }

    override suspend fun readAll(baseCurrency: String): List<ExchangeRate> =
        context.exchangeRateDataStore.data.map { prefs ->
            val base = baseCurrency.trim().uppercase()
            val ratePrefix = "${base}_"
            prefs.asMap().keys.mapNotNull { key ->
                val name = key.name
                if (!name.startsWith(ratePrefix) || !name.endsWith(".rate")) return@mapNotNull null
                val quote = name.removePrefix(ratePrefix).removeSuffix(".rate")
                val rate = prefs[stringPreferencesKey(name)]?.toBigDecimalOrNull() ?: return@mapNotNull null
                val prefix = "${base}_$quote"
                ExchangeRate(
                    baseCurrency = base,
                    quoteCurrency = quote,
                    rate = rate,
                    source = prefs[stringPreferencesKey("$prefix.source")] ?: "legacy_manual",
                    observedAt = prefs[stringPreferencesKey("$prefix.observed_at")],
                )
            }
        }.first()

    override suspend fun readSupportedCurrencies(): List<SupportedExchangeCurrency>? =
        context.exchangeRateDataStore.data.map { prefs ->
            prefs[SUPPORTED_CURRENCIES_KEY]?.let { encoded ->
                runCatching {
                    exchangeRateJson.decodeFromString<List<SupportedCurrencyCacheDto>>(encoded).map {
                        SupportedExchangeCurrency(it.currencyCode, it.displayName, it.observedAt)
                    }
                }.getOrNull()
            }
        }.first()

    override suspend fun writeSupportedCurrencies(currencies: List<SupportedExchangeCurrency>) {
        context.exchangeRateDataStore.edit { prefs ->
            prefs[SUPPORTED_CURRENCIES_KEY] = exchangeRateJson.encodeToString(
                currencies.map { SupportedCurrencyCacheDto(it.code, it.displayName, it.observedAt) },
            )
        }
    }

    private companion object {
        val SUPPORTED_CURRENCIES_KEY = stringPreferencesKey("supported_currencies")
    }
}

interface ExchangeRateRepository {
    suspend fun listSupportedCurrencies(): Result<List<SupportedExchangeCurrency>>
    suspend fun getRate(baseCurrency: String, quoteCurrency: String): Result<ExchangeRate>
    suspend fun readCachedRates(baseCurrency: String): Result<List<ExchangeRate>>
    suspend fun getSyncStatus(): Result<ExchangeRateSyncStatus>
    suspend fun syncExchangeRates(): Result<Unit>
}

class SupabaseExchangeRateRepository(
    private val client: SupabaseClient,
    private val cache: ExchangeRateCache,
    private val endpoint: String = BuildConfig.SUPABASE_URL.trim().trimEnd('/') + "/functions/v1/sync-exchange-rates",
    private val publishableKey: String = BuildConfig.SUPABASE_PUBLISHABLE_KEY.trim(),
) : ExchangeRateRepository {
    override suspend fun listSupportedCurrencies(): Result<List<SupportedExchangeCurrency>> = runCatching {
        client.postgrest.rpc("list_supported_exchange_currencies")
            .decodeList<SupportedCurrencyDto>()
            .map { SupportedExchangeCurrency(it.currencyCode.trim(), it.displayName, it.observedAt) }
            .also { cache.writeSupportedCurrencies(it) }
    }.recoverCatching { error -> cache.readSupportedCurrencies() ?: throw error }

    override suspend fun getRate(baseCurrency: String, quoteCurrency: String): Result<ExchangeRate> {
        val base = baseCurrency.trim().uppercase()
        val quote = quoteCurrency.trim().uppercase()
        if (base == quote) return Result.success(ExchangeRate(base, quote, BigDecimal.ONE, null, "same_currency"))
        return runCatching {
            client.postgrest.rpc("get_exchange_rate", buildJsonObject {
                put("p_base_currency", base)
                put("p_quote_currency", quote)
            }).decodeSingle<ExchangeRateDto>().let {
                ExchangeRate(
                    it.baseCurrency.trim(),
                    it.quoteCurrency.trim(),
                    it.rate.toExchangeBigDecimalOrNull() ?: error("invalid exchange rate"),
                    it.observedAt,
                    it.source,
                )
            }.also { rate -> cache.write(rate) }
        }.recoverCatching { error -> cache.read(base, quote) ?: throw error }
    }

    override suspend fun readCachedRates(baseCurrency: String): Result<List<ExchangeRate>> = runCatching {
        cache.readAll(baseCurrency.trim().uppercase())
    }

    override suspend fun getSyncStatus(): Result<ExchangeRateSyncStatus> = runCatching {
        client.postgrest.rpc("get_exchange_rate_sync_status")
            .decodeSingle<ExchangeRateSyncStatusDto>()
            .let { ExchangeRateSyncStatus(it.lastAttemptedAt, it.lastSucceededAt, it.lastEcbObservedAt, it.nextAttemptAt, it.lastErrorCode) }
    }

    override suspend fun syncExchangeRates(): Result<Unit> = runCatching {
        val accessToken = client.auth.currentSessionOrNull()?.accessToken.orEmpty()
        require(accessToken.isNotBlank()) { "登录会话已失效，请重新登录" }
        val http = HttpClient(OkHttp)
        try {
            val response = http.post(endpoint) {
                header(HttpHeaders.Authorization, "Bearer $accessToken")
                header("apikey", publishableKey)
            }
            if (!response.status.isSuccess()) error("汇率同步失败：${response.status.value} ${response.bodyAsText()}")
        } finally {
            http.close()
        }
    }
}

object ExchangeRateRepositoryFactory {
    fun create(context: Context): ExchangeRateRepository =
        SupabaseClientProvider.createOrNull()?.let { client ->
            SupabaseExchangeRateRepository(client, PreferencesExchangeRateCache(context.applicationContext))
        } ?: UnavailableExchangeRateRepository()
}

class UnavailableExchangeRateRepository : ExchangeRateRepository {
    private fun <T> unavailable(): Result<T> = Result.failure(IllegalStateException("尚未配置 Supabase，无法加载汇率"))
    override suspend fun listSupportedCurrencies() = unavailable<List<SupportedExchangeCurrency>>()
    override suspend fun getRate(baseCurrency: String, quoteCurrency: String) = unavailable<ExchangeRate>()
    override suspend fun readCachedRates(baseCurrency: String) = unavailable<List<ExchangeRate>>()
    override suspend fun getSyncStatus() = unavailable<ExchangeRateSyncStatus>()
    override suspend fun syncExchangeRates() = unavailable<Unit>()
}
