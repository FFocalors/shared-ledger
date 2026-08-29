package com.ffocalors.sharedledger.ui.navigation

/** Central route contract for the static SharedLedger prototype. */
object SharedLedgerRoutes {
    const val HOME = "home"
    const val CREATE_ACTIVITY = "create-activity"
    const val NORMAL_ACTIVITY_PATTERN = "normal-activity/{activityId}"
    const val LARGE_ACTIVITY_PATTERN = "large-activity/{activityId}"
    const val LEDGER_UNIT_PATTERN = "ledger-unit/{ledgerUnitId}"
    const val NEW_EXPENSE_PATTERN = "new-expense/{ledgerUnitId}"
    const val TRANSFER_PATTERN = "transfer/{activityId}?mode={mode}"
    const val FINAL_SETTLEMENT_PATTERN = "final-settlement/{activityId}"

    fun normalActivity(activityId: String) = "normal-activity/$activityId"
    fun largeActivity(activityId: String) = "large-activity/$activityId"
    fun ledgerUnit(ledgerUnitId: String) = "ledger-unit/$ledgerUnitId"
    fun newExpense(ledgerUnitId: String) = "new-expense/$ledgerUnitId"
    fun transfer(activityId: String, mode: TransferRouteMode) = "transfer/$activityId?mode=${mode.value}"
    fun finalSettlement(activityId: String) = "final-settlement/$activityId"

    fun parseTransferMode(rawMode: String?): TransferRouteMode = when (rawMode?.lowercase()) {
        TransferRouteMode.RECEIVE.value -> TransferRouteMode.RECEIVE
        TransferRouteMode.TRANSFER.value -> TransferRouteMode.TRANSFER
        else -> TransferRouteMode.TRANSFER
    }
}

enum class TransferRouteMode(val value: String) {
    TRANSFER("transfer"),
    RECEIVE("receive"),
}
