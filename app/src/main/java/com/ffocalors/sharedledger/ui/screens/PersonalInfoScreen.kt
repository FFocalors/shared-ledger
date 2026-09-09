package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Badge
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Diversity3
import androidx.compose.material.icons.rounded.Flag
import androidx.compose.material.icons.rounded.Groups
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.ManageAccounts
import androidx.compose.material.icons.rounded.PendingActions
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Verified
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconTintOrange
import com.ffocalors.sharedledger.ui.theme.IconTintSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.TextSecondary

@Composable
fun PersonalInfoScreen(
    displayName: String,
    email: String,
    onBack: () -> Unit,
    onSignOut: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val safeName = displayName.trim().ifBlank { email.trim().ifBlank { "用户" } }
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
                )
            },
        ) { padding ->
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(
                    start = SharedLedgerSpacing.Medium,
                    top = padding.calculateTopPadding() + SharedLedgerSpacing.XSmall,
                    end = SharedLedgerSpacing.Medium,
                    bottom = padding.calculateBottomPadding() + SharedLedgerSpacing.Large,
                ),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
            ) {
                item { ProfileHeroCard(safeName, email) }
                item { ProfileStats() }
                item { CollaborationIdentities() }
                item { AccountSettings(safeName, email) }
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

@Composable
private fun ProfileHeroCard(displayName: String, email: String) {
    ProfileCard {
        Row(verticalAlignment = Alignment.Top) {
            ParticipantAvatar(
                name = displayName,
                size = 64.dp,
                backgroundColor = IconContainerOrange,
            )
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
            Text("资料编辑暂未开放", style = SharedLedgerTextStyles.Label, color = TextSecondary)
        }
    }
}

@Composable
private fun ProfileStats() {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            ProfileStatCard("我发起的", "0", Icons.Rounded.Flag, 0, Modifier.weight(1f))
            ProfileStatCard("我参与的", "0", Icons.Rounded.Groups, 1, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            ProfileStatCard("认领身份", "0", Icons.Rounded.Badge, 2, Modifier.weight(1f))
            ProfileStatCard("进行中活动", "0", Icons.Rounded.PendingActions, 3, Modifier.weight(1f))
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
            Surface(modifier = Modifier.size(40.dp), shape = RoundedCornerShape(16.dp), color = container) {
                androidx.compose.foundation.layout.Box(contentAlignment = Alignment.Center) {
                    Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(20.dp))
                }
            }
            Spacer(Modifier.width(SharedLedgerSpacing.MediumSmall))
            Column {
                Text(label, style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(value, style = SharedLedgerTextStyles.CardTitle, modifier = Modifier.padding(top = 2.dp))
            }
        }
    }
}

@Composable
private fun CollaborationIdentities() {
    ProfileCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Rounded.Diversity3, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            Text("我的协作身份", style = SharedLedgerTextStyles.CardTitle)
        }
        Text(
            text = "你在多人账本中认领的记账参与人。账目收支将直接计入你所绑定的角色名下。",
            modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
            style = SharedLedgerTextStyles.Label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Surface(
            modifier = Modifier.fillMaxWidth().padding(top = SharedLedgerSpacing.Medium),
            shape = SharedLedgerRadius.Large,
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f),
        ) {
            Row(modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall), verticalAlignment = Alignment.Top) {
                Icon(Icons.Rounded.Info, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(SharedLedgerSpacing.Small))
                Text("创建者可以为自己或未注册的好友认领不同的记账席位。", style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Text(
            text = "当前账号的绑定身份会在对应活动详情中显示。",
            modifier = Modifier.fillMaxWidth().padding(vertical = SharedLedgerSpacing.Medium),
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun AccountSettings(displayName: String, email: String) {
    ProfileCard {
        SectionHeading(Icons.Rounded.ManageAccounts, "账号设置")
        SettingRow("用户昵称", displayName)
        SettingRow("绑定邮箱", email.ifBlank { "未提供" }, trailingIcon = Icons.Rounded.Verified)
        SettingRow("登录方式", "邮箱 / 密码")
        SettingRow("加入时间", "当前会话")
        androidx.compose.material3.HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f))
        DisabledSettingRow(Icons.Rounded.Key, "修改登录密码")
        DisabledSettingRow(Icons.Rounded.Shield, "安全与隐私说明")
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
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.error.copy(alpha = 0.2f)),
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
            Icon(Icons.Rounded.Logout, contentDescription = null)
            Spacer(Modifier.width(SharedLedgerSpacing.Small))
            Text("退出当前账号")
        }
    }
}

@Composable
private fun ProfileCard(
    modifier: Modifier = Modifier,
    padding: androidx.compose.ui.unit.Dp = SharedLedgerSpacing.Medium,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, AppOutlineVariant.copy(alpha = 0.55f)),
        shadowElevation = 1.dp,
    ) {
        Column(modifier = Modifier.padding(padding), content = content)
    }
}

@Composable
private fun SectionHeading(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = SharedLedgerSpacing.Small)) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
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
        trailingIcon?.let { Icon(it, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = SharedLedgerSpacing.XSmall).size(18.dp)) }
    }
}

@Composable
private fun DisabledSettingRow(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String) {
    TextButton(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth(), contentPadding = PaddingValues(vertical = SharedLedgerSpacing.XSmall)) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
        Text(label, modifier = Modifier.weight(1f).padding(start = SharedLedgerSpacing.Small), textAlign = androidx.compose.ui.text.style.TextAlign.Start)
        Icon(Icons.Rounded.ChevronRight, contentDescription = null, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun ProfileTag(text: String, modifier: Modifier = Modifier) {
    Surface(modifier = modifier, shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer) {
        Text(text, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp), style = SharedLedgerTextStyles.Label, color = MaterialTheme.colorScheme.onPrimaryContainer)
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
