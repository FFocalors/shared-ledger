package com.ffocalors.sharedledger.ui.util

import java.math.BigDecimal
import java.math.RoundingMode
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Currency
import java.util.Locale

object MoneyFormatter {
    fun format(
        amount: BigDecimal,
        currencyCode: String = "CNY",
    ): String {
        val normalizedCode = currencyCode.uppercase(Locale.ROOT)
        val fractionDigits = when (normalizedCode) {
            "CNY" -> 1
            else -> runCatching {
                Currency.getInstance(normalizedCode).defaultFractionDigits
            }.getOrDefault(2).coerceAtLeast(0)
        }
        val pattern = buildString {
            append("#,##0")
            if (fractionDigits > 0) {
                append(".")
                repeat(fractionDigits) { append("0") }
            }
        }
        val number = DecimalFormat(pattern, DecimalFormatSymbols(Locale.US)).apply {
            roundingMode = RoundingMode.HALF_UP
        }.format(amount)
        return currencySymbol(normalizedCode) + number
    }

    private fun currencySymbol(currencyCode: String): String = when (currencyCode) {
        "CNY", "JPY" -> "¥"
        "EUR" -> "€"
        "USD" -> "$"
        "GBP" -> "£"
        else -> "$currencyCode "
    }
}
