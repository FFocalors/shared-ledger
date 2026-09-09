package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.ui.demo.DemoRouteIds

internal fun ledgerUnitDemoTitle(ledgerUnitId: String): String = when (ledgerUnitId) {
    DemoRouteIds.BREAKFAST_LEDGER -> "早餐"
    DemoRouteIds.HOTEL_LEDGER -> "酒店"
    else -> "门票"
}
