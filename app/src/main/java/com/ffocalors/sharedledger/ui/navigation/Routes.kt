package com.ffocalors.sharedledger.ui.navigation

/** Central route contract for the static SharedLedger prototype. */
object SharedLedgerRoutes {
    const val AUTH = "auth"
    const val START_DESTINATION = AUTH
    const val HOME = "home"
    const val JOIN_ACTIVITY = "join-activity"
    const val CREATE_ACTIVITY = "create-activity"
    const val NORMAL_ACTIVITY_PATTERN = "normal-activity/{activityId}"
    const val LARGE_ACTIVITY_PATTERN = "large-activity/{activityId}"
    const val CREATE_SUB_ACTIVITY_PATTERN = "create-sub-activity/{activityId}"
    const val LEDGER_UNIT_PATTERN = "ledger-unit/{activityId}/{ledgerUnitId}"
    const val NEW_EXPENSE_PATTERN = "new-expense/{activityId}?ledgerUnitId={ledgerUnitId}"
    const val TRANSFER_PATTERN = "transfer/{activityId}?mode={mode}&ledgerUnitId={ledgerUnitId}"
    const val FUND_RECORDS_PATTERN = "fund-records/{activityId}?ledgerUnitId={ledgerUnitId}"
    const val FINAL_SETTLEMENT_PATTERN = "final-settlement/{activityId}"
    const val ACTIVITY_MANAGEMENT_PATTERN = "activity-management/{activityId}"
    const val EXPENSE_DETAIL_PATTERN = "expense-detail/{expenseId}"
    const val TRANSFER_DETAIL_PATTERN = "transfer-detail/{activityId}/{transferId}?ledgerUnitId={ledgerUnitId}"
    const val ACTIVITY_MANAGEMENT = ACTIVITY_MANAGEMENT_PATTERN
    const val EXPENSE_DETAIL = EXPENSE_DETAIL_PATTERN
    const val TRANSFER_DETAIL = TRANSFER_DETAIL_PATTERN
    const val FUND_RECORDS = FUND_RECORDS_PATTERN

    data class AuthSuccessNavigation(
        val destination: String,
        val popUpTo: String,
        val inclusive: Boolean,
        val launchSingleTop: Boolean,
    )

    /** Navigation contract for a successful sign-in: HOME replaces the auth return stack. */
    fun authSuccessNavigation(): AuthSuccessNavigation = AuthSuccessNavigation(
        destination = HOME,
        popUpTo = AUTH,
        inclusive = true,
        launchSingleTop = true,
    )

    fun normalActivity(activityId: String) = createRoute("normal-activity", activityId)
    fun largeActivity(activityId: String) = createRoute("large-activity", activityId)
    fun createSubActivity(activityId: String) = createRoute("create-sub-activity", activityId)
    fun ledgerUnit(activityId: String, ledgerUnitId: String) =
        "${createRoute("ledger-unit", activityId)}/${routeSegment(ledgerUnitId, "ledgerUnitId")}"
    fun newExpense(activityId: String, ledgerUnitId: String? = null): String {
        val route = createRoute("new-expense", activityId)
        return if (ledgerUnitId.isNullOrBlank()) route
        else "$route?ledgerUnitId=${routeSegment(ledgerUnitId.orEmpty(), "ledgerUnitId")}"
    }
    fun transfer(activityId: String, mode: TransferRouteMode, ledgerUnitId: String? = null): String {
        val route = "${createRoute("transfer", activityId)}?mode=${mode.value}"
        return if (ledgerUnitId.isNullOrBlank()) route
        else "$route&ledgerUnitId=${routeSegment(ledgerUnitId.orEmpty(), "ledgerUnitId")}"
    }
    fun fundRecords(activityId: String, ledgerUnitId: String? = null): String {
        val route = createRoute("fund-records", activityId)
        return if (ledgerUnitId.isNullOrBlank()) route
        else "$route?ledgerUnitId=${routeSegment(ledgerUnitId.orEmpty(), "ledgerUnitId")}"
    }
    fun finalSettlement(activityId: String) = createRoute("final-settlement", activityId)
    fun activityManagement(activityId: String) = createRoute("activity-management", activityId)
    fun expenseDetail(expenseId: String) = createRoute("expense-detail", expenseId)
    fun transferDetail(activityId: String, transferId: String, ledgerUnitId: String? = null): String {
        val route = "${createRoute("transfer-detail", activityId)}/${routeSegment(transferId, "transferId")}"
        return if (ledgerUnitId.isNullOrBlank()) route
        else "$route?ledgerUnitId=${routeSegment(ledgerUnitId.orEmpty(), "ledgerUnitId")}"
    }

    private fun routeSegment(value: String, name: String): String = value.trim().also {
        require(it.isNotBlank()) { "$name must not be blank" }
    }

    /** Builds a route from an opaque, non-display identifier. */
    fun createRoute(route: String, id: String): String {
        require(route.isNotBlank()) { "route must not be blank" }
        require(id.isNotBlank()) { "route id must not be blank" }
        return "$route/${id.trim()}"
    }

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
