package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Archive
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.DataUsage
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.DeleteForever
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.Savings
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonVariant
import com.ffocalors.sharedledger.ui.components.SharedLedgerDialog
import com.ffocalors.sharedledger.ui.components.SharedLedgerSnackbarHost
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.isTerminalActivityError
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.AppSurfaceLow
import com.ffocalors.sharedledger.ui.theme.AppSurfaceVariant
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter

private val StitchSurfaceContainer = Color(0xFFEFEDED)

/** The state shown by the activity-management screen. The host owns this state. */
@Immutable
data class ActivityManagementUiState(
    val activityName: String = "",
    val activityType: String = "",
    val baseCurrency: String = "",
    val multiCurrencyEnabled: Boolean = false,
    val joinCode: String = "",
    val participantListLocked: Boolean = false,
    val participantListLockMessage: String = "",
    val participants: List<ActivityManagementParticipant> = emptyList(),
    val members: List<ActivityManagementMember> = emptyList(),
    val deletedSubActivities: List<ActivityManagementDeletedSubActivity> = emptyList(),
    val permissionSummary: String = "",
    val status: ActivityManagementStatus = ActivityManagementStatus.InProgress,
    val outstandingDebt: String = "",
    val hasOutstandingDebt: Boolean = false,
    val remainingPrepayment: String = "",
    val showInviteEntry: Boolean = false,
    val showSettings: Boolean = false,
    val showLeaveAction: Boolean = false,
    val showDeleteAction: Boolean = false,
    /** The original Stitch screen exposes an ownership action; it must target a non-creator row. */
    val showTransferOwnershipAction: Boolean = false,
    val currentUserName: String = "",
    val currentUserParticipantId: String? = null,
    val currentUserParticipantName: String? = null,
    val canManageParticipants: Boolean = false,
    val canManageMembers: Boolean = false,
    val canArchiveActivity: Boolean = false,
    val canUnarchiveActivity: Boolean = false,
    val canBindParticipant: Boolean = false,
    val canUnbindParticipant: Boolean = false,
)

@Immutable
data class ActivityManagementDeletedSubActivity(
    val name: String,
    val ledgerUnitId: String,
    val deletedAt: String? = null,
)

@Immutable
data class ActivityManagementParticipant(
    val name: String,
    val initial: String = name.take(1),
    val isBound: Boolean,
    val participantId: String = "",
    val boundUserName: String? = null,
    val boundUserId: String? = null,
    val isBoundToCurrentUser: Boolean = false,
    val avatarStyle: String? = null,
)

@Immutable
data class ActivityManagementMember(
    val name: String,
    val initial: String = name.take(1),
    val role: String = "用户",
    val detail: String = "未绑定参与人",
    val isCreator: Boolean = false,
    val canRemove: Boolean = !isCreator,
    val memberId: String = "",
    val avatarStyle: String? = null,
)

/** Ownership can only be transferred to a named, non-creator member. */
internal fun ownershipTransferTargetId(member: ActivityManagementMember): String? =
    member.memberId.takeIf { it.isNotBlank() && !member.isCreator }

enum class ActivityManagementStatus(val label: String) {
    InProgress("进行中"),
    Settled("已结清"),
    Archived("已归档"),
}

/**
 * Activity settings and lifecycle actions are exposed as independent callbacks so this
 * screen can be used with either a local state holder or a repository-backed screen.
 */
@Composable
fun ActivityManagementScreen(
    activityId: String = "",
    modifier: Modifier = Modifier,
    state: ActivityManagementUiState = ActivityManagementUiState(),
    isLoading: Boolean = false,
    actionInProgress: Boolean = false,
    errorMessage: String? = null,
    focusParticipants: Boolean = false,
    message: String? = null,
    onMessageShown: () -> Unit = {},
    onRetry: () -> Unit = {},
    onBackClick: () -> Unit = {},
    onMoreClick: ((String) -> Unit)? = null,
    onCopyJoinCode: (String, String) -> Unit = { _, _ -> },
    onUpdateActivityName: ((String, String) -> Unit)? = null,
    onCreateParticipant: (String, String) -> Unit = { _, _ -> },
    onDeleteParticipant: ((String, String) -> Unit)? = null,
    onBindParticipant: (String, String) -> Unit = { _, _ -> },
    onUnbindParticipant: (String) -> Unit = {},
    onMultiCurrencyChange: (String, Boolean) -> Unit = { _, _ -> },
    onTransferOwnership: (String, String) -> Unit = { _, _ -> },
    onRemoveMember: (String, String) -> Unit = { _, _ -> },
    onArchiveActivity: (String) -> Unit = {},
    onUnarchiveActivity: (String) -> Unit = {},
    onLeaveActivity: (String) -> Unit = {},
    onDeleteActivity: (String) -> Unit = {},
    onRestoreSubActivity: (String, String) -> Unit = { _, _ -> },
) {
    var pendingConfirmation by rememberSaveable { mutableStateOf<ManagementConfirmation?>(null) }
    var pendingParticipantId by rememberSaveable { mutableStateOf<String?>(null) }
    var showEditActivityDialog by rememberSaveable { mutableStateOf(false) }
    var activityNameDraft by rememberSaveable(state.activityName) { mutableStateOf(state.activityName) }
    var actionMessage by rememberSaveable { mutableStateOf<String?>(null) }
    val snackbarHostState = remember { SnackbarHostState() }
    val scrollState = rememberScrollState()
    var participantFocusConsumed by rememberSaveable { mutableStateOf(false) }
    var viewportTop by remember { mutableStateOf<Float?>(null) }
    var participantCardTop by remember { mutableStateOf<Float?>(null) }
    val density = LocalDensity.current

    LaunchedEffect(actionMessage) {
        actionMessage?.let { message ->
            snackbarHostState.showSnackbar(message)
            actionMessage = null
        }
    }

    LaunchedEffect(message) {
        message?.let {
            snackbarHostState.showSnackbar(it)
            onMessageShown()
        }
    }

    fun runAction(message: String, action: () -> Unit) {
        action()
        actionMessage = message
    }
    val hazeState = rememberSharedLedgerHazeState()

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        snackbarHost = { SharedLedgerSnackbarHost(snackbarHostState) },
        topBar = {
            SharedLedgerTopBar(
                title = "SharedLedger",
                showBackButton = true,
                onBackClick = onBackClick,
                onMoreClick = onMoreClick?.let { callback -> { callback(activityId) } },
                titleStyle = SharedLedgerTextStyles.PageTitle,
                titleColor = MaterialTheme.colorScheme.primary,
                moreButtonContainerColor = StitchSurfaceContainer,
                containerColor = AppBackground,
                hazeState = hazeState,
            )
        },
    ) { innerPadding ->
        val focusTopOffsetPx = with(density) { (innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium).toPx() }
        LaunchedEffect(focusParticipants, participantFocusConsumed, isLoading, errorMessage, viewportTop != null, participantCardTop != null) {
            if (!focusParticipants || participantFocusConsumed || isLoading || errorMessage != null) return@LaunchedEffect
            if (viewportTop == null || participantCardTop == null) return@LaunchedEffect
            withFrameNanos { }
            val cardTop = participantCardTop ?: return@LaunchedEffect
            val top = viewportTop ?: return@LaunchedEffect
            val target = (scrollState.value + (cardTop - top) - focusTopOffsetPx).toInt().coerceIn(0, scrollState.maxValue)
            if (target != scrollState.value) scrollState.animateScrollTo(target)
            participantFocusConsumed = true
        }
        Box(
            modifier = Modifier
                .fillMaxSize()
                .onGloballyPositioned { viewportTop = it.positionInRoot().y },
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .sharedLedgerHazeSource(hazeState)
                    .verticalScroll(scrollState)
                    .padding(
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.MediumLarge,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.XLarge,
                    ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
            ) {
                ActivityManagementPageTitle()
                if (state.currentUserName.isNotBlank() && state.currentUserParticipantId == null) {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = SharedLedgerRadius.Medium,
                        color = MaterialTheme.colorScheme.secondaryContainer,
                        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                    ) {
                        Text(
                            text = "当前用户“${state.currentUserName}”尚未绑定参与人。请在下方选择自己的参与人；绑定后才能记账、转账或收款。",
                            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                            style = SharedLedgerTextStyles.BodySecondary,
                        )
                    }
                } else if (state.currentUserParticipantName != null) {
                    Text(
                        text = "当前绑定参与人：${state.currentUserParticipantName}",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                BasicInfoCard(
                    state = state,
                    onCopyJoinCode = {
                            runAction("加入码已复制") {
                            onCopyJoinCode(activityId, state.joinCode)
                        }
                    },
                )
                ParticipantManagementCard(
                    modifier = Modifier.onGloballyPositioned { participantCardTop = it.positionInRoot().y },
                    state = state,
                    onCreateParticipant = { name -> onCreateParticipant(activityId, name) },
                    onDeleteParticipant = onDeleteParticipant?.let { callback ->
                        { participantId -> pendingParticipantId = participantId; pendingConfirmation = ManagementConfirmation.DeleteParticipant }
                    },
                    onBindParticipant = { participantId ->
                        onBindParticipant(activityId, participantId)
                    },
                    onUnbindParticipant = {
                        onUnbindParticipant(activityId)
                    },
                )
                ActivityMembersCard(
                    members = state.members,
                    canManageMembers = state.canManageMembers,
                    showTransferOwnershipAction = state.showTransferOwnershipAction,
                    onTransferOwnership = { memberId ->
                        onTransferOwnership(activityId, memberId)
                    },
                    onRemoveMember = { memberId ->
                        onRemoveMember(activityId, memberId)
                    },
                )
                DeletedSubActivitiesCard(
                    items = state.deletedSubActivities,
                    onRestore = { ledgerUnitId -> onRestoreSubActivity(activityId, ledgerUnitId) },
                )
                if (state.showSettings) {
                    ActivitySettingsCard(
                        state = state,
                        onEditActivity = onUpdateActivityName?.let {
                            { showEditActivityDialog = true; activityNameDraft = state.activityName }
                        },
                        onMultiCurrencyChange = { enabled ->
                            onMultiCurrencyChange(activityId, enabled)
                        },
                    )
                }
                ActivityStatusCard(
                    state = state,
                    onArchiveClick = if (state.canArchiveActivity) {
                        { pendingConfirmation = ManagementConfirmation.Archive }
                    } else {
                        null
                    },
                    onUnarchiveClick = if (state.canUnarchiveActivity) {
                        { pendingConfirmation = ManagementConfirmation.Unarchive }
                    } else {
                        null
                    },
                )
                DangerZone(
                    showLeaveAction = state.showLeaveAction,
                    showDeleteAction = state.showDeleteAction,
                    onLeaveClick = { pendingConfirmation = ManagementConfirmation.Leave },
                    onDeleteClick = { pendingConfirmation = ManagementConfirmation.Delete },
                )
            }
            if (actionInProgress && !isLoading && errorMessage == null) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .pointerInput(Unit) { detectTapGestures { } },
                )
                LinearProgressIndicator(
                    modifier = Modifier
                        .fillMaxWidth()
                        .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                        .padding(top = innerPadding.calculateTopPadding()),
                )
            }
            if (isLoading || errorMessage != null) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = AppBackground,
                ) {
                    if (isLoading) {
                        LoadingState(
                            message = "正在加载活动信息…",
                            modifier = Modifier.fillMaxSize(),
                        )
                    } else {
                        ErrorState(
                            message = errorMessage ?: "活动信息加载失败",
                            onRetry = if (isTerminalActivityError(errorMessage)) null else onRetry,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
            }
        }
    }

    pendingConfirmation?.let { confirmation ->
        ManagementConfirmationDialog(
            confirmation = confirmation,
            onDismiss = { pendingConfirmation = null },
            onConfirm = {
                pendingConfirmation = null
                when (confirmation) {
                    ManagementConfirmation.Archive -> onArchiveActivity(activityId)
                    ManagementConfirmation.Unarchive -> onUnarchiveActivity(activityId)
                    ManagementConfirmation.Leave -> onLeaveActivity(activityId)
                    ManagementConfirmation.Delete -> onDeleteActivity(activityId)
                    ManagementConfirmation.DeleteParticipant -> {
                        val participantId = pendingParticipantId
                        pendingParticipantId = null
                        if (participantId != null && onDeleteParticipant != null) {
                            onDeleteParticipant(activityId, participantId)
                        }
                    }
                }
            },
        )
    }

    if (showEditActivityDialog && onUpdateActivityName != null) {
        SharedLedgerDialog(
            onDismiss = { showEditActivityDialog = false },
            title = "编辑活动资料",
            textContent = {
                SharedLedgerTextField(
                    value = activityNameDraft,
                    onValueChange = { activityNameDraft = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = "活动名称",
                )
            },
            dismissText = "取消",
            confirmText = "保存",
            confirmEnabled = activityNameDraft.trim().isNotBlank(),
            onConfirm = {
                val name = activityNameDraft.trim()
                if (name.isNotBlank()) {
                    onUpdateActivityName(activityId, name)
                    showEditActivityDialog = false
                }
            },
        )
    }
}

private enum class ManagementConfirmation {
    Archive,
    Unarchive,
    Leave,
    Delete,
    DeleteParticipant,
}

@Composable
private fun ManagementConfirmationDialog(
    confirmation: ManagementConfirmation,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    val (title, message, confirmLabel) = when (confirmation) {
        ManagementConfirmation.Archive -> Triple(
            "归档活动？",
            "归档后活动将变为只读状态，无法再添加新账单。确定继续吗？",
            "归档活动",
        )
        ManagementConfirmation.Unarchive -> Triple(
            "取消归档活动？",
            "取消归档后将恢复活动写入口；已有账务数据和参与人名单保持不变。确定继续吗？",
            "取消归档",
        )
        ManagementConfirmation.Leave -> Triple(
            "退出活动？",
            "退出后您将无法继续记录或查看此活动中的新变化。确定退出吗？",
            "退出活动",
        )
        ManagementConfirmation.Delete -> Triple(
            "删除活动？",
            "删除后活动将从正常列表中移除，相关历史记录仍由系统保留。此操作不可撤销。",
            "删除活动",
        )
        ManagementConfirmation.DeleteParticipant -> Triple(
            "删除参与人？",
            "删除后将无法再使用该参与人记录新的账单。若参与人已绑定或已有账务事实，服务端会拒绝此操作。确定继续吗？",
            "删除参与人",
        )
    }
    SharedLedgerDialog(
        onDismiss = onDismiss,
        title = title,
        text = message,
        dismissText = "取消",
        confirmText = confirmLabel,
        destructive = confirmation == ManagementConfirmation.Delete ||
            confirmation == ManagementConfirmation.DeleteParticipant,
        onConfirm = onConfirm,
    )
}

@Preview(name = "活动管理", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun ActivityManagementScreenPreview() {
    SharedLedgerTheme {
        ActivityManagementScreen(
            activityId = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.NORMAL_ACTIVITY,
            state = ActivityManagementUiState(
                activityName = "周末露营计划",
                activityType = "旅行",
                baseCurrency = "CNY (¥)",
                multiCurrencyEnabled = true,
                joinCode = "5831 2746",
                participantListLockMessage = "参与人名单已锁定 (已产生正式账单)",
                participants = listOf(
                    ActivityManagementParticipant("Participant 1", "A", isBound = true, participantId = "demo-participant-1"),
                    ActivityManagementParticipant("Participant 2", "B", isBound = false, participantId = "demo-participant-2"),
                ),
                members = listOf(
                    ActivityManagementMember("Alice", "A", "创建者", "绑定参与人: Participant 1", true, memberId = "demo-member-alice"),
                    ActivityManagementMember("Charlie", "C", "用户", "未绑定参与人", memberId = "demo-member-charlie"),
                ),
                permissionSummary = "创建者可管理",
                outstandingDebt = "¥ 350.00",
                hasOutstandingDebt = true,
                remainingPrepayment = "¥ 0.00",
                showDeleteAction = true,
                showTransferOwnershipAction = true,
                canManageParticipants = true,
                canManageMembers = true,
                canArchiveActivity = true,
                canUnbindParticipant = true,
            ),
        )
    }
}
