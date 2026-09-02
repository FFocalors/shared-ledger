package com.ffocalors.sharedledger.ui.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
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
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.AppSurfaceLow
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.Neutral
import com.ffocalors.sharedledger.ui.theme.NeutralContent
import com.ffocalors.sharedledger.ui.theme.SageGreen
import com.ffocalors.sharedledger.ui.theme.SoftPrimary
import com.ffocalors.sharedledger.ui.theme.SoftPrimaryContent
import com.ffocalors.sharedledger.ui.theme.SoftCharcoal
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonTone
import com.ffocalors.sharedledger.BuildConfig

/** The two authentication forms available on [AuthScreen]. */
enum class AuthMode {
    Login,
    Register,
}

/**
 * SharedLedger's login and registration entry point.
 *
 * The screen owns only presentation state and local validation. Authentication
 * is intentionally supplied by the integration layer through [onLogin] and
 * [onRegister]; [isLoading] and [errorMessage] represent the external request
 * state and do not require an SDK in this UI module.
 */
@Composable
fun AuthScreen(
    modifier: Modifier = Modifier,
    initialMode: AuthMode = AuthMode.Login,
    isLoading: Boolean = false,
    errorMessage: String? = null,
    showDemoCredentials: Boolean = BuildConfig.DEBUG,
    showDemoRegistrationNotice: Boolean = BuildConfig.DEBUG,
    onLogin: ((email: String, password: String) -> Unit)? = null,
    onRegister: ((nickname: String, email: String, password: String) -> Unit)? = null,
    onForgotPassword: ((email: String) -> Unit)? = null,
) {
    var isRegisterMode by rememberSaveable {
        mutableStateOf(initialMode == AuthMode.Register)
    }
    var loginEmail by rememberSaveable { mutableStateOf("") }
    var loginPassword by rememberSaveable { mutableStateOf("") }
    var registerNickname by rememberSaveable { mutableStateOf("") }
    var registerEmail by rememberSaveable { mutableStateOf("") }
    var registerPassword by rememberSaveable { mutableStateOf("") }
    var registerConfirmPassword by rememberSaveable { mutableStateOf("") }
    var loginPasswordVisible by rememberSaveable { mutableStateOf(false) }
    var registerPasswordVisible by rememberSaveable { mutableStateOf(false) }
    var registerConfirmPasswordVisible by rememberSaveable { mutableStateOf(false) }

    var localErrorMessage by rememberSaveable { mutableStateOf<String?>(null) }
    var loginEmailError by rememberSaveable { mutableStateOf<String?>(null) }
    var loginPasswordError by rememberSaveable { mutableStateOf<String?>(null) }
    var registerNicknameError by rememberSaveable { mutableStateOf<String?>(null) }
    var registerEmailError by rememberSaveable { mutableStateOf<String?>(null) }
    var registerPasswordError by rememberSaveable { mutableStateOf<String?>(null) }
    var registerConfirmPasswordError by rememberSaveable { mutableStateOf<String?>(null) }

    fun clearValidationErrors() {
        localErrorMessage = null
        loginEmailError = null
        loginPasswordError = null
        registerNicknameError = null
        registerEmailError = null
        registerPasswordError = null
        registerConfirmPasswordError = null
    }

    val mode = if (isRegisterMode) AuthMode.Register else AuthMode.Login
    val formError = errorMessage ?: localErrorMessage

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(AppBackground)
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        // Center the Stitch-sized card when it fits; verticalScroll keeps every field reachable
        // after the IME reduces the available viewport.
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 480.dp)
                .shadow(
                    elevation = 8.dp,
                    shape = SharedLedgerRadius.ExtraLarge,
                    clip = false,
                )
                .clip(SharedLedgerRadius.ExtraLarge)
                .background(AppSurfaceLow)
                .padding(horizontal = 24.dp, vertical = 32.dp),
            verticalArrangement = Arrangement.spacedBy(32.dp),
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = "SharedLedger",
                    style = SharedLedgerTextStyles.PageTitle,
                    color = SageGreen,
                )
                Text(
                    text = "松弛、透明且可信的多人记账",
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = SoftCharcoal,
                )
            }

            AuthModeSelector(
                mode = mode,
                enabled = !isLoading,
                onModeSelected = { selectedMode ->
                    val nextIsRegister = selectedMode == AuthMode.Register
                    if (nextIsRegister != isRegisterMode) {
                        isRegisterMode = nextIsRegister
                        clearValidationErrors()
                    }
                },
            )

            if (showDemoCredentials) {
                DemoCredentialsHint()
            }

            AnimatedContent(
                targetState = mode,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = if (mode == AuthMode.Login) 380.dp else 460.dp),
                transitionSpec = {
                    if (targetState == AuthMode.Register) {
                        (slideInHorizontally { it } + fadeIn()) togetherWith
                            (slideOutHorizontally { -it } + fadeOut())
                    } else {
                        (slideInHorizontally { -it } + fadeIn()) togetherWith
                            (slideOutHorizontally { it } + fadeOut())
                    }
                },
                label = "authentication form transition",
            ) { displayedMode ->
                when (displayedMode) {
                    AuthMode.Login -> LoginForm(
                        email = loginEmail,
                        password = loginPassword,
                        passwordVisible = loginPasswordVisible,
                        emailError = loginEmailError,
                        passwordError = loginPasswordError,
                        formError = formError,
                        isLoading = isLoading,
                        submitAvailable = onLogin != null,
                        onEmailChange = {
                            loginEmail = it
                            loginEmailError = null
                            localErrorMessage = null
                        },
                        onPasswordChange = {
                            loginPassword = it
                            loginPasswordError = null
                            localErrorMessage = null
                        },
                        onTogglePassword = {
                            loginPasswordVisible = !loginPasswordVisible
                        },
                        onForgotPassword = onForgotPassword?.let { callback -> { callback(loginEmail.trim()) } },
                        onSubmit = {
                            val normalizedEmail = loginEmail.trim()
                            val emailProblem = when {
                                normalizedEmail.isBlank() -> "请输入邮箱"
                                !isValidEmail(normalizedEmail) -> "请输入正确的邮箱地址"
                                else -> null
                            }
                            val passwordProblem = when {
                                loginPassword.isBlank() -> "请输入密码"
                                loginPassword.length < 6 -> "密码至少 6 位"
                                else -> null
                            }
                            loginEmailError = emailProblem
                            loginPasswordError = passwordProblem
                            localErrorMessage = if (emailProblem == null && passwordProblem == null) {
                                null
                            } else {
                                "请输入正确的邮箱或密码"
                            }
                            if (emailProblem == null && passwordProblem == null) {
                                onLogin?.invoke(normalizedEmail, loginPassword)
                            }
                        },
                    )

                    AuthMode.Register -> RegisterForm(
                        nickname = registerNickname,
                        email = registerEmail,
                        password = registerPassword,
                        confirmPassword = registerConfirmPassword,
                        passwordVisible = registerPasswordVisible,
                        confirmPasswordVisible = registerConfirmPasswordVisible,
                        nicknameError = registerNicknameError,
                        emailError = registerEmailError,
                        passwordError = registerPasswordError,
                        confirmPasswordError = registerConfirmPasswordError,
                        formError = formError,
                        showDemoRegistrationNotice = showDemoRegistrationNotice,
                        isLoading = isLoading,
                        submitAvailable = onRegister != null,
                        onNicknameChange = {
                            registerNickname = it
                            registerNicknameError = null
                            localErrorMessage = null
                        },
                        onEmailChange = {
                            registerEmail = it
                            registerEmailError = null
                            localErrorMessage = null
                        },
                        onPasswordChange = {
                            registerPassword = it
                            registerPasswordError = null
                            localErrorMessage = null
                        },
                        onConfirmPasswordChange = {
                            registerConfirmPassword = it
                            registerConfirmPasswordError = null
                            localErrorMessage = null
                        },
                        onTogglePassword = {
                            registerPasswordVisible = !registerPasswordVisible
                        },
                        onToggleConfirmPassword = {
                            registerConfirmPasswordVisible = !registerConfirmPasswordVisible
                        },
                        onSubmit = {
                            val normalizedEmail = registerEmail.trim()
                            val nicknameProblem = if (registerNickname.isBlank()) "请输入昵称" else null
                            val emailProblem = when {
                                normalizedEmail.isBlank() -> "请输入邮箱"
                                !isValidEmail(normalizedEmail) -> "请输入正确的邮箱地址"
                                else -> null
                            }
                            val passwordProblem = when {
                                registerPassword.isBlank() -> "请输入密码"
                                registerPassword.length < 6 -> "密码至少 6 位"
                                else -> null
                            }
                            val confirmProblem = when {
                                registerConfirmPassword.isBlank() -> "请确认密码"
                                registerConfirmPassword != registerPassword -> "两次输入的密码不一致"
                                else -> null
                            }
                            registerNicknameError = nicknameProblem
                            registerEmailError = emailProblem
                            registerPasswordError = passwordProblem
                            registerConfirmPasswordError = confirmProblem
                            localErrorMessage = if (
                                nicknameProblem == null &&
                                    emailProblem == null &&
                                    passwordProblem == null &&
                                    confirmProblem == null
                            ) {
                                null
                            } else {
                                "请检查您的输入信息"
                            }
                            if (
                                nicknameProblem == null &&
                                    emailProblem == null &&
                                    passwordProblem == null &&
                                    confirmProblem == null
                            ) {
                                onRegister?.invoke(
                                    registerNickname.trim(),
                                    normalizedEmail,
                                    registerPassword,
                                )
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun AuthModeSelector(
    mode: AuthMode,
    enabled: Boolean,
    onModeSelected: (AuthMode) -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .height(48.dp),
        shape = SharedLedgerRadius.Full,
        color = Neutral,
    ) {
        Row(modifier = Modifier.padding(4.dp)) {
            AuthModeTab(
                text = "登录",
                selected = mode == AuthMode.Login,
                enabled = enabled,
                onClick = { onModeSelected(AuthMode.Login) },
                modifier = Modifier.weight(1f),
            )
            AuthModeTab(
                text = "注册",
                selected = mode == AuthMode.Register,
                enabled = enabled,
                onClick = { onModeSelected(AuthMode.Register) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun AuthModeTab(
    text: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .height(40.dp)
            .semantics {
                contentDescription = if (selected) "$text（当前）" else text
            },
        onClick = onClick,
        enabled = enabled,
        shape = SharedLedgerRadius.Full,
        color = if (selected) SoftPrimary else Color.Transparent,
        shadowElevation = if (selected) 1.dp else 0.dp,
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = text,
                style = SharedLedgerTextStyles.CardTitle,
                color = if (selected) SoftPrimaryContent else NeutralContent,
            )
        }
    }
}

@Composable
private fun LoginForm(
    email: String,
    password: String,
    passwordVisible: Boolean,
    emailError: String?,
    passwordError: String?,
    formError: String?,
    isLoading: Boolean,
    submitAvailable: Boolean,
    onEmailChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onTogglePassword: () -> Unit,
    onForgotPassword: (() -> Unit)?,
    onSubmit: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        AuthFormError(message = formError)
        AuthTextField(
            value = email,
            onValueChange = onEmailChange,
            placeholder = "邮箱",
            fieldDescription = "邮箱输入框",
            errorText = emailError,
            keyboardType = KeyboardType.Email,
            enabled = !isLoading,
        )
        AuthPasswordField(
            value = password,
            onValueChange = onPasswordChange,
            placeholder = "密码",
            fieldDescription = "密码输入框",
            passwordVisible = passwordVisible,
            errorText = passwordError,
            onToggleVisibility = onTogglePassword,
            enabled = !isLoading,
        )
        onForgotPassword?.let { callback ->
            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                TextButton(
                    onClick = callback,
                    enabled = !isLoading,
                    contentPadding = PaddingValues(0.dp),
                    modifier = Modifier.semantics { contentDescription = "忘记密码" },
                ) {
                    Text(
                        text = "忘记密码？",
                        style = SharedLedgerTextStyles.Label,
                        color = NeutralContent.copy(alpha = 0.72f),
                    )
                }
            }
        }
        if (submitAvailable) {
            AuthSubmitButton(
                text = "登录",
                loadingText = "登录中…",
                tone = SharedLedgerButtonTone.WarmSecondary,
                isLoading = isLoading,
                onClick = onSubmit,
            )
        }
    }
}

@Composable
private fun RegisterForm(
    nickname: String,
    email: String,
    password: String,
    confirmPassword: String,
    passwordVisible: Boolean,
    confirmPasswordVisible: Boolean,
    nicknameError: String?,
    emailError: String?,
    passwordError: String?,
    confirmPasswordError: String?,
    formError: String?,
    showDemoRegistrationNotice: Boolean,
    isLoading: Boolean,
    submitAvailable: Boolean,
    onNicknameChange: (String) -> Unit,
    onEmailChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onConfirmPasswordChange: (String) -> Unit,
    onTogglePassword: () -> Unit,
    onToggleConfirmPassword: () -> Unit,
    onSubmit: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        AuthFormError(message = formError)
        if (showDemoRegistrationNotice) {
            Text(
                text = "演示回调：注册不会写入 Supabase，仅进入示例首页。",
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 4.dp, vertical = 0.dp),
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        AuthTextField(
            value = nickname,
            onValueChange = onNicknameChange,
            placeholder = "昵称",
            fieldDescription = "昵称输入框",
            errorText = nicknameError,
            enabled = !isLoading,
        )
        AuthTextField(
            value = email,
            onValueChange = onEmailChange,
            placeholder = "邮箱",
            fieldDescription = "邮箱输入框",
            errorText = emailError,
            keyboardType = KeyboardType.Email,
            enabled = !isLoading,
        )
        AuthPasswordField(
            value = password,
            onValueChange = onPasswordChange,
            placeholder = "密码",
            fieldDescription = "密码输入框",
            passwordVisible = passwordVisible,
            errorText = passwordError,
            onToggleVisibility = onTogglePassword,
            enabled = !isLoading,
        )
        AuthPasswordField(
            value = confirmPassword,
            onValueChange = onConfirmPasswordChange,
            placeholder = "确认密码",
            fieldDescription = "确认密码输入框",
            passwordVisible = confirmPasswordVisible,
            errorText = confirmPasswordError,
            onToggleVisibility = onToggleConfirmPassword,
            enabled = !isLoading,
        )
        if (submitAvailable) {
            AuthSubmitButton(
                text = "注册",
                loadingText = "注册中…",
                tone = SharedLedgerButtonTone.SoftPrimary,
                isLoading = isLoading,
                onClick = onSubmit,
            )
        }
    }
}

@Composable
private fun DemoCredentialsHint() {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 32.dp, max = 40.dp)
            .semantics {
                contentDescription = "Debug 演示管理员账号：admin@sharedledger.test，密码：Admin123!"
            },
        shape = SharedLedgerRadius.Medium,
        color = Color.Transparent,
    ) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "Debug 演示管理员（可直接输入）：admin@sharedledger.test / Admin123!",
                modifier = Modifier.padding(horizontal = 4.dp),
                style = SharedLedgerTextStyles.Label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
            )
        }
    }
}

@Composable
private fun AuthFormError(message: String?) {
    if (message != null) {
        Text(
            text = message,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .semantics { liveRegion = LiveRegionMode.Polite },
            style = SharedLedgerTextStyles.Label,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun AuthTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    fieldDescription: String,
    errorText: String?,
    keyboardType: KeyboardType = KeyboardType.Text,
    enabled: Boolean,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        AuthBasicTextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = placeholder,
            fieldDescription = fieldDescription,
            keyboardType = keyboardType,
            errorText = errorText,
            enabled = enabled,
            trailingContent = null,
        )
        AuthFieldError(errorText)
    }
}

@Composable
private fun AuthPasswordField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    fieldDescription: String,
    passwordVisible: Boolean,
    errorText: String?,
    onToggleVisibility: () -> Unit,
    enabled: Boolean,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        AuthBasicTextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = placeholder,
            fieldDescription = fieldDescription,
            keyboardType = KeyboardType.Password,
            errorText = errorText,
            enabled = enabled,
            visualTransformation = if (passwordVisible) {
                VisualTransformation.None
            } else {
                PasswordVisualTransformation()
            },
            trailingContent = {
                IconButton(
                    onClick = onToggleVisibility,
                    enabled = enabled,
                    modifier = Modifier.semantics {
                        contentDescription = if (passwordVisible) "隐藏密码" else "显示密码"
                    },
                ) {
                    Icon(
                        imageVector = if (passwordVisible) Icons.Rounded.Visibility else Icons.Rounded.VisibilityOff,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
        )
        AuthFieldError(errorText)
    }
}

/** BasicTextField keeps the controlled form semantics while giving the Stitch layout exact 24dp
 * horizontal content padding, which the String overload of Material3 OutlinedTextField lacks. */
@Composable
private fun AuthBasicTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    fieldDescription: String,
    keyboardType: KeyboardType,
    errorText: String?,
    enabled: Boolean,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    trailingContent: (@Composable () -> Unit)?,
) {
    var focused by rememberSaveable(fieldDescription) { mutableStateOf(false) }
    val borderColor = when {
        errorText != null -> MaterialTheme.colorScheme.error
        focused -> SageGreen
        else -> AppOutlineVariant.copy(alpha = 0.9f)
    }
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .onFocusChanged { focused = it.isFocused }
            .semantics { contentDescription = fieldDescription },
        enabled = enabled,
        singleLine = true,
        textStyle = SharedLedgerTextStyles.Body.copy(color = MaterialTheme.colorScheme.onSurface),
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        visualTransformation = visualTransformation,
        decorationBox = { innerTextField ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .border(1.dp, borderColor, RoundedCornerShape(12.dp))
                    .background(SurfaceWarmLowest, RoundedCornerShape(12.dp))
                    .padding(
                        horizontal = 24.dp,
                        // Keep the 48dp password affordance inside the same 56dp field shell.
                        vertical = if (trailingContent == null) 16.dp else 4.dp,
                    ),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(modifier = Modifier.weight(1f)) {
                    if (value.isEmpty()) {
                        Text(text = placeholder, style = SharedLedgerTextStyles.Body)
                    }
                    innerTextField()
                }
                trailingContent?.invoke()
            }
        },
    )
}

@Composable
private fun AuthFieldError(errorText: String?) {
    if (errorText != null) {
        Text(
            text = errorText,
            modifier = Modifier.padding(start = 16.dp),
            style = SharedLedgerTextStyles.Label,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun AuthSubmitButton(
    text: String,
    loadingText: String,
    tone: SharedLedgerButtonTone,
    isLoading: Boolean,
    onClick: () -> Unit,
) {
    SharedLedgerButton(
        text = text,
        onClick = onClick,
        tone = tone,
        loading = isLoading,
        loadingText = loadingText,
    )
}

private fun isValidEmail(value: String): Boolean =
    Regex("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$").matches(value)

@Preview(name = "登录注册", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun AuthScreenPreview() {
    SharedLedgerTheme {
        AuthScreen()
    }
}
