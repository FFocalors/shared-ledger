package com.ffocalors.sharedledger.data.expense

/**
 * Stable persistence keys for expense artwork.
 *
 * The database stores only these values; Compose/ImageVector names remain a UI detail.
 */
object ExpenseIconKey {
    const val MONEY = "money"
    const val DINING = "dining"
    const val SHOPPING = "shopping"
    const val TRANSPORT = "transport"
    const val HOTEL = "hotel"
    const val TICKET = "ticket"
    const val FUEL = "fuel"
    const val ENTERTAINMENT = "entertainment"
    const val MEDICAL = "medical"
    const val GIFT = "gift"
    const val GROCERY = "grocery"
    const val FLIGHT = "flight"

    val supported: Set<String> = setOf(
        MONEY,
        DINING,
        SHOPPING,
        TRANSPORT,
        HOTEL,
        TICKET,
        FUEL,
        ENTERTAINMENT,
        MEDICAL,
        GIFT,
        GROCERY,
        FLIGHT,
    )

    fun normalize(value: String?): String = value
        ?.trim()
        ?.lowercase()
        ?.takeIf(supported::contains)
        ?: MONEY
}
