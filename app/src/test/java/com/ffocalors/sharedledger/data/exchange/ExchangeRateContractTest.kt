package com.ffocalors.sharedledger.data.exchange

import com.ffocalors.sharedledger.data.expense.CreateExpenseInput
import com.ffocalors.sharedledger.data.expense.ExpenseRpcPayloadBuilder
import com.ffocalors.sharedledger.data.expense.ExpenseSplitMethod
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

class ExchangeRateContractTest {
    @Test
    fun autoRatePayloadNeverSendsTrustedFxRate() {
        val payload = ExpenseRpcPayloadBuilder.createAutoRate(
            CreateExpenseInput(
                ledgerUnitId = "unit-1",
                title = "票",
                originalAmount = BigDecimal("10"),
                originalCurrency = "USD",
                fxRate = BigDecimal("999"),
                splitMethod = ExpenseSplitMethod.Aa,
                payments = emptyList(),
                aaParticipantIds = listOf("participant-1"),
                occurredAt = "2026-09-13T00:00:00Z",
            ),
        )

        assertFalse(payload.containsKey("fx_rate"))
        assertEquals("USD", payload["original_currency"]?.toString()?.trim('"'))
    }

    @Test
    fun supportedRateMetadataIsDecodedWithoutLegacyFields() {
        val currency = kotlinx.serialization.json.Json.decodeFromString<kotlinx.serialization.json.JsonObject>(
            """{"currency_code":"USD","display_name":"US Dollar","observed_at":"2026-09-12T00:00:00Z"}""",
        )
        assertTrue(currency.containsKey("observed_at"))
    }

    @Test
    fun exchangeRateNumericJsonIsParsedSafely() {
        val dto = Json.decodeFromString<ExchangeRateDto>(
            """{"base_currency":"CNY","quote_currency":"USD","rate":0.13725,"source":"ECB_REFERENCE"}""",
        )
        assertEquals(BigDecimal("0.13725"), dto.rate.toExchangeBigDecimalOrNull())
    }

    @Test
    fun exchangeRateQuotedNumericJsonRemainsBackwardCompatible() {
        val dto = Json.decodeFromString<ExchangeRateDto>(
            """{"base_currency":"CNY","quote_currency":"USD","rate":"0.13725","source":"ECB_REFERENCE"}""",
        )
        assertEquals(BigDecimal("0.13725"), dto.rate.toExchangeBigDecimalOrNull())
    }

    @Test
    fun cachedRateUsesStableNormalizedBaseQuoteKey() {
        assertEquals("CNY_USD", exchangeRatePreferencePrefix(" cny ", "usd"))
    }
}
