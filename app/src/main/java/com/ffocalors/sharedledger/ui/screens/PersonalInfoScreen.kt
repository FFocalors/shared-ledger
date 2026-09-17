package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Logout
import androidx.compose.material.icons.rounded.Badge
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Diversity3
import androidx.compose.material.icons.rounded.Flag
import androidx.compose.material.icons.rounded.Groups
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.ManageAccounts
import androidx.compose.material.icons.rounded.PendingActions
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Verified
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.auth.PasswordChangeUiState
import com.ffocalors.sharedledger.ui.profile.CollaborationIdentity
import com.ffocalors.sharedledger.ui.profile.PersonalOverviewUiState
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconTintOrange
import com.ffocalors.sharedledger.ui.theme.IconTintSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import kotlinx.coroutines.launch

private const val AccountSettingsItemIndex = 3

@Composable
fun PersonalInfoScreen(
    displayName: String,
    email: String,
    onBack: () -> Unit,
    onSignOut: () -> Unit,
    modifier: Modifier = Modifier,
    passwordChangeState: PasswordChangeUiState = PasswordChangeUiState(),
    onChangePassword: (String, String) -> Unit = { _, _ -> },
    onClearPasswordChangeState: () -> Unit = {},
    overviewState: PersonalOverviewUiState = PersonalOverviewUiState(),
    onRetryOverview: () -> Unit = {},
    onOpenActivity: ((CollaborationIdentity) -> Unit)? = null,
) {
    val safeName = displayName.trim().ifBlank { email.trim().ifBlank { "用户" } }
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()
    var showPasswordDialog by rememberSaveable { mutableStateOf(false) }
    var showPrivacyNotice by rememberSaveable { mutableStateOf(false) }
    val hazeState = rememberSharedLedgerHazeState()
    Surface(modifier = modifier.fillMaxSize(), color = AppBackground) {
        androidx.compose.material3.Scaffold(
            containerColor = AppBackground,
            topBar = {
                SharedLedgerTopBar(
                    title = "个人信息",
                    showBackButton = true,
                    onBackClick = onBack,
                    showMoreButton = false,
                    containerColor = AppBackground,
                    hazeState = hazeState,
                )
            },
        ) { padding ->
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.TopCenter,
            ) {
            LazyColumn(
                state = listState,
                modifier = Modifier.widthIn(max = SharedLedgerDimens.ContentMaxWidth).fillMaxSize().sharedLedgerHazeSource(hazeState),
                contentPadding = PaddingValues(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = padding.calculateTopPadding() + SharedLedgerSpacing.XSmall,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = padding.calculateBottomPadding() + SharedLedgerSpacing.Large,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                item {
                    ProfileHeroCard(
                        displayName = safeName,
                        email = email,
                        onEditProfile = {
                            coroutineScope.launch {
                                listState.animateScrollToItem(AccountSettingsItemIndex)
                            }
                        },
                    )
                }
                item { ProfileStats(overviewState) }
                item {
                    CollaborationIdentities(
                        state = overviewState,
                        onRetry = onRetryOverview,
                        onOpenActivity = onOpenActivity,
                    )
                }
                item {
                    AccountSettings(
                        displayName = safeName,
                        email = email,
                        onChangePassword = {
                            onClearPasswordChangeState()
                            showPasswordDialog = true
                        },
                        onOpenPrivacyNotice = { showPrivacyNotice = true },
                    )
                }
                item { AboutApp() }
                item { LogoutCard(onSignOut) }
                item {
                    Text(
                        text = "SharedLedger · 简洁高效的多人活动协同账本",
                        modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.XSmall),
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    )
                }
            }
            }
        }
    }
    if (showPasswordDialog) {
        PasswordChangeDialog(
            state = passwordChangeState,
            onSubmit = onChangePassword,
            onClearMessage = onClearPasswordChangeState,
            onDismiss = {
                if (!passwordChangeState.isSubmitting) {
                    showPasswordDialog = false
                    onClearPasswordChangeState()
                }
            },
        )
    }
    if (showPrivacyNotice) {
        PrivacyNoticeSheet(onDismiss = { showPrivacyNotice = false })
    }
}

@Composable
private fun ProfileHeroCard(
    displayName: String,
    email: String,
    onEditProfile: () -> Unit,
) {
    ProfileCard {
        Row(verticalAlignment = Alignment.Top) {
            Box {
                ParticipantAvatar(
                    name = displayName,
                    size = SharedLedgerDimens.AvatarLarge,
                    backgroundColor = IconContainerOrange,
                )
                Surface(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .size(SharedLedgerDimens.IconMedium),
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.primary,
                    border = BorderStroke(SharedLedgerDimens.AvatarBorder, MaterialTheme.colorScheme.surface),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Surface(
                            modifier = Modifier.size(SharedLedgerSpacing.Small),
                            shape = CircleShape,
                            color = MaterialTheme.colorScheme.onPrimary,
                        ) {}
                    }
                }
            }
            Spacer(Modifier.width(SharedLedgerSpacing.Medium))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = displayName,
                        style = SharedLedgerTextStyles.PageTitle,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.width(SharedLedgerSpacing.Small))
                    ProfileTag("当前账号")
                }
                Text(
                    text = email.ifBlank { "未提供邮箱" },
                    modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                ProfileTag("已登录 · 账号正常", modifier = Modifier.padding(top = SharedLedgerSpacing.Small))
            }
        }
        androidx.compose.material3.HorizontalDivider(
            modifier = Modifier.padding(vertical = SharedLedgerSpacing.Medium),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f),
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = "协作身份与活动数据来自当前账号",
                modifier = Modifier.weight(1f),
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            TextButton(
                onClick = onEditProfile,
                contentPadding = PaddingValues(horizontal = SharedLedgerSpacing.XSmall),
            ) {
                Text("编辑资料", style = SharedLedgerTextStyles.Label)
                Icon(
                    imageVector = Icons.Rounded.ChevronRight,
                    contentDescription = null,
                    modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                )
            }
        }
    }
}

@Composable
private fun ProfileStats(state: PersonalOverviewUiState) {
    val overview = state.overview
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            ProfileStatCard("我发起的", overview?.initiatedCount?.toString() ?: "—", Icons.Rounded.Flag, 0, Modifier.weight(1f))
            ProfileStatCard("我参与的", overview?.participatedCount?.toString() ?: "—", Icons.Rounded.Groups, 1, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            ProfileStatCard("认领身份", overview?.claimedIdentityCount?.toString() ?: "—", Icons.Rounded.Badge, 2, Modifier.weight(1f))
            ProfileStatCard("进行中活动", overview?.activeActivityCount?.toString() ?: "—", Icons.Rounded.PendingActions, 3, Modifier.weight(1f))
        }
        if (state.isLoading || state.isRefreshing) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = SharedLedgerSpacing.XSmall),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                CircularProgressIndicator(modifier = Modifier.size(SharedLedgerDimens.IconSmall), strokeWidth = 2.dp)
                Spacer(Modifier.width(SharedLedgerSpacing.Small))
                Text(
                    text = if (state.isRefreshing) "正在刷新活动数据…" else "正在加载活动数据…",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ProfileStatCard(label: String, value: String, icon: androidx.compose.ui.graphics.vector.ImageVector, index: Int, modifier: Modifier = Modifier) {
    val (container, tint) = when (index) {
        0 -> IconContainerSage to IconTintSage
        1 -> Color(0xFFEAF1E1) to Color(0xFF3D5229)
        2 -> Color(0xFFFDF3E7) to IconTintOrange
        else -> Color(0xFFF0F4F8) to Color(0xFF2B6CB0)
    }
    ProfileCard(modifier = modifier, padding = SharedLedgerSpacing.MediumSmall) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Surface(modifier = Modifier.size(SharedLedgerDimens.ActionIconContainer), shape = SharedLedgerRadius.Large, color = container) {
                androidx.compose.foundation.layout.Box(contentAlignment = Alignment.Center) {
                    Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(SharedLedgerDimens.ActionIcon))
                }
            }
            Spacer(Modifier.width(SharedLedgerSpacing.MediumSmall))
            Column {
                Text(label, style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(value, style = SharedLedgerTextStyles.CardTitle, modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall))
            }
        }
    }
}

@Composable
private fun CollaborationIdentities(
    state: PersonalOverviewUiState,
    onRetry: () -> Unit,
    onOpenActivity: ((CollaborationIdentity) -> Unit)?,
) {
    ProfileCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Rounded.Diversity3, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            Text("我的协作身份", modifier = Modifier.weight(1f), style = SharedLedgerTextStyles.CardTitle)
            if (state.isRefreshing) {
                CircularProgressIndicator(modifier = Modifier.size(SharedLedgerDimens.IconSmall), strokeWidth = 2.dp)
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Medium),
            shape = SharedLedgerRadius.Large,
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f),
        ) {
            Row(modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall), verticalAlignment = Alignment.Top) {
                Icon(Icons.Rounded.Info, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(SharedLedgerDimens.IconSmall))
                Spacer(Modifier.width(SharedLedgerSpacing.Small))
                Text("这里展示当前账号在每个活动中的成员角色与参与人绑定状态。", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        when {
            state.overview == null && state.isLoading -> ProfileLoadingRow()
            state.overview == null && state.errorMessage != null -> ProfileLoadError(state.errorMessage, onRetry)
            else -> {
                state.errorMessage?.let { ProfileLoadError(it, onRetry) }
                val identities = state.overview?.identities.orEmpty()
                if (identities.isEmpty()) {
                    Text(
                        text = "当前账号还没有可见活动。创建或加入活动后，协作身份会显示在这里。",
                        modifier = Modifier.fillMaxWidth().padding(vertical = SharedLedgerSpacing.Medium),
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    identities.forEachIndexed { index, identity ->
                        if (index > 0) {
                            androidx.compose.material3.HorizontalDivider(
                                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f),
                            )
                        }
                        CollaborationIdentityRow(identity, onOpenActivity)
                    }
                }
            }
        }
    }
}

@Composable
private fun ProfileLoadingRow() {
    LoadingState(message = "正在加载真实活动与协作身份…", isRefreshing = true)
}

@Composable
private fun ProfileLoadError(message: String, onRetry: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Medium),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = message,
            modifier = Modifier.weight(1f),
            style = SharedLedgerTextStyles.Label,
            color = MaterialTheme.colorScheme.error,
        )
        TextButton(onClick = onRetry) { Text("重试") }
    }
}

@Composable
private fun CollaborationIdentityRow(
    identity: CollaborationIdentity,
    onOpenActivity: ((CollaborationIdentity) -> Unit)?,
) {
    val rowModifier = if (onOpenActivity != null) {
        Modifier.clip(SharedLedgerRadius.Medium).clickable { onOpenActivity(identity) }
    } else {
        Modifier
    }
    Row(
        modifier = rowModifier.fillMaxWidth().padding(vertical = SharedLedgerSpacing.MediumSmall),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ParticipantAvatar(
            name = identity.participantName ?: identity.activityName,
            size = SharedLedgerDimens.AvatarMedium,
            backgroundColor = if (identity.isCreator) IconContainerSage else IconContainerOrange,
        )
        Spacer(Modifier.width(SharedLedgerSpacing.MediumSmall))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = identity.activityName,
                    modifier = Modifier.weight(1f, fill = false),
                    style = SharedLedgerTextStyles.Body,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.width(SharedLedgerSpacing.XSmall))
                ProfileTag(if (identity.isCreator) "创建者" else "活动成员")
            }
            Text(
                text = when {
                    identity.isParticipantBound && identity.participantName != null -> "绑定参与人：${identity.participantName}"
                    identity.isParticipantBound -> "已绑定参与人，信息待同步"
                    else -> "未绑定参与人"
                },
                modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (identity.isArchived) {
                Text(
                    text = "已归档 · 只读",
                    modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        if (onOpenActivity != null) {
            Icon(
                Icons.Rounded.ChevronRight,
                contentDescription = "打开${identity.activityName}",
                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AccountSettings(
    displayName: String,
    email: String,
    onChangePassword: () -> Unit,
    onOpenPrivacyNotice: () -> Unit,
) {
    ProfileCard {
        SectionHeading(Icons.Rounded.ManageAccounts, "账号设置")
        SettingRow("用户昵称", displayName)
        SettingRow("绑定邮箱", email.ifBlank { "未提供" }, trailingIcon = Icons.Rounded.Verified)
        SettingRow("登录方式", "邮箱 / 密码")
        SettingRow("加入时间", "当前会话")
        androidx.compose.material3.HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f))
        SettingActionRow(Icons.Rounded.Key, "修改登录密码", onChangePassword)
        SettingActionRow(Icons.Rounded.Shield, "安全与隐私说明", onOpenPrivacyNotice)
    }
}

@Composable
private fun AboutApp() {
    ProfileCard {
        SectionHeading(Icons.Rounded.Info, "关于应用")
        SettingRow("软件版本", "SharedLedger Android")
        SettingRow("服务协议", "暂未配置")
        SettingRow("离线数据状态", "实时同步")
    }
}

@Composable
private fun LogoutCard(onSignOut: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        color = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.35f),
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, MaterialTheme.colorScheme.error.copy(alpha = 0.2f)),
    ) {
        Button(
            onClick = onSignOut,
            modifier = Modifier.fillMaxWidth().padding(SharedLedgerSpacing.MediumSmall),
            shape = SharedLedgerRadius.Large,
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.error,
                contentColor = MaterialTheme.colorScheme.onError,
            ),
        ) {
            Icon(Icons.AutoMirrored.Rounded.Logout, contentDescription = null)
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            Text("退出当前账号")
        }
    }
}

@Composable
private fun ProfileCard(
    modifier: Modifier = Modifier,
    padding: androidx.compose.ui.unit.Dp = SharedLedgerSpacing.MediumLarge,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = SharedLedgerRadius.ExtraLarge,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, AppOutlineVariant.copy(alpha = 0.55f)),
        shadowElevation = SharedLedgerElevation.Static,
    ) {
        Column(modifier = Modifier.padding(padding), content = content)
    }
}

@Composable
private fun SectionHeading(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = SharedLedgerSpacing.Small)) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(SharedLedgerDimens.ActionIcon))
        Spacer(Modifier.width(SharedLedgerSpacing.Small))
        Text(title, style = SharedLedgerTextStyles.CardTitle)
    }
}

@Composable
private fun SettingRow(label: String, value: String, trailingIcon: androidx.compose.ui.graphics.vector.ImageVector? = null) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = SharedLedgerSpacing.XSmall),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, modifier = Modifier.weight(1f), style = SharedLedgerTextStyles.BodySecondary, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = SharedLedgerTextStyles.BodySecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
        trailingIcon?.let { Icon(it, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = SharedLedgerSpacing.XSmall).size(SharedLedgerDimens.IconSmall)) }
    }
}

@Composable
private fun SettingActionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
) {
    TextButton(onClick = onClick, modifier = Modifier.fillMaxWidth(), contentPadding = PaddingValues(vertical = SharedLedgerSpacing.XSmall)) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(SharedLedgerDimens.IconSmall))
        Text(label, modifier = Modifier.weight(1f).padding(start = SharedLedgerSpacing.Small), textAlign = androidx.compose.ui.text.style.TextAlign.Start)
        Icon(Icons.Rounded.ChevronRight, contentDescription = null, modifier = Modifier.size(SharedLedgerDimens.IconSmall))
    }
}

@Composable
private fun ProfileTag(text: String, modifier: Modifier = Modifier) {
    Surface(modifier = modifier, shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer) {
        Text(text, modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Small, vertical = SharedLedgerSpacing.XSmall), style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onPrimaryContainer)
    }
}

@Preview(name = "个人信息", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PersonalInfoScreenPreview() {
    SharedLedgerTheme {
        PersonalInfoScreen(
            displayName = "Alice",
            email = "alice@example.com",
            onBack = {},
            onSignOut = {},
        )
    }
}
