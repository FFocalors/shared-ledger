package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.ui.components.ManagementCard
import com.ffocalors.sharedledger.ui.components.ManagementCardHeader
import com.ffocalors.sharedledger.ui.components.ManagementDivider
import com.ffocalors.sharedledger.ui.components.ManagementGroup
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonVariant
import com.ffocalors.sharedledger.ui.components.SharedLedgerDialog
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.AppSurfaceLow
import com.ffocalors.sharedledger.ui.theme.AppSurfaceVariant
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter

private val StitchSurfaceContainer = Color(0xFFEFEDED)

@Composable
internal fun ActivityManagementPageTitle() {
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
internal fun BasicInfoCard(
    state: ActivityManagementUiState,
    onCopyJoinCode: () -> Unit,
) {
    ManagementCard {
        ManagementCardHeader(icon = Icons.Rounded.Info, title = "基本信息")
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
internal fun ParticipantManagementCard(
    modifier: Modifier = Modifier,
    state: ActivityManagementUiState,
    onCreateParticipant: (String) -> Unit,
    onDeleteParticipant: ((String) -> Unit)?,
    onBindParticipant: (String) -> Unit,
    onUnbindParticipant: () -> Unit,
) {
    var showCreateDialog by rememberSaveable { mutableStateOf(false) }
    var participantName by rememberSaveable { mutableStateOf("") }
    ManagementCard(modifier = modifier) {
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
                ManagementCardHeader(icon = Icons.Rounded.Group, title = "参与人管理")
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
                name = participant.name,
                background = if (participant.isBound) {
                    AvatarBackground.Bound(participant.avatarStyle, participant.boundUserId)
                } else {
                    AvatarBackground.Unbound(participant.participantId.ifBlank { participant.name })
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
            ManagementDivider()
        }
    }
}

@Composable
internal fun ActivityMembersCard(
    members: List<ActivityManagementMember>,
    canManageMembers: Boolean,
    showTransferOwnershipAction: Boolean,
    onTransferOwnership: (String) -> Unit,
    onRemoveMember: (String) -> Unit,
) {
    ManagementGroup {
        ManagementCardHeader(icon = Icons.Rounded.Person, title = "活动用户")
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
                name = member.name,
                background = AvatarBackground.Bound(member.avatarStyle, member.memberId),
            )
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = member.name,
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = " (${member.role})",
                        style = SharedLedgerTextStyles.Label,
                        color = if (member.isCreator) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
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
            ManagementDivider()
        }
    }
}

@Composable
internal fun ActivitySettingsCard(
    state: ActivityManagementUiState,
    onEditActivity: (() -> Unit)?,
    onMultiCurrencyChange: (Boolean) -> Unit,
) {
    ManagementGroup {
        ManagementCardHeader(icon = Icons.Rounded.Settings, title = "活动设置")
        onEditActivity?.let { callback ->
            SettingsActionRow(
                icon = Icons.Rounded.Edit,
                title = "活动资料",
                value = "名称与类型",
                onClick = callback,
                contentDescription = "编辑活动资料",
            )
            ManagementDivider()
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
    icon: ImageVector,
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
internal fun ActivityStatusCard(
    state: ActivityManagementUiState,
    onArchiveClick: (() -> Unit)?,
    onUnarchiveClick: (() -> Unit)?,
) {
    val hasOutstandingDebt = state.hasOutstandingDebt
    ManagementGroup(contentSpacing = SharedLedgerSpacing.MediumLarge) {
        ManagementCardHeader(icon = Icons.Rounded.DataUsage, title = "活动状态")
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
        ManagementDivider()
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
    icon: ImageVector,
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
internal fun DangerZone(
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
    icon: ImageVector,
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
    leadingIcon: ImageVector? = null,
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
internal fun DeletedSubActivitiesCard(
    items: List<ActivityManagementDeletedSubActivity>,
    onRestore: (String) -> Unit,
) {
    if (items.isEmpty()) return
    ManagementGroup(contentSpacing = SharedLedgerSpacing.Small) {
        ManagementCardHeader(icon = Icons.Rounded.Delete, title = "已删除子活动")
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
