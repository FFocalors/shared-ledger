package com.ffocalors.sharedledger

import com.ffocalors.sharedledger.ui.util.MoneyFormatter
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Test

class MoneyFormatterTest {
    @Test
    fun formatsCnyWithOneDecimalAndGrouping() {
        assertEquals("¥2,480.0", MoneyFormatter.format(BigDecimal("2480"), "CNY"))
    }

    @Test
    fun formatsEuroWithCurrencyPrecision() {
        assertEquals("€120.00", MoneyFormatter.format(BigDecimal("120"), "EUR"))
    }
}
