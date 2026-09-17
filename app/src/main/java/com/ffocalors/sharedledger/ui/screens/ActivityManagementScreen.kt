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
import androidx.compose.material3.SnackbarHost
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
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
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter

private val StitchSurfaceContainer = Color(0xFFEFEDED)
private val StitchSurfaceContainerHigh = Color(0xFFEAE8E7)

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
    val isBoundToCurrentUser: Boolean = false,
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
        snackbarHost = { SnackbarHost(snackbarHostState) },
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
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .sharedLedgerHazeSource(hazeState)
                    .verticalScroll(rememberScrollState())
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

@Composable
private fun DeletedSubActivitiesCard(
    items: List<ActivityManagementDeletedSubActivity>,
    onRestore: (String) -> Unit,
) {
    if (items.isEmpty()) return
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        color = AppSurface,
        tonalElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Text("已删除子活动", style = SharedLedgerTextStyles.SectionTitle)
            Text(
                "删除后账单和附件会隐藏，账务已重算；恢复后可继续查看。",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            items.forEach { item ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(item.name, style = SharedLedgerTextStyles.BodySecondary)
                        item.deletedAt?.let { timestamp ->
                            Text("已删除 ${UiDateTimeFormatter.format(timestamp)}", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    TextButton(onClick = { onRestore(item.ledgerUnitId) }) { Text("恢复") }
                }
            }
        }
    }
}

@Composable
private fun ActivityManagementPageTitle() {
    Column(
        modifier = Modifier.padding(bottom = SharedLedgerSpacing.XSmall),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
    ) {
        Text(
            text = "活动管理",
            style = SharedLedgerTextStyles.PageTitle,
            color = MaterialTheme.colorScheme.onBackground,
            modifier = Modifier.semantics { heading() },
        )
        Text(
            text = "管理您的活动详情、用户及状态。",
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BasicInfoCard(
    state: ActivityManagementUiState,
    onCopyJoinCode: () -> Unit,
) {
    ManagementCard {
        CardHeader(icon = Icons.Rounded.Info, title = "基本信息")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            InfoCell(label = "活动名称", value = state.activityName, modifier = Modifier.weight(1f))
            InfoCell(
                label = "类型",
                value = state.activityType,
                leadingIcon = Icons.Rounded.FlightTakeoff,
                modifier = Modifier.weight(1f),
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            InfoCell(label = "基础币种", value = state.baseCurrency, modifier = Modifier.weight(1f))
            InfoCell(
                label = "多币种状态",
                value = if (state.multiCurrencyEnabled) "已开启" else "已关闭",
                modifier = Modifier.weight(1f),
            )
        }
        JoinCodeRow(
            joinCode = state.joinCode,
            onCopyClick = onCopyJoinCode,
        )
    }
}

@Composable
private fun JoinCodeRow(
    joinCode: String,
    onCopyClick: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Small,
        color = StitchSurfaceContainer,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)),
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "加入码",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = joinCode,
                    style = SharedLedgerTextStyles.CardTitle,
                    color = MaterialTheme.colorScheme.primary,
                    letterSpacing = 2.sp,
                )
            }
            IconButton(
                onClick = onCopyClick,
                modifier = Modifier.semantics {
                    contentDescription = "复制加入码 $joinCode"
                },
            ) {
                Icon(
                    imageVector = Icons.Rounded.ContentCopy,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun ParticipantManagementCard(
    state: ActivityManagementUiState,
    onCreateParticipant: (String) -> Unit,
    onDeleteParticipant: ((String) -> Unit)?,
    onBindParticipant: (String) -> Unit,
    onUnbindParticipant: () -> Unit,
) {
    var showCreateDialog by rememberSaveable { mutableStateOf(false) }
    var participantName by rememberSaveable { mutableStateOf("") }
    ManagementCard {
        if (state.participantListLocked) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = SharedLedgerRadius.Small,
                color = AppSurfaceLow,
            ) {
                Row(
                    modifier = Modifier.padding(
                        horizontal = SharedLedgerSpacing.Medium,
                        vertical = SharedLedgerSpacing.Small,
                    ),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Lock,
                        contentDescription = null,
                        modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = state.participantListLockMessage,
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(modifier = Modifier.weight(1f)) {
                CardHeader(icon = Icons.Rounded.Group, title = "参与人管理")
            }
            if (state.canManageParticipants && !state.participantListLocked) {
                TextButton(onClick = { showCreateDialog = true }) {
                    Text("添加参与人", style = SharedLedgerTextStyles.Label)
                }
            }
        }
        Column(modifier = Modifier.fillMaxWidth()) {
            state.participants.forEachIndexed { index, participant ->
                ParticipantManagementRow(
                    participant = participant,
                    index = index,
                    showDivider = index < state.participants.lastIndex,
                    canBindParticipant = state.canBindParticipant,
                    canUnbindParticipant = state.canUnbindParticipant,
                    canDeleteParticipant = state.canManageParticipants &&
                        !state.participantListLocked && !participant.isBound && onDeleteParticipant != null,
                    onBindParticipant = onBindParticipant,
                    onDeleteParticipant = { onDeleteParticipant?.invoke(participant.participantId) },
                    onUnbindParticipant = onUnbindParticipant,
                )
            }
        }
    }
    if (showCreateDialog) {
        SharedLedgerDialog(
            onDismiss = { showCreateDialog = false },
            title = "添加参与人",
            textContent = {
                SharedLedgerTextField(
                    value = participantName,
                    onValueChange = { participantName = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = "请输入姓名",
                )
            },
            dismissText = "取消",
            confirmText = "添加",
            confirmEnabled = participantName.isNotBlank(),
            onConfirm = {
                val name = participantName.trim()
                if (name.isNotBlank() && state.canManageParticipants && !state.participantListLocked) {
                    onCreateParticipant(name)
                    participantName = ""
                    showCreateDialog = false
                }
            },
        )
    }
}

@Composable
private fun ParticipantManagementRow(
    participant: ActivityManagementParticipant,
    index: Int,
    showDivider: Boolean,
    canBindParticipant: Boolean,
    canUnbindParticipant: Boolean,
    canDeleteParticipant: Boolean,
    onBindParticipant: (String) -> Unit,
    onDeleteParticipant: () -> Unit,
    onUnbindParticipant: () -> Unit,
) {
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            ParticipantAvatar(
                name = participant.initial,
                backgroundColor = if (index % 2 == 0) {
                    WarmOrangeContainer
                } else {
                    MaterialTheme.colorScheme.tertiaryContainer
                },
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = participant.name,
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = when {
                        participant.isBoundToCurrentUser -> "已绑定当前用户"
                        participant.isBound -> "已绑定用户：${participant.boundUserName ?: "其他用户"}"
                        else -> "未绑定用户"
                    },
                    style = SharedLedgerTextStyles.Label,
                    color = if (participant.isBound) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            when {
                participant.isBoundToCurrentUser && canUnbindParticipant -> {
                    TextButton(
                        onClick = onUnbindParticipant,
                        modifier = Modifier.semantics {
                            contentDescription = "解除绑定参与人 ${participant.name}"
                        },
                    ) { Text("解除绑定") }
                }
                canBindParticipant && !participant.isBound -> {
                    TextButton(
                        onClick = { onBindParticipant(participant.participantId) },
                        modifier = Modifier.semantics {
                            contentDescription = "绑定参与人 ${participant.name}"
                        },
                    ) { Text("绑定") }
                }
                canDeleteParticipant -> {
                    IconButton(
                        onClick = onDeleteParticipant,
                        modifier = Modifier.semantics {
                            contentDescription = "删除参与人 ${participant.name}"
                        },
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Delete,
                            contentDescription = null,
                            modifier = Modifier.size(SharedLedgerDimens.ActionIcon),
                            tint = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
            }
        }
        if (showDivider) {
            DividerLine()
        }
    }
}

@Composable
private fun ActivityMembersCard(
    members: List<ActivityManagementMember>,
    canManageMembers: Boolean,
    showTransferOwnershipAction: Boolean,
    onTransferOwnership: (String) -> Unit,
    onRemoveMember: (String) -> Unit,
) {
    ManagementCard {
        CardHeader(icon = Icons.Rounded.Person, title = "活动用户")
        Column(modifier = Modifier.fillMaxWidth()) {
            members.forEachIndexed { index, member ->
                ActivityMemberRow(
                    member = member,
                    index = index,
                    showDivider = index < members.lastIndex,
                    canManageMembers = canManageMembers,
                    showTransferOwnershipAction = showTransferOwnershipAction,
                    onTransferOwnership = { onTransferOwnership(member.memberId) },
                    onRemoveMember = { onRemoveMember(member.memberId) },
                )
            }
        }
    }
}

@Composable
private fun ActivityMemberRow(
    member: ActivityManagementMember,
    index: Int,
    showDivider: Boolean,
    canManageMembers: Boolean,
    showTransferOwnershipAction: Boolean,
    onTransferOwnership: () -> Unit,
    onRemoveMember: () -> Unit,
) {
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            ParticipantAvatar(
                name = member.initial,
                backgroundColor = if (index == 0) {
                    WarmOrangeContainer
                } else {
                    StitchSurfaceContainerHigh
                },
            )
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = member.name,
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    if (member.isCreator) {
                        Text(
                            text = " (${member.role})",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    } else {
                        Text(
                            text = " (${member.role})",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Text(
                    text = member.detail,
                    style = SharedLedgerTextStyles.Label,
                    color = if (member.isCreator) {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }
            if (canManageMembers && showTransferOwnershipAction && ownershipTransferTargetId(member) != null) {
                TextButton(
                    onClick = onTransferOwnership,
                    modifier = Modifier.semantics {
                        contentDescription = "将创建者转移给 ${member.name}"
                    },
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(
                        horizontal = SharedLedgerSpacing.Small,
                        vertical = SharedLedgerSpacing.XSmall,
                    ),
                ) {
                    Text(
                        text = "转移创建者",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            } else if (canManageMembers && !member.isCreator && member.canRemove) {
                IconButton(
                    onClick = onRemoveMember,
                    modifier = Modifier.semantics {
                        contentDescription = "移除用户 ${member.name}"
                    },
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Delete,
                        contentDescription = null,
                        modifier = Modifier.size(SharedLedgerDimens.ActionIcon),
                        tint = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }
        if (showDivider) {
            DividerLine()
        }
    }
}

@Composable
private fun ActivitySettingsCard(
    state: ActivityManagementUiState,
    onEditActivity: (() -> Unit)?,
    onMultiCurrencyChange: (Boolean) -> Unit,
) {
    ManagementCard {
        CardHeader(icon = Icons.Rounded.Settings, title = "活动设置")
        onEditActivity?.let { callback ->
            SettingsActionRow(
                icon = Icons.Rounded.Edit,
                title = "活动资料",
                value = "名称与类型",
                onClick = callback,
                contentDescription = "编辑活动资料",
            )
            DividerLine()
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = SharedLedgerSpacing.MediumSmall),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            Icon(
                imageVector = Icons.Rounded.Settings,
                contentDescription = null,
                modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "开启多币种",
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "支持在活动中记录不同货币",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(
                checked = state.multiCurrencyEnabled,
                onCheckedChange = onMultiCurrencyChange,
                modifier = Modifier.semantics {
                    contentDescription = "多币种，${if (state.multiCurrencyEnabled) "已开启" else "已关闭"}"
                },
                colors = SwitchDefaults.colors(
                    checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                    checkedTrackColor = MaterialTheme.colorScheme.primary,
                    uncheckedThumbColor = MaterialTheme.colorScheme.surface,
                    uncheckedTrackColor = MaterialTheme.colorScheme.surfaceVariant,
                    uncheckedBorderColor = Color.Transparent,
                ),
            )
        }
    }
}

@Composable
private fun SettingsActionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    value: String,
    onClick: () -> Unit,
    contentDescription: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(SharedLedgerRadius.Medium)
            .clickable(onClick = onClick)
            .semantics {
                this.contentDescription = contentDescription
                role = Role.Button
            }
            .padding(vertical = SharedLedgerSpacing.MediumSmall),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = title,
            modifier = Modifier.weight(1f),
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = value,
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = "›",
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ActivityStatusCard(
    state: ActivityManagementUiState,
    onArchiveClick: (() -> Unit)?,
    onUnarchiveClick: (() -> Unit)?,
) {
    val hasOutstandingDebt = state.hasOutstandingDebt
    ManagementCard(contentSpacing = SharedLedgerSpacing.MediumLarge) {
        CardHeader(icon = Icons.Rounded.DataUsage, title = "活动状态")
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "当前状态",
                modifier = Modifier.weight(1f),
                style = SharedLedgerTextStyles.Body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            StatusChip(state.status)
        }
        DividerLine()
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            StatusMetric(
                label = "未结债务",
                value = state.outstandingDebt.ifBlank { "—" },
                icon = Icons.Rounded.ReceiptLong,
                modifier = Modifier.weight(1f),
            )
            StatusMetric(
                label = "剩余预存",
                value = state.remainingPrepayment.ifBlank { "—" },
                icon = Icons.Rounded.Savings,
                modifier = Modifier.weight(1f),
            )
        }
        when {
            onArchiveClick != null -> SharedLedgerButton(
                text = "归档活动",
                onClick = onArchiveClick,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = SharedLedgerSpacing.XSmall),
                variant = SharedLedgerButtonVariant.Neutral,
                icon = Icons.Rounded.Archive,
            )
            onUnarchiveClick != null -> SharedLedgerButton(
                text = "取消归档",
                onClick = onUnarchiveClick,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = SharedLedgerSpacing.XSmall),
                variant = SharedLedgerButtonVariant.Neutral,
                icon = Icons.Rounded.Archive,
            )
        }
        if (hasOutstandingDebt) {
            Text(
                text = "⚠ 当前仍有未结债务，归档后将无法结算",
                modifier = Modifier.fillMaxWidth(),
                style = SharedLedgerTextStyles.Label,
                color = ErrorRed,
                textAlign = TextAlign.Center,
            )
        }
        Text(
            text = if (state.status == ActivityManagementStatus.Archived) {
                "当前活动为只读状态；取消归档后可恢复活动写入口。"
            } else {
                "归档后将变为只读状态，无法再添加新账单。"
            },
            modifier = Modifier.fillMaxWidth(),
            style = SharedLedgerTextStyles.Label,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun StatusMetric(
    label: String,
    value: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = SharedLedgerRadius.Small,
        color = AppBackground,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.2f)),
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = label,
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = value,
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun StatusChip(status: ActivityManagementStatus) {
    val (containerColor, contentColor) = when (status) {
        ActivityManagementStatus.InProgress ->
            MaterialTheme.colorScheme.primary.copy(alpha = 0.1f) to MaterialTheme.colorScheme.primary
        ActivityManagementStatus.Settled ->
            MaterialTheme.colorScheme.primaryContainer to MaterialTheme.colorScheme.onPrimaryContainer
        ActivityManagementStatus.Archived ->
            AppSurfaceVariant to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        shape = CircleShape,
        color = containerColor,
        contentColor = contentColor,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.XSmall),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        ) {
            Box(
                modifier = Modifier
                    .size(SharedLedgerSpacing.Small)
                    .background(contentColor, CircleShape),
            )
            Text(text = status.label, style = SharedLedgerTextStyles.Label)
        }
    }
}

@Composable
private fun DangerZone(
    showLeaveAction: Boolean,
    showDeleteAction: Boolean,
    onLeaveClick: () -> Unit,
    onDeleteClick: () -> Unit,
) {
    val errorColor = MaterialTheme.colorScheme.error
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = SharedLedgerSpacing.Medium),
        shape = SharedLedgerRadius.Medium,
        color = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.25f),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, errorColor.copy(alpha = SharedLedgerDimens.CardBorderAlpha)),
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumLarge),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
                Icon(
                    imageVector = Icons.Rounded.Warning,
                    contentDescription = null,
                    tint = errorColor,
                )
                Text(
                    text = "危险区域",
                    style = SharedLedgerTextStyles.SectionTitle,
                    color = errorColor,
                    modifier = Modifier.semantics { heading() },
                )
            }
            Text(
                text = "删除后活动将从正常列表中移除并停止继续使用，相关历史记录仍由系统保留。",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (showLeaveAction) {
                SharedLedgerButton(
                    text = "退出活动",
                    onClick = onLeaveClick,
                    variant = SharedLedgerButtonVariant.Danger,
                    outlined = true,
                    icon = Icons.Rounded.Logout,
                )
            }
            if (showDeleteAction) {
                Button(
                    onClick = onDeleteClick,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(SharedLedgerDimens.ButtonHeight)
                        .semantics { contentDescription = "删除活动" },
                    shape = SharedLedgerRadius.Full,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    ),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.DeleteForever,
                            contentDescription = null,
                            modifier = Modifier.size(20.dp),
                        )
                        Text(text = "删除活动", style = SharedLedgerTextStyles.Button)
                    }
                }
            }
        }
    }
}

@Composable
private fun CompactActionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
    contentDescription: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(SharedLedgerRadius.Medium)
            .clickable(onClick = onClick)
            .semantics {
                this.contentDescription = contentDescription
                role = Role.Button
            }
            .padding(vertical = SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
    ) {
        Surface(
            modifier = Modifier.size(36.dp),
            shape = CircleShape,
            color = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(SharedLedgerDimens.ActionIcon))
            }
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = subtitle,
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            text = "›",
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun InfoCell(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    leadingIcon: androidx.compose.ui.graphics.vector.ImageVector? = null,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
    ) {
        Text(
            text = label,
            style = SharedLedgerTextStyles.Label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        ) {
            leadingIcon?.let {
                Icon(
                    imageVector = it,
                    contentDescription = null,
                    modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = value,
                style = SharedLedgerTextStyles.Body,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun CardHeader(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
        )
        Text(
            text = title,
            style = SharedLedgerTextStyles.CardTitle,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics { heading() },
        )
    }
}

@Composable
private fun ManagementCard(
    contentSpacing: androidx.compose.ui.unit.Dp = SharedLedgerSpacing.Medium,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        color = AppSurface,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, AppSurfaceVariant),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(contentSpacing),
            content = content,
        )
    }
}

@Composable
private fun DividerLine(color: Color = AppSurfaceVariant.copy(alpha = 0.55f)) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(SharedLedgerDimens.OutlineWidth)
            .background(color),
    )
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
