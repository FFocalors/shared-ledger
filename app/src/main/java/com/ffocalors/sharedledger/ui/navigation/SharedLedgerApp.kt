package com.ffocalors.sharedledger.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.DisposableEffect
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
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.navigation.NavBackStackEntry
import com.ffocalors.sharedledger.data.auth.AuthRepositoryFactory
import com.ffocalors.sharedledger.data.auth.AuthState
import com.ffocalors.sharedledger.ui.activity.ActivityViewModel
import com.ffocalors.sharedledger.ui.expense.ExpenseFormMode
import com.ffocalors.sharedledger.ui.expense.ExpenseFormParticipant
import com.ffocalors.sharedledger.ui.expense.ExpenseViewModel
import com.ffocalors.sharedledger.ui.expense.toFormDraft
import com.ffocalors.sharedledger.ui.expense.toUiState
import com.ffocalors.sharedledger.data.activity.ActivityType
import com.ffocalors.sharedledger.data.financial.FinancialReadResult
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepository
import com.ffocalors.sharedledger.data.financial.FinancialRecordRepositoryFactory
import com.ffocalors.sharedledger.data.financial.FinancialContext
import com.ffocalors.sharedledger.data.financial.FinalSettlementSuggestion
import com.ffocalors.sharedledger.data.financial.PrepaymentInput
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
import com.ffocalors.sharedledger.ui.screens.PrepaymentMode
import com.ffocalors.sharedledger.ui.screens.PrepaymentScreen
import com.ffocalors.sharedledger.ui.screens.FinalSettlementSuggestionUi
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.ui.transfer.TransferViewModel
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import java.math.BigDecimal
import java.time.Instant
import kotlinx.coroutines.launch

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
private fun RefreshActivityOnResume(
    backStackEntry: NavBackStackEntry,
    onResume: () -> Unit,
) {
    DisposableEffect(backStackEntry) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) onResume()
        }
        backStackEntry.lifecycle.addObserver(observer)
        if (backStackEntry.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) onResume()
        onDispose { backStackEntry.lifecycle.removeObserver(observer) }
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
    val expenseViewModel: ExpenseViewModel = viewModel(
        key = "expense-$currentUserId",
        factory = ExpenseViewModel.Factory(currentUserId = currentUserId),
    )
    val homeState by activityViewModel.home.collectAsState()
    val viewModelJoinState by activityViewModel.join.collectAsState()
    var joinInviteCode by rememberSaveable { mutableStateOf("") }
    var selectedJoinParticipantId by rememberSaveable { mutableStateOf<String?>(null) }
    val financialRepository = remember { FinancialRecordRepositoryFactory.create() }
    fun requireParticipantBinding(activityId: String, action: () -> Unit) {
        val detail = activityViewModel.detail(activityId).value.detail
        if (canPerformFinancialAction(detail, currentUserId)) {
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
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val routeError = "活动路由参数缺失".takeIf { activityId.isBlank() }
            val detailState by activityViewModel.detail(activityId).collectAsState()
            val expenseState by expenseViewModel.listState("activity:$activityId").collectAsState()
            RefreshActivityOnResume(backStackEntry) {
                if (activityId.isNotBlank()) {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByActivity(
                        activityId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, detailState.detail?.summary?.baseCurrency) {
                if (activityId.isNotBlank()) {
                    expenseViewModel.loadByActivity(
                        activityId,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            val defaultLedgerUnitId = detailState.detail?.ledgerUnits?.firstOrNull { it.type.equals("default", true) || it.type.equals("root", true) }?.id
            NormalActivityScreen(
                activity = detailState.detail,
                isLoading = detailState.isLoading,
                errorMessage = routeError ?: detailState.errorMessage,
                expenses = expenseState.expenses,
                expenseLoading = expenseState.isLoading,
                expenseErrorMessage = expenseState.errorMessage,
                onExpenseRetry = {
                    expenseViewModel.loadByActivity(
                        activityId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                },
                onRetry = {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByActivity(
                        activityId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                },
                onBack = { navController.navigateUp() },
                onTransfer = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                    }
                },
                onNewExpense = {
                    requireParticipantBinding(activityId) {
                        defaultLedgerUnitId?.let { navController.navigate(SharedLedgerRoutes.newExpense(activityId, it)) }
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
                    navController.navigate(SharedLedgerRoutes.expenseDetail(activityId, expenseId, defaultLedgerUnitId))
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
            val expenseState by expenseViewModel.listState("activity:$activityId").collectAsState()
            RefreshActivityOnResume(backStackEntry) {
                if (activityId.isNotBlank()) {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByActivity(
                        activityId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, detailState.detail?.summary?.baseCurrency) {
                if (activityId.isNotBlank()) {
                    expenseViewModel.loadByActivity(
                        activityId,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            LargeActivityScreen(
                activity = detailState.detail,
                ledgerUnitAmounts = expenseState.ledgerUnitTotals,
                participantBound = expenseState.participantBound.takeIf { !expenseState.isLoading && expenseState.errorMessage == null },
                isLoading = detailState.isLoading || expenseState.isLoading,
                errorMessage = detailState.errorMessage ?: expenseState.errorMessage,
                onRetry = {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByActivity(
                        activityId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                },
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
                onShowPrepayment = {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.prepayment(activityId, "fund"))
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
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId").orEmpty()
            val routeError = "账本路由参数缺失".takeIf { activityId.isBlank() || ledgerUnitId.isBlank() }
            val detailState by activityViewModel.detail(activityId).collectAsState()
            val expenseState by expenseViewModel.listState("ledger:$ledgerUnitId").collectAsState()
            RefreshActivityOnResume(backStackEntry) {
                if (activityId.isNotBlank()) {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByLedgerUnit(
                        activityId,
                        ledgerUnitId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, ledgerUnitId, detailState.detail?.summary?.baseCurrency) {
                if (routeError == null) {
                    expenseViewModel.loadByLedgerUnit(
                        activityId,
                        ledgerUnitId,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            LedgerUnitScreen(
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                activity = detailState.detail,
                isLoading = detailState.isLoading,
                errorMessage = routeError ?: detailState.errorMessage,
                expenses = expenseState.expenses,
                totalBaseAmount = expenseState.totalBaseAmount,
                participantBound = expenseState.participantBound,
                expenseLoading = expenseState.isLoading,
                expenseErrorMessage = expenseState.errorMessage,
                onExpenseRetry = {
                    expenseViewModel.loadByLedgerUnit(
                        activityId,
                        ledgerUnitId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                },
                onRetry = {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByLedgerUnit(
                        activityId,
                        ledgerUnitId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                },
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
                    navController.navigate(SharedLedgerRoutes.expenseDetail(activityId, expenseId, ledgerUnitId))
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
                navArgument("mode") { type = NavType.StringType; defaultValue = ExpenseFormRouteMode.CREATE.value },
                navArgument("expenseId") { type = NavType.StringType; nullable = true; defaultValue = null },
            ),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val routeLedgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            val expenseId = backStackEntry.arguments?.getString("expenseId")
            val routeMode = parseExpenseFormMode(backStackEntry.arguments?.getString("mode"))
            val activityState by activityViewModel.detail(activityId).collectAsState()
            val detailExpenseState = if (expenseId == null) {
                com.ffocalors.sharedledger.ui.expense.ExpenseDetailRouteState(isLoading = false)
            } else {
                val state by expenseViewModel.detailState(expenseId).collectAsState()
                state
            }
            val formState by expenseViewModel.form.collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId, expenseId) {
                expenseViewModel.clearFormError()
                activityViewModel.loadDetail(activityId)
                if (expenseId != null) expenseViewModel.loadDetail(expenseId)
            }
            val activityDetail = activityState.detail
            val resolvedLedgerUnitId = routeLedgerUnitId
                ?: detailExpenseState.detail?.ledgerUnit?.id
                ?: activityDetail?.ledgerUnits?.firstOrNull { it.type.equals("default", true) || it.type.equals("root", true) }?.id
            val participants = activityDetail?.participants?.map { ExpenseFormParticipant(it.id, it.name) }
                ?: detailExpenseState.detail?.participants?.map { ExpenseFormParticipant(it.id, it.name) }.orEmpty()
            if (activityState.errorMessage != null || detailExpenseState.errorMessage != null) {
                ExpenseRouteStatus(activityState.errorMessage ?: detailExpenseState.errorMessage ?: "账单加载失败", onBack = { navController.navigateUp() })
            } else if (activityState.isLoading || resolvedLedgerUnitId == null || (expenseId != null && detailExpenseState.isLoading)) {
                ExpenseRouteStatus("正在加载账单表单…", onBack = { navController.navigateUp() })
            } else {
                val formMode = when (routeMode) {
                    ExpenseFormRouteMode.EDIT -> ExpenseFormMode.Edit
                    ExpenseFormRouteMode.REFUND -> ExpenseFormMode.Refund
                    ExpenseFormRouteMode.CREATE -> ExpenseFormMode.Create
                }
                NewExpenseScreen(
                    ledgerUnitId = resolvedLedgerUnitId,
                    participants = participants,
                    baseCurrency = activityDetail?.summary?.baseCurrency ?: detailExpenseState.detail?.expense?.originalCurrency ?: "CNY",
                    multiCurrencyEnabled = activityDetail?.summary?.multiCurrencyEnabled == true,
                    mode = formMode,
                    initialDraft = detailExpenseState.detail?.toFormDraft(formMode),
                    isSubmitting = formState.isSubmitting,
                    errorMessage = formState.errorMessage,
                    onBack = { navController.navigateUp() },
                    onSave = { draft -> expenseViewModel.submit(formMode, expenseId, activityId, draft) { navController.navigateUp() } },
                )
            }
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
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            val mode = when (SharedLedgerRoutes.parseTransferMode(backStackEntry.arguments?.getString("mode"))) {
                TransferRouteMode.RECEIVE -> TransferMode.RECEIVE
                TransferRouteMode.TRANSFER -> TransferMode.TRANSFER
            }
            val transferViewModel: TransferViewModel = viewModel(
                key = "transfer-$activityId-${mode.name}",
                factory = TransferViewModel.Factory(),
            )
            val transferState by transferViewModel.uiState.collectAsState()
            androidx.compose.runtime.LaunchedEffect(activityId, mode) {
                if (activityId.isNotBlank()) {
                    transferViewModel.load(
                        activityId,
                        if (mode == TransferMode.RECEIVE) SettlementDirection.RECEIVE else SettlementDirection.TRANSFER,
                    )
                }
            }
            TransferScreen(
                mode = mode,
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                state = transferState.copy(
                    errorMessage = transferState.errorMessage ?: "活动路由参数缺失".takeIf { activityId.isBlank() },
                ),
                onBack = { navController.navigateUp() },
                onRetry = { transferViewModel.retry() },
                onConfirm = { draft ->
                    transferViewModel.submit(draft) {
                        activityViewModel.loadDetail(draft.activityId, force = true)
                        activityViewModel.refreshHome()
                        navController.navigateUp()
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
                onPrepayment = { navController.navigate(SharedLedgerRoutes.prepayment(activityId, "fund")) },
                onPrepaymentReturn = { navController.navigate(SharedLedgerRoutes.prepayment(activityId, "return")) },
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
            arguments = listOf(
                navArgument("expenseId") { type = NavType.StringType },
                navArgument("activityId") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("ledgerUnitId") { type = NavType.StringType; nullable = true; defaultValue = null },
            ),
        ) { backStackEntry ->
            val expenseId = backStackEntry.arguments?.getString("expenseId").orEmpty()
            val routeActivityId = backStackEntry.arguments?.getString("activityId")
            val routeLedgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            val state by expenseViewModel.detailState(expenseId).collectAsState()
            androidx.compose.runtime.LaunchedEffect(expenseId) { expenseViewModel.loadDetail(expenseId) }
            val detail = state.detail
            if (state.isLoading) {
                ExpenseRouteStatus("正在加载账单详情…", onBack = { navController.navigateUp() })
            } else if (state.errorMessage != null || detail == null) {
                ExpenseRouteStatus(state.errorMessage ?: "账单不存在或已被删除", onBack = { navController.navigateUp() })
            } else {
                val activityId = routeActivityId ?: detail.ledgerUnit.activityId
                val ledgerUnitId = routeLedgerUnitId ?: detail.ledgerUnit.id
                ExpenseDetailScreen(
                    uiState = detail.toUiState().copy(actionMessage = state.actionMessage),
                    onBack = { navController.navigateUp() },
                    onEdit = { id -> requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId, ExpenseFormRouteMode.EDIT, id))
                    } },
                    onVoid = { id -> requireParticipantBinding(activityId) { expenseViewModel.delete(id) } },
                    onRestore = { id -> requireParticipantBinding(activityId) { expenseViewModel.restore(id) } },
                    onAddRefund = { id -> requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId, ExpenseFormRouteMode.REFUND, id))
                    } },
                )
            }
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
                currentUserId = currentUserId,
                onBack = { navController.navigateUp() },
                onRecreateCorrectRecord = {
                    navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER, ledgerUnitId))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.PREPAYMENT_PATTERN,
            arguments = listOf(
                navArgument("activityId") { type = NavType.StringType },
                navArgument("mode") { type = NavType.StringType; defaultValue = "fund" },
            ),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val mode = if (backStackEntry.arguments?.getString("mode") == "return") PrepaymentMode.RETURN else PrepaymentMode.FUND
            var context by remember(activityId) { mutableStateOf<FinancialContext?>(null) }
            var loading by remember(activityId) { mutableStateOf(true) }
            var submitting by remember(activityId) { mutableStateOf(false) }
            var error by remember(activityId) { mutableStateOf<String?>(null) }
            var reload by remember(activityId) { mutableStateOf(0) }
            val scope = androidx.compose.runtime.rememberCoroutineScope()
            RefreshActivityOnResume(backStackEntry) { reload++ }
            androidx.compose.runtime.LaunchedEffect(activityId, reload) {
                loading = true
                error = null
                when (val result = financialRepository.loadPrepaymentContext(activityId)) {
                    is FinancialReadResult.Success -> context = result.value
                    is FinancialReadResult.Failure -> error = result.message
                }
                loading = false
            }
            PrepaymentScreen(
                mode = mode,
                context = context,
                isLoading = loading,
                isSubmitting = submitting,
                errorMessage = error,
                onRetry = { reload++ },
                onBack = { navController.navigateUp() },
                onSubmit = { ownerId, custodianId, amount ->
                    if (ownerId == custodianId) {
                        error = "预存所有者和保管人不能是同一位参与人"
                    } else if (!submitting) {
                        submitting = true
                        error = null
                        val input = PrepaymentInput(activityId, ownerId, custodianId, amount, Instant.now().toString())
                        scope.launch {
                            val result = if (mode == PrepaymentMode.FUND) financialRepository.createPrepayment(input) else financialRepository.createPrepaymentReturn(input)
                            submitting = false
                            if (result.isSuccess) {
                                activityViewModel.loadDetail(activityId, force = true)
                                activityViewModel.refreshHome()
                                navController.navigate(SharedLedgerRoutes.transferDetail(activityId, result.value!!.transferId)) {
                                    popUpTo(SharedLedgerRoutes.PREPAYMENT_PATTERN) { inclusive = true }
                                }
                            } else error = result.errorMessage
                        }
                    }
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId")
                ?: DemoRouteIds.LARGE_ACTIVITY
            var suggestions by remember(activityId) { mutableStateOf<List<FinalSettlementSuggestionUi>>(emptyList()) }
            var loading by remember(activityId) { mutableStateOf(true) }
            var error by remember(activityId) { mutableStateOf<String?>(null) }
            var submitting by remember(activityId) { mutableStateOf(false) }
            var refreshToken by remember(activityId) { mutableStateOf(0) }
            val scope = androidx.compose.runtime.rememberCoroutineScope()
            androidx.compose.runtime.LaunchedEffect(activityId, refreshToken) {
                loading = true
                error = null
                when (val result = financialRepository.previewFinalSettlement(activityId)) {
                    is FinancialReadResult.Success -> suggestions = result.value.map { item ->
                        FinalSettlementSuggestionUi(
                            id = item.id,
                            fromParticipantId = item.from.participantId,
                            toParticipantId = item.to.participantId,
                            from = com.ffocalors.sharedledger.ui.components.ParticipantUiModel(item.from.displayName),
                            to = com.ffocalors.sharedledger.ui.components.ParticipantUiModel(item.to.displayName),
                            amount = item.amount,
                            currency = item.currency,
                            ordinaryAmount = item.ordinaryAmount,
                            prepaymentReturnAmount = item.prepaymentReturnAmount,
                            sourceFinancialVersion = item.sourceFinancialVersion,
                        )
                    }
                    is FinancialReadResult.Failure -> error = result.message
                }
                loading = false
            }
            FinalSettlementScreen(
                activityId = activityId,
                onBack = { navController.navigateUp() },
                suggestions = suggestions,
                isLoading = loading || submitting,
                errorMessage = error,
                onRetry = { refreshToken++ },
                onFinalize = { request ->
                    if (!submitting) {
                        val item = suggestions.firstOrNull { it.id == request.previewItemId }
                        if (item == null || !request.isValid()) {
                            error = "当前结算方案已发生变化，请重新查看最新方案。"
                            refreshToken++
                        } else {
                            submitting = true
                            scope.launch {
                                val remoteItem = FinalSettlementSuggestion(
                                    id = item.id,
                                    activityId = activityId,
                                    from = com.ffocalors.sharedledger.domain.financial.ParticipantInfo(item.fromParticipantId, item.from.name),
                                    to = com.ffocalors.sharedledger.domain.financial.ParticipantInfo(item.toParticipantId, item.to.name),
                                    amount = item.amount,
                                    ordinaryAmount = item.ordinaryAmount,
                                    prepaymentReturnAmount = item.prepaymentReturnAmount,
                                    currency = item.currency,
                                    sourceFinancialVersion = item.sourceFinancialVersion,
                                )
                                val written = financialRepository.executeFinalSettlement(remoteItem, Instant.now().toString())
                                submitting = false
                                if (written.isSuccess) {
                                    activityViewModel.loadDetail(activityId, force = true)
                                    activityViewModel.refreshHome()
                                    navController.navigate(SharedLedgerRoutes.transferDetail(activityId, written.value!!.transferId)) {
                                        popUpTo(SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN) { inclusive = true }
                                        launchSingleTop = true
                                    }
                                } else {
                                    error = written.errorMessage
                                    refreshToken++
                                }
                            }
                        }
                    }
                },
            )
        }
    }
}

@Composable
private fun ExpenseRouteStatus(message: String, onBack: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(SharedLedgerSpacing.Large),
        horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium, androidx.compose.ui.Alignment.CenterVertically),
    ) {
        if (message.startsWith("正在")) CircularProgressIndicator()
        Text(message, style = SharedLedgerTextStyles.BodySecondary)
        SharedLedgerButton("返回", onBack, tone = SharedLedgerButtonTone.Neutral)
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
    currentUserId: String,
    onBack: () -> Unit,
    onRecreateCorrectRecord: () -> Unit,
) {
    var state by remember(activityId, transferId) {
        mutableStateOf<FinancialDetailRouteState>(FinancialDetailRouteState.Loading)
    }
    var actionError by remember(activityId, transferId) { mutableStateOf<String?>(null) }
    var refreshToken by remember(activityId, transferId) { mutableStateOf(0) }
    var isSubmitting by remember(activityId, transferId) { mutableStateOf(false) }
    var currentParticipantId by remember(activityId, transferId) { mutableStateOf<String?>(null) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    androidx.compose.runtime.LaunchedEffect(activityId, transferId, repository, refreshToken) {
        state = FinancialDetailRouteState.Loading
        state = when (val result = repository.get(activityId, transferId)) {
            is FinancialReadResult.Success -> FinancialDetailRouteState.Content(result.value)
            is FinancialReadResult.Failure -> FinancialDetailRouteState.Error(result.message)
        }
        currentParticipantId = when (val result = repository.currentParticipantId(activityId)) {
            is FinancialReadResult.Success -> result.value
            is FinancialReadResult.Failure -> null
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
                    currentParticipantId = currentParticipantId,
                    currentParticipantName = currentParticipantId?.let { participantId ->
                        listOf(record.from, record.to).firstOrNull { it.participantId == participantId }?.displayName
                    },
                ),
                onBack = onBack,
                onAddDispute = { _, note ->
                    if (currentParticipantId == null) {
                        actionError = "当前用户不是这笔记录的交易双方"
                    } else if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.addDispute(activityId, transferId, currentParticipantId!!, note)
                            isSubmitting = false
                            if (result.isSuccess) { actionError = null; refreshToken++ } else actionError = result.errorMessage
                        }
                    }
                },
                onResolveDispute = { disputeId ->
                    if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.resolveDispute(activityId, disputeId)
                            isSubmitting = false
                            if (result.isSuccess) { actionError = null; refreshToken++ } else actionError = result.errorMessage
                        }
                    }
                },
                onVoid = { _, reason ->
                    if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.void(activityId, transferId, reason)
                            isSubmitting = false
                            if (result.isSuccess) { actionError = null; refreshToken++ } else actionError = result.errorMessage
                        }
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

internal fun canPerformFinancialAction(
    detail: com.ffocalors.sharedledger.data.activity.ActivityDetail?,
    currentUserId: String,
): Boolean = detail?.members?.any { member ->
    member.userId == currentUserId && member.claimedParticipantId != null
} == true
