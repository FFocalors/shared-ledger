package com.ffocalors.sharedledger.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.demo.DemoRouteIds
import com.ffocalors.sharedledger.ui.screens.CreateActivityScreen
import com.ffocalors.sharedledger.ui.screens.CreateSubActivityScreen
import com.ffocalors.sharedledger.ui.screens.FinalSettlementScreen
import com.ffocalors.sharedledger.ui.screens.HomeScreen
import com.ffocalors.sharedledger.ui.screens.LargeActivityScreen
import com.ffocalors.sharedledger.ui.screens.LedgerUnitScreen
import com.ffocalors.sharedledger.ui.screens.NewExpenseScreen
import com.ffocalors.sharedledger.ui.screens.NormalActivityScreen
import com.ffocalors.sharedledger.ui.screens.TransferMode
import com.ffocalors.sharedledger.ui.screens.TransferScreen

@Composable
fun SharedLedgerApp(modifier: Modifier = Modifier) {
    val navController = rememberNavController()

    NavHost(
        navController = navController,
        startDestination = SharedLedgerRoutes.HOME,
        modifier = modifier,
    ) {
        composable(SharedLedgerRoutes.HOME) {
            HomeScreen(
                onJapanTravelClick = {
                    navController.navigate(SharedLedgerRoutes.largeActivity(DemoRouteIds.LARGE_ACTIVITY))
                },
                onWeekendDinnerClick = {
                    navController.navigate(SharedLedgerRoutes.normalActivity(DemoRouteIds.NORMAL_ACTIVITY))
                },
                onCreateActivity = { navController.navigate(SharedLedgerRoutes.CREATE_ACTIVITY) },
                onJoinActivity = {},
            )
        }
        composable(SharedLedgerRoutes.CREATE_ACTIVITY) {
            CreateActivityScreen(
                onBackClick = { navController.navigateUp() },
                onCreate = { kind ->
                    val destination = when (kind) {
                        ActivityKind.Standard -> SharedLedgerRoutes.normalActivity(DemoRouteIds.CREATED_NORMAL_ACTIVITY)
                        ActivityKind.Large -> SharedLedgerRoutes.largeActivity(DemoRouteIds.CREATED_LARGE_ACTIVITY)
                    }
                    navController.navigate(destination) {
                        popUpTo(SharedLedgerRoutes.CREATE_ACTIVITY) { inclusive = true }
                    }
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.NORMAL_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.NORMAL_ACTIVITY
            NormalActivityScreen(
                onBack = { navController.navigateUp() },
                onTransfer = {
                    navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                },
                onNewExpense = {
                    navController.navigate(SharedLedgerRoutes.newExpense(activityId))
                },
                onReceive = {
                    navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.LARGE_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.LARGE_ACTIVITY
            LargeActivityScreen(
                onBack = { navController.navigateUp() },
                onSubActivityClick = { id -> navController.navigate(SharedLedgerRoutes.ledgerUnit(id)) },
                onAddSubActivity = {
                    navController.navigate(SharedLedgerRoutes.createSubActivity(activityId))
                },
                onFinalSettlement = {
                    navController.navigate(SharedLedgerRoutes.finalSettlement(activityId))
                },
                onTransfer = {
                    navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                },
                onReceive = {
                    navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.CREATE_SUB_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) {
            CreateSubActivityScreen(
                parentActivityName = "日本旅行",
                onBack = { navController.navigateUp() },
                onCreate = { navController.navigateUp() },
            )
        }
        composable(
            route = SharedLedgerRoutes.LEDGER_UNIT_PATTERN,
            arguments = listOf(navArgument("ledgerUnitId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
                ?: DemoRouteIds.TICKET_LEDGER
            LedgerUnitScreen(
                onBack = { navController.navigateUp() },
                onTransfer = {
                    navController.navigate(SharedLedgerRoutes.transfer(ledgerUnitId, TransferRouteMode.TRANSFER))
                },
                onNewExpense = {
                    navController.navigate(SharedLedgerRoutes.newExpense(ledgerUnitId))
                },
                onReceive = {
                    navController.navigate(SharedLedgerRoutes.transfer(ledgerUnitId, TransferRouteMode.RECEIVE))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.NEW_EXPENSE_PATTERN,
            arguments = listOf(navArgument("ledgerUnitId") { type = NavType.StringType }),
        ) {
            NewExpenseScreen(
                onBack = { navController.navigateUp() },
                onSave = { navController.navigateUp() },
            )
        }
        composable(
            route = SharedLedgerRoutes.TRANSFER_PATTERN,
            arguments = listOf(
                navArgument("activityId") { type = NavType.StringType },
                navArgument("mode") {
                    type = NavType.StringType
                    defaultValue = TransferRouteMode.TRANSFER.value
                },
            ),
        ) { backStackEntry ->
            val mode = when (SharedLedgerRoutes.parseTransferMode(backStackEntry.arguments?.getString("mode"))) {
                TransferRouteMode.RECEIVE -> TransferMode.RECEIVE
                TransferRouteMode.TRANSFER -> TransferMode.TRANSFER
            }
            TransferScreen(
                mode = mode,
                onBack = { navController.navigateUp() },
                onConfirm = { navController.navigateUp() },
            )
        }
        composable(
            route = SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) {
            FinalSettlementScreen(onBack = { navController.navigateUp() })
        }
    }
}
