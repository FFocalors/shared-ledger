package com.ffocalors.sharedledger.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import com.ffocalors.sharedledger.BuildConfig
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
    val navController = rememberNavController()
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
    var authError by rememberSaveable { mutableStateOf<String?>(null) }

    NavHost(
        navController = navController,
        startDestination = SharedLedgerRoutes.START_DESTINATION,
        modifier = modifier,
    ) {
        composable(SharedLedgerRoutes.AUTH) {
            AuthScreen(
                errorMessage = authError,
                showDemoCredentials = BuildConfig.DEBUG,
                showDemoRegistrationNotice = BuildConfig.DEBUG,
                onLogin = { email, password ->
                    if (DemoAdminCredentials.matches(email, password)) {
                        authError = null
                        val navigation = SharedLedgerRoutes.authSuccessNavigation()
                        navController.navigate(navigation.destination) {
                            popUpTo(navigation.popUpTo) { inclusive = navigation.inclusive }
                            launchSingleTop = navigation.launchSingleTop
                        }
                    } else {
                        authError = if (BuildConfig.DEBUG) {
                            "登录失败：请输入 Debug 演示管理员账号和密码"
                        } else {
                            "登录失败：当前版本未配置后端认证服务"
                        }
                    }
                },
                onRegister = { _, _, _ ->
                    if (BuildConfig.DEBUG) {
                        authError = null
                        val navigation = SharedLedgerRoutes.authSuccessNavigation()
                        navController.navigate(navigation.destination) {
                            popUpTo(navigation.popUpTo) { inclusive = navigation.inclusive }
                            launchSingleTop = navigation.launchSingleTop
                        }
                    } else {
                        authError = "注册失败：当前版本未配置后端注册服务"
                    }
                },
                onForgotPassword = { email ->
                    authError = if (email.isBlank()) {
                        "请输入邮箱后再申请重置密码"
                    } else {
                        "演示：已记录密码重置请求（$email）"
                    }
                },
            )
        }
        composable(SharedLedgerRoutes.HOME) {
            HomeScreen(
                onActivityClick = { activity ->
                    val destination = when (activity.kind) {
                        ActivityKind.Large -> SharedLedgerRoutes.largeActivity(activity.activityId)
                        ActivityKind.Standard -> SharedLedgerRoutes.normalActivity(activity.activityId)
                    }
                    navController.navigate(destination)
                },
                onCreateActivity = { navController.navigate(SharedLedgerRoutes.CREATE_ACTIVITY) },
                onJoinActivity = { navController.navigate(SharedLedgerRoutes.JOIN_ACTIVITY) },
            )
        }
        composable(SharedLedgerRoutes.JOIN_ACTIVITY) {
            var joinState by remember { mutableStateOf(JoinActivityUiState()) }
            JoinActivityScreen(
                state = joinState,
                onBackClick = { navController.navigateUp() },
                onInviteCodeChange = { value ->
                    joinState = joinState.copy(inviteCode = value.filter(Char::isDigit).take(8))
                },
                onValidateInviteCode = { code ->
                    joinState = joinState.copy(
                        inviteCode = code,
                        status = if (code.length == 8) JoinActivityStatus.ReadyToJoin
                        else JoinActivityStatus.InvalidCode,
                    )
                },
                onParticipantSelected = { participantId ->
                    val selected = joinState.preview.participants.firstOrNull { it.participantId == participantId }
                    joinState = joinState.copy(
                        selectedParticipantId = participantId,
                        selectedParticipantName = selected?.name,
                    )
                },
                onJoinActivity = { participantId ->
                    if (participantId.isNotBlank()) {
                        joinState = joinState.copy(status = JoinActivityStatus.Joined)
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
            LargeActivityScreen(
                onBack = { navController.navigateUp() },
                onSubActivityClick = { id ->
                    navController.navigate(SharedLedgerRoutes.ledgerUnit(activityId, id))
                },
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
        ) {
            CreateSubActivityScreen(
                parentActivityName = "日本旅行",
                onBack = { navController.navigateUp() },
                onCreate = { navController.navigateUp() },
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
            LedgerUnitScreen(
                activityId = activityId,
                ledgerUnitId = ledgerUnitId,
                onBack = { navController.navigateUp() },
                onTransfer = {
                    navController.navigate(
                        SharedLedgerRoutes.transfer(activityId, TransferRouteMode.TRANSFER, ledgerUnitId),
                    )
                },
                onNewExpense = {
                    navController.navigate(SharedLedgerRoutes.newExpense(activityId, ledgerUnitId))
                },
                onReceive = {
                    navController.navigate(
                        SharedLedgerRoutes.transfer(activityId, TransferRouteMode.RECEIVE, ledgerUnitId),
                    )
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
            ActivityManagementScreen(
                activityId = activityId,
                onBackClick = { navController.navigateUp() },
                onArchiveActivity = { targetActivityId ->
                    if (targetActivityId == activityId) navController.navigateUp()
                },
                onLeaveActivity = { targetActivityId ->
                    if (targetActivityId == activityId) navController.navigateUp()
                },
                onDeleteActivity = { targetActivityId ->
                    if (targetActivityId == activityId) navController.navigateUp()
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
