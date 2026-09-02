package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.material.icons.rounded.PersonAdd
import androidx.compose.material.icons.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.Savings
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonVariant
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.AppSurfaceLow
import com.ffocalors.sharedledger.ui.theme.AppSurfaceVariant
import com.ffocalors.sharedledger.ui.theme.ErrorContainer
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer

private val StitchSurfaceContainer = Color(0xFFEFEDED)
private val StitchSurfaceContainerHigh = Color(0xFFEAE8E7)

/** The state shown by the activity-management screen. The host owns this state. */
@Immutable
data class ActivityManagementUiState(
    val activityName: String = "周末露营计划",
    val activityType: String = "旅行",
    val baseCurrency: String = "CNY (¥)",
    val multiCurrencyEnabled: Boolean = true,
    val joinCode: String = "5831 2746",
    val participantListLocked: Boolean = true,
    val participantListLockMessage: String = "参与人名单已锁定 (已产生正式账单)",
    val participants: List<ActivityManagementParticipant> = listOf(
        ActivityManagementParticipant("Participant 1", "A", isBound = true, participantId = "demo-participant-1"),
        ActivityManagementParticipant("Participant 2", "B", isBound = false, participantId = "demo-participant-2"),
    ),
    val members: List<ActivityManagementMember> = listOf(
        ActivityManagementMember(
            name = "Alice",
            initial = "A",
            role = "创建者",
            detail = "关联参与人: Participant 1",
            isCreator = true,
            memberId = "demo-member-alice",
        ),
        ActivityManagementMember(
            name = "Charlie",
            initial = "C",
            role = "成员",
            detail = "账号已关联",
            memberId = "demo-member-charlie",
        ),
    ),
    val permissionSummary: String = "创建者可管理",
    val status: ActivityManagementStatus = ActivityManagementStatus.InProgress,
    val outstandingDebt: String = "¥ 350.00",
    val remainingPrepayment: String = "¥ 0.00",
    val showInviteEntry: Boolean = false,
    val showSettings: Boolean = false,
    val showLeaveAction: Boolean = false,
    /** The original Stitch screen exposes an ownership action; it must target a non-creator row. */
    val showTransferOwnershipAction: Boolean = true,
)

@Immutable
data class ActivityManagementParticipant(
    val name: String,
    val initial: String = name.take(1),
    val isBound: Boolean,
    val participantId: String = "",
)

@Immutable
data class ActivityManagementMember(
    val name: String,
    val initial: String = name.take(1),
    val role: String = "成员",
    val detail: String = "账号已关联",
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
    activityId: String = com.ffocalors.sharedledger.ui.demo.DemoRouteIds.NORMAL_ACTIVITY,
    modifier: Modifier = Modifier,
    state: ActivityManagementUiState = ActivityManagementUiState(),
    onBackClick: () -> Unit = {},
    onMoreClick: ((String) -> Unit)? = null,
    onCopyJoinCode: (String, String) -> Unit = { _, _ -> },
    onInviteClick: (String) -> Unit = {},
    onEditActivity: (String) -> Unit = {},
    onManagePermissions: (String) -> Unit = {},
    onMultiCurrencyChange: (String, Boolean) -> Unit = { _, _ -> },
    onTransferOwnership: (String, String) -> Unit = { _, _ -> },
    onRemoveMember: (String, String) -> Unit = { _, _ -> },
    onArchiveActivity: (String) -> Unit = {},
    onLeaveActivity: (String) -> Unit = {},
    onDeleteActivity: (String) -> Unit = {},
) {
    var pendingConfirmation by rememberSaveable { mutableStateOf<ManagementConfirmation?>(null) }
    var actionMessage by rememberSaveable { mutableStateOf<String?>(null) }
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(actionMessage) {
        actionMessage?.let { message ->
            snackbarHostState.showSnackbar(message)
            actionMessage = null
        }
    }

    fun runAction(message: String, action: () -> Unit) {
        action()
        actionMessage = message
    }

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
                BasicInfoCard(
                    state = state,
                    onCopyJoinCode = {
                        runAction("演示：加入码已准备复制") {
                            onCopyJoinCode(activityId, state.joinCode)
                        }
                    },
                )
                if (state.showInviteEntry) {
                    SharedLedgerButton(
                        text = "邀请成员",
                        onClick = {
                            runAction("演示：已打开邀请入口") { onInviteClick(activityId) }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        variant = SharedLedgerButtonVariant.Neutral,
                        icon = Icons.Rounded.PersonAdd,
                    )
                }
                ParticipantManagementCard(state = state)
                ActivityMembersCard(
                    members = state.members,
                    showTransferOwnershipAction = state.showTransferOwnershipAction,
                    onTransferOwnership = { memberId ->
                        runAction("演示：已提交创建者转移") {
                            onTransferOwnership(activityId, memberId)
                        }
                    },
                    onRemoveMember = { memberId ->
                        runAction("演示：已提交移除成员") {
                            onRemoveMember(activityId, memberId)
                        }
                    },
                )
                if (state.showSettings) {
                    ActivitySettingsCard(
                        state = state,
                        onEditActivity = {
                            runAction("演示：已打开活动资料") { onEditActivity(activityId) }
                        },
                        onManagePermissions = {
                            runAction("演示：已打开成员权限") { onManagePermissions(activityId) }
                        },
                        onMultiCurrencyChange = { enabled ->
                            runAction("演示：多币种已${if (enabled) "开启" else "关闭"}") {
                                onMultiCurrencyChange(activityId, enabled)
                            }
                        },
                    )
                }
                ActivityStatusCard(
                    state = state,
                    onArchiveClick = { pendingConfirmation = ManagementConfirmation.Archive },
                )
                DangerZone(
                    showLeaveAction = state.showLeaveAction,
                    onLeaveClick = { pendingConfirmation = ManagementConfirmation.Leave },
                    onDeleteClick = { pendingConfirmation = ManagementConfirmation.Delete },
                )
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
                    ManagementConfirmation.Archive -> runAction("演示：活动已归档") {
                        onArchiveActivity(activityId)
                    }
                    ManagementConfirmation.Leave -> runAction("演示：已退出活动") {
                        onLeaveActivity(activityId)
                    }
                    ManagementConfirmation.Delete -> runAction("演示：活动已删除") {
                        onDeleteActivity(activityId)
                    }
                }
            },
        )
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
            text = "管理您的活动详情、成员及状态。",
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
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)),
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
private fun ParticipantManagementCard(state: ActivityManagementUiState) {
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
                        modifier = Modifier.size(18.dp),
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
        CardHeader(icon = Icons.Rounded.Group, title = "参与人管理")
        Column(modifier = Modifier.fillMaxWidth()) {
            state.participants.forEachIndexed { index, participant ->
                ParticipantManagementRow(
                    participant = participant,
                    index = index,
                    showDivider = index < state.participants.lastIndex,
                )
            }
        }
    }
}

@Composable
private fun ParticipantManagementRow(
    participant: ActivityManagementParticipant,
    index: Int,
    showDivider: Boolean,
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
                    text = if (participant.isBound) "已绑定" else "未绑定",
                    style = SharedLedgerTextStyles.Label,
                    color = if (participant.isBound) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
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
    showTransferOwnershipAction: Boolean,
    onTransferOwnership: (String) -> Unit,
    onRemoveMember: (String) -> Unit,
) {
    ManagementCard {
        CardHeader(icon = Icons.Rounded.Person, title = "活动成员")
        Column(modifier = Modifier.fillMaxWidth()) {
            members.forEachIndexed { index, member ->
                ActivityMemberRow(
                    member = member,
                    index = index,
                    showDivider = index < members.lastIndex,
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
            if (showTransferOwnershipAction && ownershipTransferTargetId(member) != null) {
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
            } else if (!member.isCreator && member.canRemove) {
                IconButton(
                    onClick = onRemoveMember,
                    modifier = Modifier.semantics {
                        contentDescription = "移除成员 ${member.name}"
                    },
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Delete,
                        contentDescription = null,
                        modifier = Modifier.size(20.dp),
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
    onEditActivity: () -> Unit,
    onManagePermissions: () -> Unit,
    onMultiCurrencyChange: (Boolean) -> Unit,
) {
    ManagementCard {
        CardHeader(icon = Icons.Rounded.Settings, title = "活动设置")
        SettingsActionRow(
            icon = Icons.Rounded.Edit,
            title = "活动资料",
            value = "名称与类型",
            onClick = onEditActivity,
            contentDescription = "编辑活动资料",
        )
        DividerLine()
        SettingsActionRow(
            icon = Icons.Rounded.Group,
            title = "成员权限",
            value = state.permissionSummary,
            onClick = onManagePermissions,
            contentDescription = "管理成员权限",
        )
        DividerLine()
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
                modifier = Modifier.size(22.dp),
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
            modifier = Modifier.size(22.dp),
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
    onArchiveClick: () -> Unit,
) {
    val hasOutstandingDebt = state.outstandingDebt != "¥ 0.00"
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
                value = state.outstandingDebt,
                icon = Icons.Rounded.ReceiptLong,
                modifier = Modifier.weight(1f),
            )
            StatusMetric(
                label = "剩余预存",
                value = state.remainingPrepayment,
                icon = Icons.Rounded.Savings,
                modifier = Modifier.weight(1f),
            )
        }
        SharedLedgerButton(
            text = "归档活动",
            onClick = onArchiveClick,
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = SharedLedgerSpacing.XSmall),
            variant = SharedLedgerButtonVariant.Neutral,
            icon = Icons.Rounded.Archive,
        )
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
            text = "归档后将变为只读状态，无法再添加新账单。",
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
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.2f)),
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
                    modifier = Modifier.size(14.dp),
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
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        ) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(contentColor, CircleShape),
            )
            Text(text = status.label, style = SharedLedgerTextStyles.Label)
        }
    }
}

@Composable
private fun DangerZone(
    showLeaveAction: Boolean,
    onLeaveClick: () -> Unit,
    onDeleteClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = SharedLedgerSpacing.Medium),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        DividerLine(color = ErrorRed.copy(alpha = 0.2f))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Icon(
                imageVector = Icons.Rounded.Warning,
                contentDescription = null,
                tint = ErrorRed,
            )
            Text(
                text = "危险区域",
                style = SharedLedgerTextStyles.SectionTitle,
                color = ErrorRed,
                modifier = Modifier.semantics { heading() },
            )
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = SharedLedgerRadius.Medium,
            color = ErrorContainer.copy(alpha = 0.2f),
            border = BorderStroke(1.dp, ErrorRed.copy(alpha = 0.3f)),
            shadowElevation = SharedLedgerElevation.Card,
        ) {
            Column(
                modifier = Modifier.padding(SharedLedgerSpacing.MediumLarge),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
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
                SharedLedgerButton(
                    text = "删除活动",
                    onClick = onDeleteClick,
                    variant = SharedLedgerButtonVariant.Danger,
                    icon = Icons.Rounded.DeleteForever,
                )
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
                Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(20.dp))
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
                    modifier = Modifier.size(18.dp),
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
            modifier = Modifier.size(24.dp),
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
        border = BorderStroke(1.dp, AppSurfaceVariant),
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
            .height(1.dp)
            .background(color),
    )
}

private enum class ManagementConfirmation {
    Archive,
    Leave,
    Delete,
}

@Composable
private fun ManagementConfirmationDialog(
    confirmation: ManagementConfirmation,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    val (title, message, confirmLabel, confirmColor) = when (confirmation) {
        ManagementConfirmation.Archive -> Quadruple(
            "归档活动？",
            "归档后活动将变为只读状态，无法再添加新账单。确定继续吗？",
            "归档活动",
            MaterialTheme.colorScheme.primary,
        )
        ManagementConfirmation.Leave -> Quadruple(
            "退出活动？",
            "退出后您将无法继续记录或查看此活动中的新变化。确定退出吗？",
            "退出活动",
            MaterialTheme.colorScheme.primary,
        )
        ManagementConfirmation.Delete -> Quadruple(
            "删除活动？",
            "删除后活动将从正常列表中移除，相关历史记录仍由系统保留。此操作不可撤销。",
            "删除活动",
            ErrorRed,
        )
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(text = title, style = SharedLedgerTextStyles.CardTitle) },
        text = { Text(text = message, style = SharedLedgerTextStyles.BodySecondary) },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(text = "取消", style = SharedLedgerTextStyles.BodySecondary)
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = ButtonDefaults.buttonColors(
                    containerColor = confirmColor,
                    contentColor = if (confirmation == ManagementConfirmation.Delete) {
                        MaterialTheme.colorScheme.onError
                    } else {
                        MaterialTheme.colorScheme.onPrimary
                    },
                ),
            ) {
                Text(text = confirmLabel, style = SharedLedgerTextStyles.BodySecondary)
            }
        },
    )
}

private data class Quadruple<out A, out B, out C, out D>(
    val first: A,
    val second: B,
    val third: C,
    val fourth: D,
)

@Preview(name = "活动管理", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun ActivityManagementScreenPreview() {
    SharedLedgerTheme {
        ActivityManagementScreen()
    }
}
