package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.data.transfer.SettlementCurrencyOption
import java.math.BigDecimal
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TransferAmountTest {
    @Test
    fun emptyZeroAndMalformedAmountsAreNotSubmittable() {
        assertFalse(isValidTransferAmount(""))
        assertFalse(isValidTransferAmount("0"))
        assertFalse(isValidTransferAmount("-1"))
        assertFalse(isValidTransferAmount("."))
        assertTrue(isValidTransferAmount("0.01"))
    }

    @Test
    fun foreignCurrencyUsesCommonTwoDecimalInputPrecision() {
        assertEquals("12.34", sanitizeTransferAmount("12.3456", fractionDigits = 2))
        assertEquals("12.3", sanitizeTransferAmount("12.3456", fractionDigits = 1))
    }

    @Test
    fun disabledMultiCurrencyHidesPickerAndKeepsOnlyBaseCurrency() {
        val options = listOf(
            SettlementCurrencyOption("CNY", BigDecimal("30.0")),
            SettlementCurrencyOption("USD", BigDecimal("4.2")),
        )

        assertFalse(shouldShowTransferCurrencyPicker(multiCurrencyEnabled = false))
        assertEquals(listOf("CNY"), visibleTransferCurrencyOptions(false, options, "CNY").map { it.normalizedCurrencyCode })
        assertEquals("CNY", defaultTransferCurrencyOption(options, "CNY", false)?.normalizedCurrencyCode)
    }

    @Test
    fun enabledMultiCurrencyUsesOnlyServerDebtOptionsAndIncludesBaseOption() {
        val options = listOf(
            SettlementCurrencyOption("CNY", BigDecimal("30.0")),
            SettlementCurrencyOption("USD", BigDecimal("4.2")),
        )

        assertTrue(shouldShowTransferCurrencyPicker(multiCurrencyEnabled = true))
        assertEquals(
            listOf("CNY", "USD"),
            visibleTransferCurrencyOptions(true, options, "CNY").map { it.normalizedCurrencyCode },
        )
        assertEquals("CNY", defaultTransferCurrencyOption(options, "CNY", true)?.normalizedCurrencyCode)
    }
}
