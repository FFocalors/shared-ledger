package com.ffocalors.sharedledger.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ffocalors.sharedledger.data.auth.AuthRepositoryFactory
import com.ffocalors.sharedledger.data.auth.AuthState
import com.ffocalors.sharedledger.ui.activity.ActivityViewModel
import com.ffocalors.sharedledger.data.activity.ActivityType
import com.ffocalors.sharedledger.data.financial.FakeActorContext
import com.ffocalors.sharedledger.data.financial.FakeFinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepository
import com.ffocalors.sharedledger.domain.financial.FinalSettlementPath
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordComponent
import com.ffocalors.sharedledger.domain.financial.FundRecordComponentType
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import com.ffocalors.sharedledger.domain.financial.RecorderInfo
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.ui.demo.DemoRouteIds
import com.ffocalors.sharedledger.ui.screens.CreateActivityScreen
import com.ffocalors.sharedledger.ui.screens.CreateSubActivityScreen
import com.ffocalors.sharedledger.ui.screens.AuthScreen
import com.ffocalors.sharedledger.ui.screens.ActivityManagementScreen
import com.ffocalors.sharedledger.ui.screens.ExpenseDetailScreen
import com.ffocalors.sharedledger.ui.screens.ExpenseDetailStatus
import com.ffocalors.sharedledger.ui.screens.JoinActivityScreen
import com.ffocalors.sharedledger.ui.screens.JoinActivityStatus
import com.ffocalors.sharedledger.ui.screens.JoinActivityUiState
import com.ffocalors.sharedledger.ui.screens.TransferDetailScreen
import com.ffocalors.sharedledger.ui.screens.TransferDetailUiState
import com.ffocalors.sharedledger.ui.screens.FinalSettlementScreen
import com.ffocalors.sharedledger.ui.screens.FinalSettlementRequest
import com.ffocalors.sharedledger.ui.screens.isValid
import com.ffocalors.sharedledger.ui.screens.FundRecordsScreen
import com.ffocalors.sharedledger.ui.screens.HomeScreen
import com.ffocalors.sharedledger.ui.screens.LargeActivityScreen
import com.ffocalors.sharedledger.ui.screens.LedgerUnitScreen
import com.ffocalors.sharedledger.ui.screens.NewExpenseScreen
import com.ffocalors.sharedledger.ui.screens.NormalActivityScreen
import com.ffocalors.sharedledger.ui.screens.TransferMode
import com.ffocalors.sharedledger.ui.screens.TransferScreen
import com.ffocalors.sharedledger.ui.screens.demoExpenseDetailUiState
import com.ffocalors.sharedledger.ui.screens.demoCreateTransfer
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import java.math.BigDecimal

@Composable
fun SharedLedgerApp(modifier: Modifier = Modifier) {
    val authRepository = remember { AuthRepositoryFactory.create() }
    val authViewModel: com.ffocalors.sharedledger.ui.auth.AuthViewModel = viewModel(
        factory = com.ffocalors.sharedledger.ui.auth.AuthViewModel.Factory(authRepository),
    )
    val authUiState by authViewModel.uiState.collectAsState()

    when (val authState = authUiState.authState) {
        AuthState.Loading -> AuthLoadingScreen(modifier)
        is AuthState.Authenticated -> key(authState.user.id) {
            AuthenticatedNavHost(
                modifier = modifier,
                currentUserId = authState.user.id,
                onSignOut = authViewModel::signOut,
            )
        }
        AuthState.Unauthenticated, is AuthState.Error -> AuthScreen(
            modifier = modifier,
            errorMessage = authUiState.message,
            isLoading = authUiState.isSubmitting,
            onLogin = authViewModel::signIn,
            onRegister = authViewModel::signUp,
            onForgotPassword = { email ->
                authViewModel.showMessage(
                    if (email.isBlank()) "请输入邮箱后再申请重置密码" else "密码重置功能尚未接入，请联系管理员",
                )
            },
        )
    }
}

@Composable
private fun AuthLoadingScreen(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxSize(),
        horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally,
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
    ) {
        CircularProgressIndicator()
        Text(
            text = "正在恢复登录状态…",
            modifier = Modifier.padding(top = SharedLedgerSpacing.Medium),
            style = SharedLedgerTextStyles.BodySecondary,
        )
    }
}

@Composable
private fun AuthenticatedNavHost(
    modifier: Modifier = Modifier,
    currentUserId: String,
    onSignOut: () -> Unit,
) {
    val navController = rememberNavController()
    val activityViewModel: ActivityViewModel = viewModel(
        key = "activity-$currentUserId",
        factory = ActivityViewModel.Factory(currentUserId = currentUserId),
    )
    val homeState by activityViewModel.home.collectAsState()
    val viewModelJoinState by activityViewModel.join.collectAsState()
    var joinInviteCode by rememberSaveable { mutableStateOf("") }
    var selectedJoinParticipantId by rememberSaveable { mutableStateOf<String?>(null) }
    val demoActorContext = remember {
        FakeActorContext(
            actor = RecorderInfo("fake-app-user", "Fake Demo 管理员"),
            participantIds = setOf("fake-current-user", "fake-carol"),
        )
    }
    val financialRepository = remember(demoActorContext) {
        FakeFinancialRecordRepository(actorContext = demoActorContext)
    }
    val demoActor = demoActorContext.actor
    fun requireParticipantBinding(activityId: String, action: () -> Unit) {
        val detail = activityViewModel.detail(activityId).value.detail
        if (activityViewModel.isCurrentUserBound(detail)) {
            action()
        } else {
            navController.navigate(SharedLedgerRoutes.activityManagement(activityId)) {
                launchSingleTop = true
            }
        }
    }
    NavHost(
        navController = navController,
        startDestination = SharedLedgerRoutes.HOME,
        modifier = modifier,
    ) {
        composable(SharedLedgerRoutes.HOME) {
            androidx.compose.runtime.LaunchedEffect(currentUserId) {
                activityViewModel.resetJoin()
                activityViewModel.refreshHome()
            }
            HomeScreen(
                activities = homeState.activities,
                isLoading = homeState.isLoading,
                errorMessage = homeState.errorMessage,
                onRetry = { activityViewModel.refreshHome() },
                onActivityClick = { activity ->
                    val destination = when (activity.kind) {
                        ActivityKind.Large -> SharedLedgerRoutes.largeActivity(activity.activityId)
                        ActivityKind.Standard -> SharedLedgerRoutes.normalActivity(activity.activityId)
                    }
                    navController.navigate(destination)
                },
                onCreateActivity = { navController.navigate(SharedLedgerRoutes.CREATE_ACTIVITY) },
                onJoinActivity = { navController.navigate(SharedLedgerRoutes.JOIN_ACTIVITY) },
                onSignOut = onSignOut,
            )
        }
        composable(SharedLedgerRoutes.JOIN_ACTIVITY) {
            androidx.compose.runtime.LaunchedEffect(Unit) {
                activityViewModel.resetJoin()
                joinInviteCode = ""
                selectedJoinParticipantId = null
            }
            val joinState = viewModelJoinState.copy(
                inviteCode = viewModelJoinState.inviteCode.ifBlank { joinInviteCode },
                selectedParticipantId = selectedJoinParticipantId ?: viewModelJoinState.selectedParticipantId,
            )
            JoinActivityScreen(
                state = joinState,
                onBackClick = { navController.navigateUp() },
                onInviteCodeChange = { value ->
                    joinInviteCode = value.filter(Char::isDigit).take(8)
                },
                onValidateInviteCode = { code ->
                    activityViewModel.joinActivity(code)
                },
                onParticipantSelected = { participantId ->
                    selectedJoinParticipantId = participantId
                    val selected = joinState.preview.participants.firstOrNull { it.participantId == participantId }
                    activityViewModel.selectJoinParticipant(participantId, selected?.name)
                },
                onJoinActivity = { participantId ->
                    val activityId = activityViewModel.joinedActivityId()
                    if (participantId.isNotBlank() && activityId != null) activityViewModel.claimParticipant(activityId, participantId)
                },
                onCompleteJoinWithoutClaim = {
                    activityViewModel.completeJoinWithoutClaim()
                },
                onUnclaimActivity = {
                    val activityId = activityViewModel.joinedActivityId()
                    if (activityId != null) {
                        activityViewModel.unclaimParticipant(activityId)
                        activityViewModel.resetJoin()
                    }
                },
                onJoinSuccessNavigate = {
                    navController.navigate(SharedLedgerRoutes.HOME) {
                        popUpTo(SharedLedgerRoutes.HOME) { inclusive = false }
                        launchSingleTop = true
                    }
                },
            )
        }
        composable(SharedLedgerRoutes.CREATE_ACTIVITY) {
            val creating by activityViewModel.actionLoading.collectAsState()
            val message by activityViewModel.message.collectAsState()
            CreateActivityScreen(
                onBackClick = { navController.navigateUp() },
                isLoading = creating,
                errorMessage = message,
                onCreate = { name, kind, multiCurrency ->
                    activityViewModel.createActivity(name, kind, multiCurrency) { created ->
                        val destination = if (created.type == ActivityType.Large) SharedLedgerRoutes.largeActivity(created.id) else SharedLedgerRoutes.normalActivity(created.id)
                        navController.navigate(destination) { popUpTo(SharedLedgerRoutes.CREATE_ACTIVITY) { inclusive = true } }
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
            val detailState by activityViewModel.detail(activityId).collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                activityViewModel.loadDetail(activityId)
            }
            NormalActivityScreen(
                activity = detailState.detail,
                isLoading = detailState.isLoading,
                errorMessage = detailState.errorMessage,
                onRetry = { activityViewModel.loadDetail(activityId, force = true) },
                onBack = { navController.navigateUp() },
                onTransfer = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                    }
                },
                onNewExpense = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId))
                    }
                },
                onReceive = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE))
                    }
                },
                onFundRecords = {
                    navController.navigate(SharedLedgerRoutes.fundRecords(activityId)) { launchSingleTop = true }
                },
                onManageActivity = {
                    navController.navigate(SharedLedgerRoutes.activityManagement(activityId))
                },
                onExpenseClick = { expenseId ->
                    navController.navigate(SharedLedgerRoutes.expenseDetail(expenseId))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.LARGE_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.LARGE_ACTIVITY
            val detailState by activityViewModel.detail(activityId).collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                activityViewModel.loadDetail(activityId)
            }
            LargeActivityScreen(
                activity = detailState.detail,
                isLoading = detailState.isLoading,
                errorMessage = detailState.errorMessage,
                onRetry = { activityViewModel.loadDetail(activityId, force = true) },
                onBack = { navController.navigateUp() },
                onSubActivityClick = { id ->
                    navController.navigate(SharedLedgerRoutes.ledgerUnit(activityId, id))
                },
                onAddSubActivity = {
                    navController.navigate(SharedLedgerRoutes.createSubActivity(activityId))
                },
                onFinalSettlement = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.finalSettlement(activityId))
                    }
                },
                onTransfer = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                    }
                },
                onReceive = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE))
                    }
                },
                onFundRecords = {
                    navController.navigate(SharedLedgerRoutes.fundRecords(activityId)) { launchSingleTop = true }
                },
                onManageActivity = {
                    navController.navigate(SharedLedgerRoutes.activityManagement(activityId))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.CREATE_SUB_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.LARGE_ACTIVITY
            val detailState by activityViewModel.detail(activityId).collectAsState()
            val creating by activityViewModel.actionLoading.collectAsState()
            val message by activityViewModel.message.collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                activityViewModel.loadDetail(activityId)
            }
            CreateSubActivityScreen(
                activity = detailState.detail,
                isLoading = creating || detailState.isLoading,
                errorMessage = message ?: detailState.errorMessage,
                onBack = { navController.navigateUp() },
                onCreate = { name ->
                    activityViewModel.createSubActivity(activityId, name) {
                        navController.navigateUp()
                    }
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.LEDGER_UNIT_PATTERN,
            arguments = listOf(
                navArgument("activityId") { type = NavType.StringType },
                navArgument("ledgerUnitId") { type = NavType.StringType },
            ),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.LARGE_ACTIVITY
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
                ?: DemoRouteIds.TICKET_LEDGER
            val detailState by activityViewModel.detail(activityId).collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                activityViewModel.loadDetail(activityId)
            }
            LedgerUnitScreen(
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                activity = detailState.detail,
                isLoading = detailState.isLoading,
                errorMessage = detailState.errorMessage,
                onRetry = { activityViewModel.loadDetail(activityId, force = true) },
                onBack = { navController.navigateUp() },
                onTransfer = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(
                            SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER, ledgerUnitId),
                        )
                    }
                },
                onNewExpense = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId))
                    }
                },
                onReceive = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(
                            SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE, ledgerUnitId),
                        )
                    }
                },
                onFundRecords = {
                    navController.navigate(SharedLedgerRoutes.fundRecords(activityId, ledgerUnitId)) {
                        launchSingleTop = true
                    }
                },
                onExpenseClick = { expenseId ->
                    navController.navigate(SharedLedgerRoutes.expenseDetail(expenseId))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.NEW_EXPENSE_PATTERN,
            arguments = listOf(
                navArgument("activityId") { type = NavType.StringType },
                navArgument("ledgerUnitId") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
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
                navArgument("ledgerUnitId") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
                navArgument("mode") {
                    type = NavType.StringType
                    defaultValue = TransferRouteMode.TRANSFER.value
                },
            ),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.NORMAL_ACTIVITY
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            val mode = when (SharedLedgerRoutes.parseTransferMode(backStackEntry.arguments?.getString("mode"))) {
                TransferRouteMode.RECEIVE -> TransferMode.RECEIVE
                TransferRouteMode.TRANSFER -> TransferMode.TRANSFER
            }
            TransferScreen(
                mode = mode,
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                onBack = { navController.navigateUp() },
                onConfirm = { draft ->
                    val created = demoCreateTransfer(draft)
                    val written = financialRepository.create(
                        demoTransferRecord(draft, created.transferId, demoActor),
                    )
                    if (written.isSuccess) {
                        navController.navigate(
                            SharedLedgerRoutes.transferDetail(
                                activityId = created.activityId,
                                transferId = created.transferId,
                                ledgerUnitId = created.ledgerUnitId,
                            ),
                        ) {
                            popUpTo(SharedLedgerRoutes.TRANSFER_PATTERN) { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.FUND_RECORDS_PATTERN,
            arguments = listOf(
                navArgument("activityId") { type = NavType.StringType },
                navArgument("ledgerUnitId") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.NORMAL_ACTIVITY
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            FundRecordsScreen(
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                repository = financialRepository,
                onBack = { navController.navigateUp() },
                onRecordClick = { transferId ->
                    navController.navigate(SharedLedgerRoutes.transferDetail(activityId, transferId, ledgerUnitId)) {
                        launchSingleTop = true
                    }
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.ACTIVITY_MANAGEMENT_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.NORMAL_ACTIVITY
            val detailState by activityViewModel.detail(activityId).collectAsState()
            val managementState = activityViewModel.managementState(activityId)
            val actionLoading by activityViewModel.actionLoading.collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                activityViewModel.loadDetail(activityId)
            }
            ActivityManagementScreen(
                activityId = activityId,
                state = managementState
                    ?: com.ffocalors.sharedledger.ui.screens.ActivityManagementUiState(),
                isLoading = detailState.isLoading || managementState == null || actionLoading,
                errorMessage = detailState.errorMessage,
                onRetry = { activityViewModel.loadDetail(activityId, force = true) },
                onBackClick = { navController.navigateUp() },
                onMultiCurrencyChange = { targetActivityId, enabled ->
                    if (targetActivityId == activityId) {
                        activityViewModel.updateSettings(
                            activityId = activityId,
                            name = managementState?.activityName.orEmpty(),
                            multiCurrency = enabled,
                        )
                    }
                },
                onCreateParticipant = { targetActivityId, name ->
                    if (targetActivityId == activityId) {
                        activityViewModel.createParticipant(activityId, name)
                    }
                },
                onBindParticipant = { targetActivityId, participantId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.bindCurrentUser(activityId, participantId)
                    }
                },
                onUnbindParticipant = { targetActivityId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.unbindCurrentUser(activityId)
                    }
                },
                onTransferOwnership = { targetActivityId, memberId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.transferCreator(activityId, memberId)
                    }
                },
                onRemoveMember = { targetActivityId, memberId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.removeMember(activityId, memberId)
                    }
                },
                onArchiveActivity = { targetActivityId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.archiveActivity(activityId) { navController.navigateUp() }
                    }
                },
                onLeaveActivity = { targetActivityId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.removeMember(activityId, currentUserId)
                        navController.navigateUp()
                    }
                },
                onDeleteActivity = { targetActivityId ->
                    if (targetActivityId == activityId) {
                        activityViewModel.deleteActivity(activityId) { navController.navigateUp() }
                    }
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.EXPENSE_DETAIL_PATTERN,
            arguments = listOf(navArgument("expenseId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val expenseId = backStackEntry.arguments?.getString("expenseId")
                ?: DemoRouteIds.DINNER_EXPENSE
            var expenseStatus by rememberSaveable(expenseId) {
                mutableStateOf(demoExpenseDetailUiState(expenseId).status)
            }
            var expenseActionMessage by rememberSaveable(expenseId) { mutableStateOf<String?>(null) }
            val expenseActionHandler = remember(expenseId) {
                DemoExpenseActionHandler(
                    onStatusChanged = { expenseStatus = it },
                    onMessage = { expenseActionMessage = it },
                )
            }
            ExpenseDetailScreen(
                uiState = demoExpenseDetailUiState(expenseId).copy(
                    status = expenseStatus,
                    actionMessage = expenseActionMessage,
                ),
                onBack = { navController.navigateUp() },
                onEdit = { id -> expenseActionHandler.edit(id) },
                onVoid = { id -> expenseActionHandler.void(id) },
                onRestore = { id -> expenseActionHandler.restore(id) },
                onAddRefund = { id -> expenseActionHandler.addRefund(id) },
                onDeletePermanently = { id -> expenseActionHandler.deletePermanently(id) },
                onAttachmentClick = { id, attachmentId -> expenseActionHandler.viewAttachment(id, attachmentId) },
            )
        }
        composable(
            route = SharedLedgerRoutes.TRANSFER_DETAIL_PATTERN,
            arguments = listOf(
                navArgument("activityId") { type = NavType.StringType },
                navArgument("transferId") { type = NavType.StringType },
                navArgument("ledgerUnitId") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.NORMAL_ACTIVITY
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            val transferId = backStackEntry.arguments?.getString("transferId")
                ?: DemoRouteIds.TRANSFER
            FinancialRecordDetailRoute(
                activityId = activityId,
                transferId = transferId,
                ledgerUnitId = ledgerUnitId,
                repository = financialRepository,
                actorContext = demoActorContext,
                onBack = { navController.navigateUp() },
                onRecreateCorrectRecord = {
                    navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER, ledgerUnitId))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.LARGE_ACTIVITY
            FinalSettlementScreen(
                activityId = activityId,
                onBack = { navController.navigateUp() },
                onFinalize = { request ->
                    val transferId = DemoRouteIds.finalSettlementTransfer(activityId) +
                        "-${request.previewItemId}-${request.fromParticipantId}-${request.toParticipantId}"
                    val written = if (request.isValid()) {
                        financialRepository.create(demoFinalSettlementRecord(request, transferId, demoActor))
                    } else {
                        com.ffocalors.sharedledger.data.financial.FinancialWriteResult.failure("最终结算建议已过期，请重新预览")
                    }
                    if (written.isSuccess) {
                        navController.navigate(SharedLedgerRoutes.transferDetail(activityId, transferId)) {
                            popUpTo(SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN) { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                },
            )
        }
    }
}

private sealed interface FinancialDetailRouteState {
    data object Loading : FinancialDetailRouteState
    data class Content(val record: FundRecord) : FinancialDetailRouteState
    data class Error(val message: String) : FinancialDetailRouteState
}

@Composable
private fun FinancialRecordDetailRoute(
    activityId: String,
    transferId: String,
    ledgerUnitId: String?,
    repository: FinancialRecordRepository,
    actorContext: FakeActorContext,
    onBack: () -> Unit,
    onRecreateCorrectRecord: () -> Unit,
) {
    var state by remember(activityId, transferId) {
        mutableStateOf<FinancialDetailRouteState>(FinancialDetailRouteState.Loading)
    }
    var actionError by remember(activityId, transferId) { mutableStateOf<String?>(null) }
    var refreshToken by remember(activityId, transferId) { mutableStateOf(0) }

    androidx.compose.runtime.LaunchedEffect(activityId, transferId, repository, refreshToken) {
        state = FinancialDetailRouteState.Loading
        state = when (val result = repository.get(activityId, transferId)) {
            is FinancialReadResult.Success -> FinancialDetailRouteState.Content(result.value)
            is FinancialReadResult.Failure -> FinancialDetailRouteState.Error(result.message)
        }
    }

    when (val current = state) {
        FinancialDetailRouteState.Loading -> FinancialStateScreen("正在加载资金记录详情…", onBack)
        is FinancialDetailRouteState.Error -> FinancialErrorScreen(current.message, onBack) { refreshToken++ }
        is FinancialDetailRouteState.Content -> {
            val record = current.record
            TransferDetailScreen(
                uiState = TransferDetailUiState(
                    record = record,
                    activityId = activityId,
                    transferId = transferId,
                    ledgerUnitId = ledgerUnitId,
                    errorMessage = actionError,
                    currentParticipantId = actorContext.currentParticipant(record)?.participantId,
                    currentParticipantName = actorContext.currentParticipant(record)?.displayName,
                ),
                onBack = onBack,
                onAddDispute = { _, note ->
                    val currentParticipant = actorContext.currentParticipant(record)
                    if (currentParticipant == null) {
                        actionError = "当前用户不是这笔记录的交易双方"
                    } else {
                        val result = repository.addDispute(activityId, transferId, currentParticipant.participantId, note)
                        if (result.isSuccess) {
                            actionError = null
                            refreshToken++
                        } else {
                            actionError = result.errorMessage
                        }
                    }
                },
                onResolveDispute = { disputeId ->
                    val result = repository.resolveDispute(activityId, disputeId)
                    if (result.isSuccess) {
                        actionError = null
                        refreshToken++
                    } else {
                        actionError = result.errorMessage
                    }
                },
                onVoid = { _, reason ->
                    val result = repository.void(activityId, transferId, reason)
                    if (result.isSuccess) {
                        actionError = null
                        refreshToken++
                    } else {
                        actionError = result.errorMessage
                    }
                },
                onRecreateCorrectRecord = { onRecreateCorrectRecord() },
            )
        }
    }
}

@Composable
private fun FinancialStateScreen(message: String, onBack: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(SharedLedgerSpacing.Large),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Text(message, style = SharedLedgerTextStyles.BodySecondary)
        CircularProgressIndicator()
        SharedLedgerButton("返回", onBack, tone = SharedLedgerButtonTone.Neutral)
    }
}

@Composable
private fun FinancialErrorScreen(message: String, onBack: () -> Unit, onRetry: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(SharedLedgerSpacing.Large),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Text("资金记录加载失败", style = SharedLedgerTextStyles.PageTitle)
        Text(message, style = SharedLedgerTextStyles.BodySecondary)
        SharedLedgerButton("重试", onRetry, tone = SharedLedgerButtonTone.SoftPrimary)
        SharedLedgerButton("返回", onBack, tone = SharedLedgerButtonTone.Neutral)
    }
}

private fun demoTransferRecord(
    draft: com.ffocalors.sharedledger.ui.screens.TransferDraft,
    transferId: String,
    actor: RecorderInfo,
): FundRecord {
    val amount = draft.amount.toBigDecimalOrNull() ?: BigDecimal.ZERO
    val selected = ParticipantInfo(draft.participantId, draft.participantId)
    val current = ParticipantInfo("fake-current-user", "我")
    val from = if (draft.mode == TransferMode.RECEIVE) selected else current
    val to = if (draft.mode == TransferMode.RECEIVE) current else selected
    return FundRecord(
        transferId = transferId,
        activityId = draft.activityId,
        from = from,
        to = to,
        type = FundRecordType.SETTLEMENT,
        amount = amount,
        currency = "CNY",
        occurredAt = "2026-09-02 10:10",
        recordedAt = "2026-09-02 10:10",
        recordedBy = actor,
        components = listOf(FundRecordComponent("$transferId-component", FundRecordComponentType.SETTLEMENT, amount)),
    )
}

internal fun demoFinalSettlementRecord(request: FinalSettlementRequest, transferId: String, actor: RecorderInfo): FundRecord {
    val from = demoParticipant(request.fromParticipantId)
    val to = demoParticipant(request.toParticipantId)
    val components = listOfNotNull(
        request.ordinaryAmount.takeIf { it > BigDecimal.ZERO }
            ?.let { FundRecordComponent("$transferId-ordinary", FundRecordComponentType.SETTLEMENT, it) },
        request.prepaymentReturnAmount.takeIf { it > BigDecimal.ZERO }
            ?.let { FundRecordComponent("$transferId-prepayment-return", FundRecordComponentType.PREPAYMENT_RETURN, it) },
    )
    return FundRecord(
        transferId = transferId,
        activityId = request.activityId,
        from = from,
        to = to,
        type = FundRecordType.FINAL_SETTLEMENT,
        amount = request.amount,
        currency = request.currency,
        occurredAt = "2026-09-02 10:20",
        recordedAt = "2026-09-02 10:20",
        recordedBy = actor,
        components = components,
        finalSettlementPaths = components.mapIndexed { index, component ->
            FinalSettlementPath(index + 1, 1, from, to, component.amount, component.type)
        },
    )
}

private fun demoParticipant(participantId: String): ParticipantInfo = when (participantId) {
    "fake-alice" -> ParticipantInfo(participantId, "Alice")
    "fake-bob" -> ParticipantInfo(participantId, "Bob")
    "fake-carol" -> ParticipantInfo(participantId, "Carol")
    else -> ParticipantInfo(participantId, participantId)
}

internal class DemoExpenseActionHandler(
    private val onStatusChanged: (ExpenseDetailStatus) -> Unit,
    private val onMessage: (String) -> Unit,
) {
    fun edit(expenseId: String) = onMessage("演示：已准备编辑账单 $expenseId")

    fun void(expenseId: String) {
        onStatusChanged(ExpenseDetailStatus.Deleted)
        onMessage("演示：账单 $expenseId 已作废，历史记录仍保留")
    }

    fun restore(expenseId: String) {
        onStatusChanged(ExpenseDetailStatus.Active)
        onMessage("演示：账单 $expenseId 已恢复")
    }

    fun addRefund(expenseId: String) = onMessage("演示：已准备为账单 $expenseId 添加退款")

    fun viewAttachment(expenseId: String, attachmentId: String) =
        onMessage("演示：已打开账单 $expenseId 的凭证 $attachmentId")

    fun deletePermanently(expenseId: String) {
        onStatusChanged(ExpenseDetailStatus.Deleted)
        onMessage("演示：已记录永久删除请求 $expenseId")
    }
}
