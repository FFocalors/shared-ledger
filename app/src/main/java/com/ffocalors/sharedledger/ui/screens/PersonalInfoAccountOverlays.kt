package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.auth.PasswordChangeUiState
import com.ffocalors.sharedledger.ui.components.SharedLedgerDialog
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles

@Composable
internal fun PasswordChangeDialog(
    state: PasswordChangeUiState,
    onSubmit: (String, String) -> Unit,
    onDismiss: () -> Unit,
    onClearMessage: () -> Unit = {},
) {
    // Keep credentials only in the active composition. They must not enter SavedState.
    var newPassword by remember { mutableStateOf("") }
    var confirmPassword by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var confirmPasswordVisible by remember { mutableStateOf(false) }

    SharedLedgerDialog(
        onDismiss = onDismiss,
        title = if (state.isSuccess) "密码已更新" else "修改登录密码",
        textContent = {
            if (state.isSuccess) {
                Text(
                    text = state.message.orEmpty(),
                    style = SharedLedgerTextStyles.BodySecondary,
                )
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
                    Text(
                        text = "设置至少 8 个字符且同时包含字母和数字的新密码。修改成功后当前账号会保持登录。",
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    PasswordField(
                        value = newPassword,
                        onValueChange = {
                            newPassword = it
                            onClearMessage()
                        },
                        label = "新密码",
                        visible = passwordVisible,
                        onToggleVisibility = { passwordVisible = !passwordVisible },
                        enabled = !state.isSubmitting,
                        imeAction = ImeAction.Next,
                    )
                    PasswordField(
                        value = confirmPassword,
                        onValueChange = {
                            confirmPassword = it
                            onClearMessage()
                        },
                        label = "确认新密码",
                        visible = confirmPasswordVisible,
                        onToggleVisibility = { confirmPasswordVisible = !confirmPasswordVisible },
                        enabled = !state.isSubmitting,
                        imeAction = ImeAction.Done,
                    )
                    state.message?.let { message ->
                        Text(
                            text = message,
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            }
        },
        dismissText = if (state.isSuccess) null else "取消",
        dismissEnabled = !state.isSubmitting,
        confirmText = if (state.isSuccess) "完成" else "保存",
        confirmEnabled = state.isSuccess ||
            (newPassword.isNotEmpty() && confirmPassword.isNotEmpty() && !state.isSubmitting),
        confirmLoading = state.isSubmitting,
        onConfirm = {
            if (state.isSuccess) {
                onDismiss()
            } else {
                onSubmit(newPassword, confirmPassword)
            }
        },
    )
}

@Composable
private fun PasswordField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    visible: Boolean,
    onToggleVisibility: () -> Unit,
    enabled: Boolean,
    imeAction: ImeAction,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        singleLine = true,
        enabled = enabled,
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = imeAction),
        trailingIcon = {
            IconButton(onClick = onToggleVisibility, enabled = enabled) {
                Icon(
                    imageVector = if (visible) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                    contentDescription = if (visible) "隐藏密码" else "显示密码",
                )
            }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PrivacyNoticeSheet(onDismiss: () -> Unit) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = 680.dp)
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(
                    start = SharedLedgerSpacing.MediumLarge,
                    end = SharedLedgerSpacing.MediumLarge,
                    bottom = SharedLedgerSpacing.Large,
                ),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("安全与隐私说明", style = SharedLedgerTextStyles.PageTitle, modifier = Modifier.weight(1f))
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Rounded.Close, contentDescription = "关闭隐私说明")
                }
            }
            Text(
                text = "本说明介绍 SharedLedger Android 当前会处理的数据和已提供的数据控制。",
                modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            PrivacySection(
                title = "账号与登录",
                body = "注册和登录会使用邮箱、昵称和 Supabase Auth 会话。应用使用登录会话识别当前账号，并从账号资料中显示昵称。密码由认证服务处理，应用界面不会展示已保存的密码。",
            )
            PrivacySection(
                title = "活动与账单数据",
                body = "你创建或加入活动时产生的参与人、消费、分摊、转账、收款、预存、退款和最终结算数据会保存到项目的 Supabase 服务，用于向有权访问该活动的成员展示账本并计算结算结果。",
            )
            PrivacySection(
                title = "附件",
                body = "只有在你主动选择文件或图片时，应用才会把附件上传到 Supabase Storage，并把附件关联到对应账单。能否查看、添加或删除附件取决于活动成员身份、业务权限和归档状态。",
            )
            PrivacySection(
                title = "实时同步",
                body = "当你打开活动相关页面时，应用会监听该活动的数据变化并刷新内容，以便不同设备看到较新的账本状态。实时同步用于活动账本更新。",
            )
            PrivacySection(
                title = "你可以进行的控制",
                body = "你可以在现有权限和业务规则允许的范围内修改、作废或恢复记录，管理自己添加的附件，并在个人信息页退出当前账号。已归档活动保持只读；应用当前未提供账号删除入口。",
            )
            PrivacySection(
                title = "网络与会话",
                body = "登录、同步账本、上传附件和修改密码需要网络连接。退出登录会结束当前设备上的登录会话；再次使用账号功能时需要重新登录。",
            )
            Spacer(Modifier.size(SharedLedgerSpacing.Medium))
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text("我知道了") }
        }
    }
}

@Composable
private fun PrivacySection(title: String, body: String) {
    Text(
        text = title,
        modifier = Modifier.padding(top = SharedLedgerSpacing.MediumLarge),
        style = SharedLedgerTextStyles.CardTitle,
    )
    Text(
        text = body,
        modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
        style = SharedLedgerTextStyles.BodySecondary,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}
