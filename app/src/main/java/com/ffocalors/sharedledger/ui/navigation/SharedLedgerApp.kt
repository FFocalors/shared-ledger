package com.ffocalors.sharedledger.ui.navigation

import android.content.ClipData
import android.content.ClipboardManager
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
import androidx.compose.ui.platform.LocalContext
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
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.navArgument
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
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
import com.ffocalors.sharedledger.data.financial.FinancialWriteResult
import com.ffocalors.sharedledger.data.financial.FinancialContext
import com.ffocalors.sharedledger.data.financial.FinalSettlementSuggestion
import com.ffocalors.sharedledger.data.financial.PrepaymentInput
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
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
import com.ffocalors.sharedledger.ui.screens.PersonalInfoScreen
import com.ffocalors.sharedledger.ui.screens.TransferMode
import com.ffocalors.sharedledger.ui.screens.TransferScreen
import com.ffocalors.sharedledger.ui.screens.PrepaymentMode
import com.ffocalors.sharedledger.ui.screens.PrepaymentScreen
import com.ffocalors.sharedledger.ui.screens.FinalSettlementSuggestionUi
import com.ffocalors.sharedledger.ui.screens.FinalSettlementParticipantOption
import com.ffocalors.sharedledger.data.transfer.SettlementDirection
import com.ffocalors.sharedledger.ui.transfer.TransferViewModel
import com.ffocalors.sharedledger.ui.attachment.AttachmentClientItem
import com.ffocalors.sharedledger.ui.attachment.AttachmentUiState
import com.ffocalors.sharedledger.ui.attachment.AttachmentViewModel
import com.ffocalors.sharedledger.ui.attachment.AttachmentImagePreviewDialog
import com.ffocalors.sharedledger.ui.attachment.AttachmentInputSourceDialog
import com.ffocalors.sharedledger.ui.attachment.rememberAttachmentInputController
import com.ffocalors.sharedledger.ui.attachment.MAX_CLIENT_ATTACHMENTS
import com.ffocalors.sharedledger.ui.attachment.toExpenseDetailUiState
import com.ffocalors.sharedledger.ui.attachment.toLedgerUnitUiState
import com.ffocalors.sharedledger.ui.attachment.toNewExpenseUiState
import com.ffocalors.sharedledger.ui.realtime.ActivityRealtimeViewModel
import com.ffocalors.sharedledger.data.realtime.ActivityRealtimeDomain
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import java.time.Instant
import kotlinx.coroutines.launch

@Composable
fun SharedLedgerApp(
    modifier: Modifier = Modifier,
    pendingAuthDeepLink: String? = null,
    onAuthDeepLinkConsumed: () -> Unit = {},
) {
    val authRepository = remember { AuthRepositoryFactory.create() }
    val authViewModel: com.ffocalors.sharedledger.ui.auth.AuthViewModel = viewModel(
        factory = com.ffocalors.sharedledger.ui.auth.AuthViewModel.Factory(authRepository),
    )
    val authUiState by authViewModel.uiState.collectAsState()

    androidx.compose.runtime.LaunchedEffect(pendingAuthDeepLink) {
        pendingAuthDeepLink?.takeIf(String::isNotBlank)?.let { deepLink ->
            authViewModel.handlePasswordRecoveryLink(deepLink)
            onAuthDeepLinkConsumed()
        }
    }

    if (authUiState.isPasswordRecovery) {
        AuthScreen(
            modifier = modifier,
            errorMessage = authUiState.message,
            isLoading = authUiState.isSubmitting,
            isPasswordRecovery = true,
            onSetNewPassword = authViewModel::updatePassword,
        )
    } else {
        when (val authState = authUiState.authState) {
            AuthState.Loading -> AuthLoadingScreen(modifier)
            is AuthState.Authenticated -> key(authState.user.id) {
                AuthenticatedNavHost(
                    modifier = modifier,
                    currentUserId = authState.user.id,
                    currentUserDisplayName = authState.user.displayName,
                    currentUserEmail = authState.user.email,
                    onSignOut = authViewModel::signOut,
                )
            }
            AuthState.Unauthenticated, is AuthState.Error -> AuthScreen(
                modifier = modifier,
                errorMessage = authUiState.message,
                isLoading = authUiState.isSubmitting,
                onLogin = authViewModel::signIn,
                onRegister = authViewModel::signUp,
                onForgotPassword = authViewModel::requestPasswordReset,
            )
        }
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
    currentUserDisplayName: String,
    currentUserEmail: String,
    onSignOut: () -> Unit,
) {
    val navController = rememberNavController()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val currentBackStackEntry by navController.currentBackStackEntryAsState()
    val realtimeViewModel: ActivityRealtimeViewModel = viewModel(
        key = "realtime-$currentUserId",
    )
    val realtimeState by realtimeViewModel.uiState.collectAsState()
    val currentActivityId = currentBackStackEntry?.arguments?.getString("activityId")
    androidx.compose.runtime.LaunchedEffect(currentActivityId) {
        realtimeViewModel.observeActivity(currentActivityId)
    }
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) realtimeViewModel.onForeground()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
            realtimeViewModel.onForeground()
        }
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            realtimeViewModel.stop()
        }
    }
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
                userDisplayName = currentUserDisplayName,
                onProfileClick = { navController.navigate(SharedLedgerRoutes.PERSONAL_INFO) },
            )
        }
        composable(SharedLedgerRoutes.PERSONAL_INFO) {
            PersonalInfoScreen(
                displayName = currentUserDisplayName,
                email = currentUserEmail,
                onBack = { navController.navigateUp() },
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
            val defaultLedgerUnitId = detailState.detail?.ledgerUnits?.firstOrNull { it.type.equals("default", true) || it.type.equals("root", true) }?.id
            val canWriteActivity = detailState.detail?.let { it.summary.archivedAt == null } == true
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
            androidx.compose.runtime.LaunchedEffect(
                activityId,
                realtimeState.revisions.activityIdentity,
                realtimeState.revisions.expense,
                realtimeState.revisions.financial,
            ) {
                if (activityId.isNotBlank() && realtimeState.activeActivityId == activityId) {
                    if (realtimeState.revisions.activityIdentity > 0L || realtimeState.revisions.financial > 0L) {
                        activityViewModel.loadDetail(activityId, force = true)
                    }
                    if (realtimeState.revisions.expense > 0L || realtimeState.revisions.financial > 0L) {
                        expenseViewModel.loadByActivity(
                            activityId,
                            force = true,
                            baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                        )
                    }
                }
            }
            NormalActivityScreen(
                activity = detailState.detail,
                isLoading = detailState.isLoading,
                errorMessage = routeError ?: detailState.errorMessage,
                expenses = expenseState.expenses,
                totalBaseAmount = expenseState.totalBaseAmount,
                participantBound = expenseState.participantBound,
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
                onTransfer = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                    }
                } } else null,
                onNewExpense = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        defaultLedgerUnitId?.let { navController.navigate(SharedLedgerRoutes.newExpense(activityId, it)) }
                    }
                } } else null,
                onRefund = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        defaultLedgerUnitId?.let {
                            navController.navigate(SharedLedgerRoutes.newExpense(activityId, it, ExpenseFormRouteMode.REFUND))
                        }
                    }
                } } else null,
                onReceive = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE))
                    }
                } } else null,
                onFundRecords = if (activityId.isNotBlank()) {
                    {
                    navController.navigate(SharedLedgerRoutes.fundRecords(activityId)) { launchSingleTop = true }
                    }
                } else { {} },
                onManageActivity = if (activityId.isNotBlank()) {
                    {
                    navController.navigate(SharedLedgerRoutes.activityManagement(activityId))
                    }
                } else null,
                onExpenseClick = { expenseId ->
                    navController.navigate(SharedLedgerRoutes.expenseDetail(activityId, expenseId, defaultLedgerUnitId))
                },
            )
        }
        composable(
            route = SharedLedgerRoutes.LARGE_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val detailState by activityViewModel.detail(activityId).collectAsState()
            val expenseState by expenseViewModel.listState("activity:$activityId").collectAsState()
            val defaultLedgerUnitId = detailState.detail?.ledgerUnits?.firstOrNull { it.type.equals("default", true) || it.type.equals("root", true) }?.id
            val canWriteActivity = detailState.detail?.let { it.summary.archivedAt == null } == true
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
            androidx.compose.runtime.LaunchedEffect(
                activityId,
                realtimeState.revisions.activityIdentity,
                realtimeState.revisions.expense,
                realtimeState.revisions.financial,
            ) {
                if (activityId.isNotBlank() && realtimeState.activeActivityId == activityId) {
                    if (realtimeState.revisions.activityIdentity > 0L || realtimeState.revisions.financial > 0L) {
                        activityViewModel.loadDetail(activityId, force = true)
                    }
                    if (realtimeState.revisions.expense > 0L || realtimeState.revisions.financial > 0L) {
                        expenseViewModel.loadByActivity(
                            activityId,
                            force = true,
                            baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                        )
                    }
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
                onSubActivityClick = if (activityId.isNotBlank()) { { id ->
                    navController.navigate(SharedLedgerRoutes.ledgerUnit(activityId, id))
                } } else { { _: String -> } },
                onAddSubActivity = if (detailState.detail?.let { it.summary.archivedAt == null && it.permissions.canCreateSubActivity } == true) { {
                    navController.navigate(SharedLedgerRoutes.createSubActivity(activityId))
                } } else null,
                onFinalSettlement = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.finalSettlement(activityId))
                    }
                } } else null,
                onTransfer = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER))
                    }
                } } else null,
                onRefund = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        defaultLedgerUnitId?.let {
                            navController.navigate(SharedLedgerRoutes.newExpense(activityId, it, ExpenseFormRouteMode.REFUND))
                        }
                    }
                } } else null,
                onReceive = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE))
                    }
                } } else null,
                onShowPrepayment = if (canWriteActivity) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.prepayment(activityId, "fund"))
                    }
                } } else null,
                onFundRecords = if (activityId.isNotBlank()) {
                    {
                    navController.navigate(SharedLedgerRoutes.fundRecords(activityId)) { launchSingleTop = true }
                    }
                } else { {} },
                onManageActivity = if (activityId.isNotBlank()) {
                    {
                    navController.navigate(SharedLedgerRoutes.activityManagement(activityId))
                    }
                } else null,
            )
        }
        composable(
            route = SharedLedgerRoutes.CREATE_SUB_ACTIVITY_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            if (activityId.isBlank()) {
                ExpenseRouteStatus("活动路由参数缺失", onBack = { navController.navigateUp() })
            } else {
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
            val activityWritable = isActivityWritable(detailState.detail)
            val attachmentViewModel: AttachmentViewModel = viewModel(
                key = "attachments-ledger-$activityId-$ledgerUnitId",
                factory = AttachmentViewModel.Factory(),
            )
            val attachmentState by attachmentViewModel.uiState.collectAsState()
            val attachmentScope = androidx.compose.runtime.rememberCoroutineScope()
            var attachmentMessage by remember { mutableStateOf<String?>(null) }
            var attachmentPreview by remember { mutableStateOf<Pair<String, ByteArray>?>(null) }
            val attachmentInput = rememberAttachmentInputController(
                currentCount = attachmentState.items.size,
                onUrisSelected = { selections ->
                    var accepted = false
                    selections.forEach { selection ->
                        when (attachmentViewModel.addImage(context.contentResolver, selection.uri, selection.displayName)) {
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> accepted = true
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = "活动已归档，附件不可修改"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedLimit -> attachmentMessage = "附件最多保留 10 个"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedInvalid -> attachmentMessage = "图片处理失败"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = "附件添加失败"
                        }
                    }
                    if (accepted) {
                        when (val result = attachmentViewModel.uploadLedgerUnitAttachments()) {
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.Completed -> attachmentMessage = null
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.Partial -> attachmentMessage = "部分附件上传未完成，可逐项重试"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.RejectedArchived -> attachmentMessage = result.message
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.Failed -> attachmentMessage = result.message
                        }
                    }
                },
                onError = { attachmentMessage = it.message ?: "附件选择失败" },
            )
            RefreshActivityOnResume(backStackEntry) {
                if (activityId.isNotBlank()) {
                    activityViewModel.loadDetail(activityId, force = true)
                    expenseViewModel.loadByLedgerUnit(
                        activityId,
                        ledgerUnitId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                    attachmentViewModel.loadLedgerUnit(activityId, ledgerUnitId)
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
            androidx.compose.runtime.LaunchedEffect(activityId, ledgerUnitId) {
                if (activityId.isNotBlank() && ledgerUnitId.isNotBlank()) attachmentViewModel.loadLedgerUnit(activityId, ledgerUnitId)
            }
            androidx.compose.runtime.LaunchedEffect(activityId, ledgerUnitId, realtimeState.revisions.attachment) {
                if (realtimeState.revisions.attachment > 0L &&
                    activityId.isNotBlank() && ledgerUnitId.isNotBlank() &&
                    canReloadExternalAttachments(attachmentState)
                ) {
                    attachmentViewModel.loadLedgerUnit(activityId, ledgerUnitId)
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, ledgerUnitId, realtimeState.revisions.expense, realtimeState.revisions.financial) {
                if (realtimeState.activeActivityId == activityId &&
                    (realtimeState.revisions.expense > 0L || realtimeState.revisions.financial > 0L)
                ) {
                    expenseViewModel.loadByLedgerUnit(
                        activityId,
                        ledgerUnitId,
                        force = true,
                        baseCurrency = detailState.detail?.summary?.baseCurrency ?: "CNY",
                    )
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, realtimeState.revisions.activityIdentity) {
                if (realtimeState.activeActivityId == activityId && realtimeState.revisions.activityIdentity > 0L) {
                    activityViewModel.loadDetail(activityId, force = true)
                }
            }
            androidx.compose.runtime.LaunchedEffect(detailState.detail) {
                attachmentViewModel.writesEnabled = activityWritable
            }
            AttachmentInputSourceDialog(attachmentInput)
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
                onTransfer = if (activityWritable) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(
                            SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER, ledgerUnitId),
                        )
                    }
                } } else null,
                onNewExpense = if (activityWritable) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId))
                    }
                } } else null,
                onRefund = if (activityWritable) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(
                            SharedLedgerRoutes.newExpense(activityId, ledgerUnitId, ExpenseFormRouteMode.REFUND),
                        )
                    }
                } } else null,
                onReceive = if (activityWritable) { {
                    requireParticipantBinding(activityId) {
                        navController.navigate(
                            SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE, ledgerUnitId),
                        )
                    }
                } } else null,
                attachments = attachmentState.toLedgerUnitUiState { item -> canDeleteAttachment(item, detailState.detail, currentUserId) },
                attachmentMessage = attachmentMessage ?: attachmentState.errorMessage,
                onAddAttachment = if (activityWritable && attachmentState.items.size < MAX_CLIENT_ATTACHMENTS) attachmentInput.requestSourceChooser else null,
                onAttachmentClick = { attachmentId ->
                    attachmentMessage = "正在加载附件…"
                    attachmentScope.launch {
                        attachmentViewModel.downloadReady(attachmentId).fold(
                            onSuccess = { bytes ->
                                val item = attachmentState.items.firstOrNull { it.clientId == attachmentId }
                                attachmentPreview = (item?.fileName ?: "附件") to bytes
                                attachmentMessage = null
                            },
                            onFailure = { attachmentMessage = it.message ?: "附件加载失败" },
                        )
                    }
                },
                onRetryAttachment = if (activityWritable) { { attachmentId ->
                    attachmentScope.launch {
                        when (val result = attachmentViewModel.retryAttachment(attachmentId)) {
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> attachmentMessage = null
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = result.message
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = result.message
                            else -> attachmentMessage = "附件重试失败"
                        }
                    }
                } } else null,
                onDeleteAttachment = if (activityWritable) { { attachmentId ->
                    attachmentScope.launch {
                        when (val result = attachmentViewModel.deleteAttachment(attachmentId)) {
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> attachmentMessage = null
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = result.message
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = result.message
                            else -> attachmentMessage = "附件删除失败"
                        }
                    }
                } } else null,
                onFundRecords = {
                    navController.navigate(SharedLedgerRoutes.fundRecords(activityId, ledgerUnitId)) {
                        launchSingleTop = true
                    }
                },
                onExpenseClick = { expenseId ->
                    navController.navigate(SharedLedgerRoutes.expenseDetail(activityId, expenseId, ledgerUnitId))
                },
            )
            attachmentPreview?.let { (fileName, bytes) ->
                AttachmentImagePreviewDialog(bytes = bytes, filename = fileName, onDismiss = { attachmentPreview = null })
            }
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
            val attachmentViewModel: AttachmentViewModel = viewModel(
                key = "attachments-expense-form-$activityId-${expenseId ?: "new"}",
                factory = AttachmentViewModel.Factory(),
            )
            val attachmentState by attachmentViewModel.uiState.collectAsState()
            val attachmentScope = androidx.compose.runtime.rememberCoroutineScope()
            var attachmentMessage by remember { mutableStateOf<String?>(null) }
            var persistedExpenseId by remember(activityId, expenseId, routeMode) {
                mutableStateOf<String?>(null)
            }
            val attachmentInput = rememberAttachmentInputController(
                currentCount = attachmentState.items.size,
                onUrisSelected = { selections ->
                    selections.forEach { selection ->
                        when (attachmentViewModel.addImage(context.contentResolver, selection.uri, selection.displayName)) {
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> Unit
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = "活动已归档，附件不可修改"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedLimit -> attachmentMessage = "附件最多保留 10 个"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedInvalid -> attachmentMessage = "图片处理失败"
                            is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = "附件添加失败"
                        }
                    }
                },
                onError = { attachmentMessage = it.message ?: "附件选择失败" },
            )
            androidx.compose.runtime.LaunchedEffect(activityId, expenseId) {
                expenseViewModel.clearFormError()
                activityViewModel.loadDetail(activityId)
                if (expenseId != null) expenseViewModel.loadDetail(expenseId)
            }
            val activityDetail = activityState.detail
            val activityWritable = isActivityWritable(activityDetail)
            val resolvedLedgerUnitId = routeLedgerUnitId
                ?: detailExpenseState.detail?.ledgerUnit?.id
                ?: activityDetail?.ledgerUnits?.firstOrNull { it.type.equals("default", true) || it.type.equals("root", true) }?.id
            val participants = activityDetail?.participants?.map { ExpenseFormParticipant(it.id, it.name) }
                ?: detailExpenseState.detail?.participants?.map { ExpenseFormParticipant(it.id, it.name) }.orEmpty()
            val currentParticipantId = activityDetail?.members
                ?.firstOrNull { it.userId == currentUserId }
                ?.claimedParticipantId
            androidx.compose.runtime.LaunchedEffect(activityId, resolvedLedgerUnitId, expenseId, routeMode) {
                if (resolvedLedgerUnitId.isNullOrBlank()) return@LaunchedEffect
                if (routeMode == ExpenseFormRouteMode.EDIT && expenseId != null) {
                    attachmentViewModel.loadExpense(activityId, resolvedLedgerUnitId, expenseId)
                } else {
                    attachmentViewModel.beginExpenseDraft(activityId, resolvedLedgerUnitId)
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityDetail) {
                attachmentViewModel.writesEnabled = isActivityWritable(activityDetail)
            }
            AttachmentInputSourceDialog(attachmentInput)
            suspend fun uploadExpenseAttachments(targetExpenseId: String) {
                when (val result = attachmentViewModel.uploadExpenseAttachments(targetExpenseId)) {
                    is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.Completed -> {
                        attachmentMessage = null
                        navController.navigateUp()
                    }
                    is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.Partial -> attachmentMessage = "部分附件上传未完成，可逐项重试后再次保存"
                    is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.RejectedArchived -> attachmentMessage = result.message
                    is com.ffocalors.sharedledger.ui.attachment.AttachmentBatchResult.Failed -> attachmentMessage = result.message
                }
            }
            if (activityState.errorMessage != null || detailExpenseState.errorMessage != null) {
                ExpenseRouteStatus(activityState.errorMessage ?: detailExpenseState.errorMessage ?: "账单加载失败", onBack = { navController.navigateUp() })
            } else if (activityState.isLoading || resolvedLedgerUnitId == null || (expenseId != null && detailExpenseState.isLoading)) {
                ExpenseRouteStatus("正在加载账单表单…", onBack = { navController.navigateUp() })
            } else if (!isActivityWritable(activityDetail)) {
                ExpenseRouteStatus("活动已归档或状态不可用，当前为只读状态，不能新增、修改或退款账单。", onBack = { navController.navigateUp() })
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
                    currentParticipantId = currentParticipantId,
                    mode = formMode,
                    initialDraft = detailExpenseState.detail?.toFormDraft(formMode),
                    attachments = attachmentState.toNewExpenseUiState { item -> canDeleteAttachment(item, activityDetail, currentUserId) },
                    isSubmitting = formState.isSubmitting || attachmentState.isLoading || attachmentState.isWriting,
                    errorMessage = formState.errorMessage ?: attachmentMessage ?: attachmentState.errorMessage,
                    onBack = { navController.navigateUp() },
                    onRefreshConfirmation = if (formState.writeState == com.ffocalors.sharedledger.data.expense.ExpenseWriteState.UNKNOWN) {
                        {
                            expenseViewModel.recoverFromUnknownWrite(
                                activityId = activityId,
                                ledgerUnitId = resolvedLedgerUnitId,
                                expenseId = persistedExpenseId ?: expenseId,
                                onConfirmed = { navController.navigateUp() },
                            )
                        }
                    } else null,
                    onSave = { draft ->
                        val savedExpenseId = persistedExpenseId
                        if (savedExpenseId != null) {
                            expenseViewModel.submit(ExpenseFormMode.Edit, savedExpenseId, activityId, draft) { updatedExpenseId ->
                                persistedExpenseId = updatedExpenseId
                                attachmentScope.launch { uploadExpenseAttachments(updatedExpenseId) }
                            }
                        } else {
                            expenseViewModel.submit(formMode, expenseId, activityId, draft) { createdExpenseId ->
                                persistedExpenseId = createdExpenseId
                                attachmentScope.launch { uploadExpenseAttachments(createdExpenseId) }
                            }
                        }
                    },
                    onAddAttachment = if (activityWritable && attachmentState.items.size < MAX_CLIENT_ATTACHMENTS) attachmentInput.requestSourceChooser else null,
                    onRemoveAttachment = if (activityWritable) { { attachmentId ->
                        attachmentScope.launch {
                            when (val result = attachmentViewModel.deleteAttachment(attachmentId)) {
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> attachmentMessage = null
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = result.message
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = result.message
                                else -> attachmentMessage = "附件移除失败"
                            }
                        }
                    } } else null,
                    onRetryAttachment = if (activityWritable) { { attachmentId ->
                        attachmentScope.launch {
                            when (val result = attachmentViewModel.retryAttachment(attachmentId)) {
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> attachmentMessage = null
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = result.message
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = result.message
                                else -> attachmentMessage = "附件重试失败"
                            }
                        }
                    } } else null,
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
            val activityDetailState by activityViewModel.detail(activityId).collectAsState()
            val transferWritesEnabled = activityId.isNotBlank() &&
                !activityDetailState.isLoading &&
                activityDetailState.errorMessage == null &&
                canPerformFinancialAction(activityDetailState.detail, currentUserId)
            val transferRouteError = when {
                activityId.isBlank() -> "活动路由参数缺失"
                activityDetailState.isLoading -> "正在验证活动权限…"
                activityDetailState.errorMessage != null -> activityDetailState.errorMessage
                !transferWritesEnabled -> "活动已归档、已移除成员，或当前成员无权执行资金操作"
                else -> null
            }
            androidx.compose.runtime.LaunchedEffect(activityId) {
                if (activityId.isNotBlank()) activityViewModel.loadDetail(activityId)
            }
            androidx.compose.runtime.LaunchedEffect(activityId, realtimeState.revisions.activityIdentity) {
                if (activityId.isNotBlank() && realtimeState.activeActivityId == activityId &&
                    realtimeState.revisions.activityIdentity > 0L
                ) {
                    activityViewModel.loadDetail(activityId, force = true)
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, mode) {
                if (activityId.isNotBlank()) {
                    transferViewModel.load(
                        activityId,
                        if (mode == TransferMode.RECEIVE) SettlementDirection.RECEIVE else SettlementDirection.TRANSFER,
                        force = true,
                    )
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityId, mode, realtimeState.revisions.financial) {
                if (realtimeState.revisions.financial > 0L && realtimeState.activeActivityId == activityId) {
                    transferViewModel.load(
                        activityId,
                        if (mode == TransferMode.RECEIVE) SettlementDirection.RECEIVE else SettlementDirection.TRANSFER,
                        force = true,
                    )
                }
            }
            TransferScreen(
                mode = mode,
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                state = transferState.copy(
                    errorMessage = transferRouteError ?: transferState.errorMessage,
                ),
                onBack = { navController.navigateUp() },
                onRetry = {
                    activityViewModel.loadDetail(activityId, force = true)
                    transferViewModel.retry()
                },
                onConfirm = if (transferWritesEnabled) { { draft ->
                    transferViewModel.submit(draft) {
                        activityViewModel.loadDetail(draft.activityId, force = true)
                        activityViewModel.refreshHome()
                        navController.navigateUp()
                    }
                } } else null,
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
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            if (activityId.isBlank()) {
                ExpenseRouteStatus("活动路由参数缺失", onBack = { navController.navigateUp() })
            } else {
                val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
                FundRecordsScreen(
                    activityId = activityId,
                    ledgerUnitId = ledgerUnitId,
                    externalRefreshToken = realtimeState.revisions.financial,
                    repository = financialRepository,
                    onBack = { navController.navigateUp() },
                    onRecordClick = { record ->
                        if (record.source == com.ffocalors.sharedledger.domain.financial.FundRecordSource.REFUND_EXPENSE) {
                            record.sourceExpenseId?.let { navController.navigate(SharedLedgerRoutes.expenseDetail(activityId, it)) }
                        } else {
                            navController.navigate(SharedLedgerRoutes.transferDetail(activityId, record.transferId, ledgerUnitId)) {
                                launchSingleTop = true
                            }
                        }
                    },
                    onPrepayment = { navController.navigate(SharedLedgerRoutes.prepayment(activityId, "fund")) },
                    onPrepaymentReturn = { navController.navigate(SharedLedgerRoutes.prepayment(activityId, "return")) },
                )
            }
        }
        composable(
            route = SharedLedgerRoutes.ACTIVITY_MANAGEMENT_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            if (activityId.isBlank()) {
                ExpenseRouteStatus("活动路由参数缺失", onBack = { navController.navigateUp() })
            } else {
                val detailState by activityViewModel.detail(activityId).collectAsState()
                val managementState = activityViewModel.managementState(activityId)
                val actionLoading by activityViewModel.actionLoading.collectAsState()
                val managementMessage by activityViewModel.message.collectAsState()
                androidx.compose.runtime.LaunchedEffect(activityId) {
                    activityViewModel.loadDetail(activityId)
                }
                androidx.compose.runtime.LaunchedEffect(
                    activityId,
                    realtimeState.revisions.activityIdentity,
                    realtimeState.revisions.financial,
                ) {
                    if (realtimeState.activeActivityId == activityId &&
                        (realtimeState.revisions.activityIdentity > 0L || realtimeState.revisions.financial > 0L)
                    ) {
                        activityViewModel.loadDetail(activityId, force = true)
                    }
                }
                ActivityManagementScreen(
                    activityId = activityId,
                    state = managementState
                        ?: com.ffocalors.sharedledger.ui.screens.ActivityManagementUiState(),
                    isLoading = detailState.isLoading || managementState == null || actionLoading,
                    errorMessage = detailState.errorMessage,
                    message = managementMessage,
                    onMessageShown = activityViewModel::clearMessage,
                    onRetry = { activityViewModel.loadDetail(activityId, force = true) },
                    onBackClick = { navController.navigateUp() },
                    onCopyJoinCode = { _, joinCode ->
                        val clipboard = context.getSystemService(ClipboardManager::class.java)
                        clipboard?.setPrimaryClip(
                            ClipData.newPlainText("SharedLedger 加入码", joinCode.replace(" ", "")),
                        )
                    },
                    onUpdateActivityName = { targetActivityId, name ->
                        if (targetActivityId == activityId) {
                            activityViewModel.updateSettings(
                                activityId = activityId,
                                name = name,
                                multiCurrency = managementState?.multiCurrencyEnabled ?: false,
                            )
                        }
                    },
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
                    onDeleteParticipant = { targetActivityId, participantId ->
                        if (targetActivityId == activityId) {
                            activityViewModel.deleteParticipant(participantId, activityId)
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
                    onUnarchiveActivity = { targetActivityId ->
                        if (targetActivityId == activityId) {
                            activityViewModel.unarchiveActivity(activityId)
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
            val expenseFormState by expenseViewModel.form.collectAsState()
            val activityIdForDetail = routeActivityId ?: state.detail?.ledgerUnit?.activityId.orEmpty()
            val attachmentLedgerUnitId = routeLedgerUnitId ?: state.detail?.ledgerUnit?.id.orEmpty()
            val activityState by activityViewModel.detail(activityIdForDetail).collectAsState()
            val attachmentViewModel: AttachmentViewModel = viewModel(
                key = "attachments-expense-detail-$activityIdForDetail-$expenseId",
                factory = AttachmentViewModel.Factory(),
            )
            val attachmentState by attachmentViewModel.uiState.collectAsState()
            val attachmentScope = androidx.compose.runtime.rememberCoroutineScope()
            var attachmentMessage by remember { mutableStateOf<String?>(null) }
            var attachmentPreview by remember { mutableStateOf<Pair<String, ByteArray>?>(null) }
            androidx.compose.runtime.LaunchedEffect(expenseId) { expenseViewModel.loadDetail(expenseId) }
            androidx.compose.runtime.LaunchedEffect(expenseId, activityIdForDetail, attachmentLedgerUnitId) {
                if (activityIdForDetail.isNotBlank()) {
                    activityViewModel.loadDetail(activityIdForDetail)
                    if (attachmentLedgerUnitId.isNotBlank()) attachmentViewModel.loadExpense(activityIdForDetail, attachmentLedgerUnitId, expenseId)
                }
            }
            androidx.compose.runtime.LaunchedEffect(expenseId, realtimeState.revisions.expense, realtimeState.revisions.financial) {
                if (realtimeState.activeActivityId == activityIdForDetail &&
                    (realtimeState.revisions.expense > 0L || realtimeState.revisions.financial > 0L)
                ) {
                    expenseViewModel.loadDetail(expenseId, force = true)
                }
            }
            androidx.compose.runtime.LaunchedEffect(expenseId, activityIdForDetail, realtimeState.revisions.activityIdentity, realtimeState.revisions.financial) {
                if (realtimeState.activeActivityId == activityIdForDetail &&
                    (realtimeState.revisions.activityIdentity > 0L || realtimeState.revisions.financial > 0L)
                ) {
                    activityViewModel.loadDetail(activityIdForDetail, force = true)
                }
            }
            androidx.compose.runtime.LaunchedEffect(expenseId, activityIdForDetail, attachmentLedgerUnitId, realtimeState.revisions.attachment) {
                if (realtimeState.revisions.attachment > 0L &&
                    activityIdForDetail.isNotBlank() && attachmentLedgerUnitId.isNotBlank() &&
                    canReloadExternalAttachments(attachmentState)
                ) {
                    attachmentViewModel.loadExpense(activityIdForDetail, attachmentLedgerUnitId, expenseId)
                }
            }
            RefreshActivityOnResume(backStackEntry) {
                expenseViewModel.loadDetail(expenseId, force = true)
                if (activityIdForDetail.isNotBlank()) activityViewModel.loadDetail(activityIdForDetail, force = true)
                if (activityIdForDetail.isNotBlank() && attachmentLedgerUnitId.isNotBlank()) {
                    attachmentViewModel.loadExpense(activityIdForDetail, attachmentLedgerUnitId, expenseId)
                }
            }
            androidx.compose.runtime.LaunchedEffect(activityState.detail) {
                attachmentViewModel.writesEnabled = isActivityWritable(activityState.detail)
            }
            val detail = state.detail
            if (state.isLoading) {
                ExpenseRouteStatus("正在加载账单详情…", onBack = { navController.navigateUp() })
            } else if (state.errorMessage != null || detail == null) {
                ExpenseRouteStatus(state.errorMessage ?: "账单不存在或已被删除", onBack = { navController.navigateUp() })
            } else {
                val activityId = routeActivityId ?: detail.ledgerUnit.activityId
                val ledgerUnitId = routeLedgerUnitId ?: detail.ledgerUnit.id
                val activityWritable = isActivityWritable(activityState.detail)
                ExpenseDetailScreen(
                    uiState = detail.toUiState().copy(
                        actionMessage = state.actionMessage,
                        attachments = attachmentState.toExpenseDetailUiState { item -> canDeleteAttachment(item, activityState.detail, currentUserId) },
                        attachmentMessage = attachmentMessage
                            ?: attachmentState.errorMessage
                            ?: "正在加载附件…".takeIf { attachmentState.isLoading },
                    ),
                    onBack = { navController.navigateUp() },
                    onEdit = if (activityWritable) { { id -> requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId, ExpenseFormRouteMode.EDIT, id))
                    } } } else null,
                    onVoid = if (activityWritable) { { id -> requireParticipantBinding(activityId) { expenseViewModel.delete(id) } } } else null,
                    onRestore = if (activityWritable) { { id -> requireParticipantBinding(activityId) { expenseViewModel.restore(id) } } } else null,
                    onAddRefund = if (activityWritable) { { id -> requireParticipantBinding(activityId) {
                        navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId, ExpenseFormRouteMode.REFUND, id))
                    } } } else null,
                    onRefreshConfirmation = if (
                        expenseFormState.writeState == com.ffocalors.sharedledger.data.expense.ExpenseWriteState.UNKNOWN &&
                        activityId.isNotBlank() && ledgerUnitId.isNotBlank()
                    ) {
                        {
                            expenseViewModel.recoverFromUnknownWrite(activityId, ledgerUnitId, expenseId)
                        }
                    } else null,
                    onAttachmentClick = { _, attachmentId ->
                        attachmentMessage = "正在加载附件…"
                        attachmentScope.launch {
                            attachmentViewModel.downloadReady(attachmentId).fold(
                                onSuccess = { bytes ->
                                    val item = attachmentState.items.firstOrNull { it.clientId == attachmentId }
                                    attachmentPreview = (item?.fileName ?: "附件") to bytes
                                    attachmentMessage = null
                                },
                                onFailure = { attachmentMessage = it.message ?: "附件加载失败" },
                            )
                        }
                    },
                    onAttachmentDelete = if (activityWritable) { { _, attachmentId ->
                        attachmentScope.launch {
                            when (val result = attachmentViewModel.deleteAttachment(attachmentId)) {
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Accepted -> attachmentMessage = null
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.RejectedArchived -> attachmentMessage = result.message
                                is com.ffocalors.sharedledger.ui.attachment.AttachmentWriteResult.Failed -> attachmentMessage = result.message
                                else -> attachmentMessage = "附件删除失败"
                            }
                        }
                    } } else null,
                )
            }
            attachmentPreview?.let { (fileName, bytes) ->
                AttachmentImagePreviewDialog(bytes = bytes, filename = fileName, onDismiss = { attachmentPreview = null })
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
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val ledgerUnitId = backStackEntry.arguments?.getString("ledgerUnitId")
            val transferId = backStackEntry.arguments?.getString("transferId").orEmpty()
            if (activityId.isBlank() || transferId.isBlank()) {
                ExpenseRouteStatus("资金记录路由参数缺失", onBack = { navController.navigateUp() })
            } else {
                val activityDetailState by activityViewModel.detail(activityId).collectAsState()
                val financialWritesEnabled = canPerformFinancialAction(activityDetailState.detail, currentUserId)
                androidx.compose.runtime.LaunchedEffect(activityId) {
                    activityViewModel.loadDetail(activityId)
                }
                androidx.compose.runtime.LaunchedEffect(activityId, realtimeState.revisions.activityIdentity) {
                    if (realtimeState.activeActivityId == activityId && realtimeState.revisions.activityIdentity > 0L) {
                        activityViewModel.loadDetail(activityId, force = true)
                    }
                }
                FinancialRecordDetailRoute(
                    activityId = activityId,
                    transferId = transferId,
                    ledgerUnitId = ledgerUnitId,
                    externalRefreshToken = realtimeState.revisions.financial,
                    writesEnabled = financialWritesEnabled,
                    repository = financialRepository,
                    currentUserId = currentUserId,
                    onBack = { navController.navigateUp() },
                    onRefreshActivity = {
                        activityViewModel.loadDetail(activityId, force = true)
                        activityViewModel.refreshHome()
                    },
                    onRecreateCorrectRecord = {
                        navController.navigate(SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER, ledgerUnitId))
                    },
                )
            }
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
            val activityDetailState by activityViewModel.detail(activityId).collectAsState()
            val financialWritesEnabled = canPerformFinancialAction(activityDetailState.detail, currentUserId)
            var context by remember(activityId) { mutableStateOf<FinancialContext?>(null) }
            var loading by remember(activityId) { mutableStateOf(true) }
            var submitting by remember(activityId) { mutableStateOf(false) }
            var error by remember(activityId) { mutableStateOf<String?>(null) }
            var reload by remember(activityId) { mutableStateOf(0) }
            val scope = androidx.compose.runtime.rememberCoroutineScope()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                if (activityId.isNotBlank()) activityViewModel.loadDetail(activityId)
            }
            RefreshActivityOnResume(backStackEntry) { reload++ }
            androidx.compose.runtime.LaunchedEffect(activityId, reload, realtimeState.revisions.financial) {
                if (activityId.isBlank()) {
                    loading = false
                    return@LaunchedEffect
                }
                loading = true
                error = null
                when (val result = financialRepository.loadPrepaymentContext(activityId)) {
                    is FinancialReadResult.Success -> context = result.value
                    is FinancialReadResult.Failure -> error = result.message
                }
                loading = false
            }
            if (activityId.isBlank()) {
                ExpenseRouteStatus("活动路由参数缺失", onBack = { navController.navigateUp() })
            } else if (activityDetailState.isLoading) {
                ExpenseRouteStatus("正在验证活动权限…", onBack = { navController.navigateUp() })
            } else if (activityDetailState.errorMessage != null) {
                ExpenseRouteStatus(activityDetailState.errorMessage ?: "活动详情加载失败", onBack = { navController.navigateUp() })
            } else if (!financialWritesEnabled) {
                ExpenseRouteStatus("活动已归档或当前成员无权执行预存操作", onBack = { navController.navigateUp() })
            } else {
                PrepaymentScreen(
                    mode = mode,
                    context = context,
                    isLoading = loading,
                    isSubmitting = submitting,
                    errorMessage = error,
                    onRetry = { reload++ },
                    onBack = { navController.navigateUp() },
                    onSubmit = { ownerId, custodianId, amount, onBehalfOfParticipantId ->
                    val endpointIds = setOf(ownerId, custodianId)
                    val contextValue = context
                    val currentIsParty = contextValue?.currentParticipantId in endpointIds
                    val validOnBehalf = contextValue != null && when {
                        onBehalfOfParticipantId == null -> currentIsParty
                        else -> contextValue.canActOnBehalf &&
                            onBehalfOfParticipantId in endpointIds &&
                            contextValue.unclaimedParticipants.any { it.participantId == onBehalfOfParticipantId }
                    }
                    if (ownerId == custodianId) {
                        error = "预存所有者和保管人不能是同一位参与人"
                    } else if (!validOnBehalf) {
                        error = "请选择有效的代记参与人"
                    } else if (!submitting) {
                        submitting = true
                        error = null
                        val input = PrepaymentInput(activityId, ownerId, custodianId, amount, Instant.now().toString(), onBehalfOfParticipantId)
                        scope.launch {
                            val result = if (mode == PrepaymentMode.FUND) financialRepository.createPrepayment(input) else financialRepository.createPrepaymentReturn(input)
                            submitting = false
                            if (result.isSuccess) {
                                activityViewModel.loadDetail(activityId, force = true)
                                activityViewModel.refreshHome()
                                navController.navigate(SharedLedgerRoutes.transferDetail(activityId, result.value!!.transferId)) {
                                    popUpTo(SharedLedgerRoutes.PREPAYMENT_PATTERN) { inclusive = true }
                                }
                            } else if (result.isCommitted && result.committedOperationId != null) {
                                activityViewModel.loadDetail(activityId, force = true)
                                activityViewModel.refreshHome()
                                navController.navigate(SharedLedgerRoutes.transferDetail(activityId, result.committedOperationId)) {
                                    popUpTo(SharedLedgerRoutes.PREPAYMENT_PATTERN) { inclusive = true }
                                }
                            } else {
                                error = result.errorMessage
                            }
                        }
                    }
                    },
                )
            }
        }
        composable(
            route = SharedLedgerRoutes.FINAL_SETTLEMENT_PATTERN,
            arguments = listOf(navArgument("activityId") { type = NavType.StringType }),
        ) { backStackEntry ->
            val activityId = backStackEntry.arguments?.getString("activityId").orEmpty()
            val activityDetailState by activityViewModel.detail(activityId).collectAsState()
            val financialWritesEnabled = canPerformFinancialAction(activityDetailState.detail, currentUserId)
            var suggestions by remember(activityId) { mutableStateOf<List<FinalSettlementSuggestionUi>>(emptyList()) }
            var loading by remember(activityId) { mutableStateOf(true) }
            var error by remember(activityId) { mutableStateOf<String?>(null) }
            var submitting by remember(activityId) { mutableStateOf(false) }
            var financialContext by remember(activityId) { mutableStateOf<FinancialContext?>(null) }
            var refreshToken by remember(activityId) { mutableStateOf(0) }
            val scope = androidx.compose.runtime.rememberCoroutineScope()
            androidx.compose.runtime.LaunchedEffect(activityId) {
                if (activityId.isNotBlank()) activityViewModel.loadDetail(activityId)
            }
            androidx.compose.runtime.LaunchedEffect(activityId, refreshToken, realtimeState.revisions.financial) {
                if (activityId.isBlank()) {
                    loading = false
                    return@LaunchedEffect
                }
                loading = true
                error = null
                when (val contextResult = financialRepository.loadPrepaymentContext(activityId)) {
                    is FinancialReadResult.Success -> financialContext = contextResult.value
                    is FinancialReadResult.Failure -> {
                        error = contextResult.message
                        loading = false
                        return@LaunchedEffect
                    }
                }
                val context = financialContext
                when (val result = financialRepository.previewFinalSettlement(activityId)) {
                    is FinancialReadResult.Success -> suggestions = result.value.map { item ->
                        val onBehalfOptions = if (context?.canActOnBehalf == true) {
                            listOf(item.from, item.to).distinctBy { it.participantId }
                                .filter { participant -> context.unclaimedParticipants.any { it.participantId == participant.participantId } }
                                .map { participant -> FinalSettlementParticipantOption(participant.participantId, participant.displayName) }
                        } else emptyList()
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
                            onBehalfOptions = onBehalfOptions,
                            onBehalfRequired = context?.canActOnBehalf == true &&
                                context.currentParticipantId !in listOf(item.from.participantId, item.to.participantId),
                        )
                    }
                    is FinancialReadResult.Failure -> error = result.message
                }
                loading = false
            }
            if (activityId.isBlank()) {
                ExpenseRouteStatus("活动路由参数缺失", onBack = { navController.navigateUp() })
            } else if (activityDetailState.isLoading) {
                ExpenseRouteStatus("正在验证活动权限…", onBack = { navController.navigateUp() })
            } else if (activityDetailState.errorMessage != null) {
                ExpenseRouteStatus(activityDetailState.errorMessage ?: "活动详情加载失败", onBack = { navController.navigateUp() })
            } else if (!financialWritesEnabled) {
                ExpenseRouteStatus("活动已归档或当前成员无权执行最终结算", onBack = { navController.navigateUp() })
            } else {
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
                        } else if (item.onBehalfRequired && request.onBehalfOfParticipantId == null) {
                            error = "请选择代记参与人后再执行结算。"
                        } else if (request.onBehalfOfParticipantId != null &&
                            item.onBehalfOptions.none { it.participantId == request.onBehalfOfParticipantId }) {
                            error = "请选择有效的代记参与人后再执行结算。"
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
                                    onBehalfOfParticipantId = request.onBehalfOfParticipantId,
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
                                } else if (written.isCommitted && written.committedOperationId != null) {
                                    activityViewModel.loadDetail(activityId, force = true)
                                    activityViewModel.refreshHome()
                                    navController.navigate(SharedLedgerRoutes.transferDetail(activityId, written.committedOperationId)) {
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
}

internal fun canReloadExternalAttachments(state: AttachmentUiState): Boolean =
    !state.isWriting && state.items.none { item ->
        item.bytes != null || item.pendingUpload != null || item.deleteRecovery != null
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
    externalRefreshToken: Long = 0L,
    writesEnabled: Boolean,
    repository: FinancialRecordRepository,
    currentUserId: String,
    onBack: () -> Unit,
    onRefreshActivity: () -> Unit,
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

    fun handleFinancialActionResult(result: FinancialWriteResult<*>) {
        actionError = result.errorMessage
        if (result.isSuccess || result.isCommitted || result.isUnknown) refreshToken++
    }

    androidx.compose.runtime.LaunchedEffect(activityId, transferId, repository, refreshToken, externalRefreshToken) {
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
                onAddDispute = if (writesEnabled) { { _, note ->
                    if (currentParticipantId == null) {
                        actionError = "当前用户不是这笔记录的交易双方"
                    } else if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.addDispute(activityId, transferId, currentParticipantId!!, note)
                            isSubmitting = false
                            handleFinancialActionResult(result)
                        }
                    }
                } } else null,
                onResolveDispute = if (writesEnabled) { { disputeId ->
                    if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.resolveDispute(activityId, disputeId)
                            isSubmitting = false
                            handleFinancialActionResult(result)
                        }
                    }
                } } else null,
                onVoid = if (writesEnabled) { { _, reason ->
                    if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.void(activityId, transferId, reason)
                            isSubmitting = false
                            handleFinancialActionResult(result)
                        }
                    }
                } } else null,
                onRestore = if (writesEnabled) { { _, reason ->
                    if (!isSubmitting) {
                        isSubmitting = true
                        scope.launch {
                            val result = repository.restore(activityId, transferId, reason)
                            isSubmitting = false
                            if (result.isSuccess || result.isCommitted) onRefreshActivity()
                            handleFinancialActionResult(result)
                        }
                    }
                } } else null,
                onRecreateCorrectRecord = if (writesEnabled) { { _: String -> onRecreateCorrectRecord() } } else null,
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

internal fun canPerformFinancialAction(
    detail: com.ffocalors.sharedledger.data.activity.ActivityDetail?,
    currentUserId: String,
): Boolean = detail?.let { activity ->
    activity.summary.archivedAt == null && (
        activity.summary.createdBy == currentUserId ||
            activity.members.any { member ->
                member.userId == currentUserId && member.claimedParticipantId != null
            }
        )
} == true

internal fun isActivityWritable(
    detail: com.ffocalors.sharedledger.data.activity.ActivityDetail?,
): Boolean = detail != null && detail.summary.archivedAt == null

private fun canDeleteAttachment(
    item: AttachmentClientItem,
    detail: com.ffocalors.sharedledger.data.activity.ActivityDetail?,
    currentUserId: String,
): Boolean = item.metadata == null ||
    item.metadata.uploadedBy == currentUserId ||
    detail?.summary?.createdBy == currentUserId
