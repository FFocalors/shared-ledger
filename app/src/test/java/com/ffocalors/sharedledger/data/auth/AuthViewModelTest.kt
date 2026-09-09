package com.ffocalors.sharedledger.data.auth

import com.ffocalors.sharedledger.ui.auth.AuthViewModel
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AuthViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun startupWithoutSessionBecomesUnauthenticated() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(initialState = AuthState.Loading)
        val viewModel = AuthViewModel(repository)

        assertEquals(AuthState.Loading, viewModel.uiState.value.authState)
        advanceUntilIdle()

        assertEquals(AuthState.Unauthenticated, viewModel.uiState.value.authState)
        assertFalse(viewModel.uiState.value.isSubmitting)
    }

    @Test
    fun startupRestoresExistingSession() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val user = AuthUser("user-1", "test@example.com", "测试用户")
        val repository = FakeAuthRepository(AuthState.Authenticated(user))
        val viewModel = AuthViewModel(repository)

        advanceUntilIdle()

        assertEquals(AuthState.Authenticated(user), viewModel.uiState.value.authState)
    }

    @Test
    fun loginSuccessAndLogoutUpdateAuthState() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(AuthState.Unauthenticated)
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.signIn("test@example.com", "password")
        advanceUntilIdle()
        assertTrue(viewModel.uiState.value.authState is AuthState.Authenticated)

        viewModel.signOut()
        advanceUntilIdle()
        assertEquals(AuthState.Unauthenticated, viewModel.uiState.value.authState)
    }

    @Test
    fun loginFailureIsUserReadableAndDoesNotCrash() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(AuthState.Unauthenticated).apply {
            nextSignIn = AuthResult.Failure("邮箱或密码错误")
        }
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.signIn("test@example.com", "wrong")
        advanceUntilIdle()

        assertEquals("邮箱或密码错误", viewModel.uiState.value.message)
        assertFalse(viewModel.uiState.value.isSubmitting)
        assertEquals(1, repository.signInCalls)
    }

    @Test
    fun registrationSuccessAndEmailConfirmationAreRepresented() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(AuthState.Unauthenticated)
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.signUp("测试用户", "test@example.com", "password")
        advanceUntilIdle()
        assertTrue(viewModel.uiState.value.authState is AuthState.Authenticated)

        repository.nextSignUp = AuthResult.NeedsEmailConfirmation("注册成功，请查收验证邮件后再登录")
        viewModel.signOut()
        advanceUntilIdle()
        viewModel.signUp("测试用户", "test@example.com", "password")
        advanceUntilIdle()
        assertEquals("注册成功，请查收验证邮件后再登录", viewModel.uiState.value.message)
    }

    @Test
    fun registrationFailureIsExposedWithoutRawException() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(AuthState.Unauthenticated).apply {
            nextSignUp = AuthResult.Failure("该邮箱已注册，请直接登录")
        }
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.signUp("测试用户", "test@example.com", "password")
        advanceUntilIdle()
        assertEquals("该邮箱已注册，请直接登录", viewModel.uiState.value.message)
        assertFalse(viewModel.uiState.value.isSubmitting)
    }

    @Test
    fun sessionExpiryReturnsToUnauthenticatedAuthState() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(
            AuthState.Authenticated(AuthUser("user-1", "test@example.com", "测试用户")),
        )
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        repository.expireSession()
        advanceUntilIdle()
        assertEquals(AuthState.Unauthenticated, viewModel.uiState.value.authState)
        assertEquals("登录状态已失效，请重新登录", viewModel.uiState.value.message)
    }

    @Test
    fun repeatedSubmitIsIgnoredWhileRequestIsInFlight() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<AuthResult>()
        val repository = FakeAuthRepository(AuthState.Unauthenticated).apply {
            signInGate = gate
        }
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.signIn("test@example.com", "password")
        viewModel.signIn("test@example.com", "password")
        advanceUntilIdle()
        assertEquals(1, repository.signInCalls)
        assertTrue(viewModel.uiState.value.isSubmitting)

        gate.complete(AuthResult.Success)
        advanceUntilIdle()
        assertFalse(viewModel.uiState.value.isSubmitting)
        assertTrue(viewModel.uiState.value.authState is AuthState.Authenticated)
    }

    @Test
    fun errorMapperHidesSdkAndNetworkDetails() {
        assertEquals("邮箱或密码错误", AuthErrorMapper.toUserMessage(Exception("Invalid login credentials")))
        assertEquals("该邮箱已注册，请直接登录", AuthErrorMapper.toUserMessage(Exception("User already registered")))
        assertEquals("网络连接失败，请检查网络后重试", AuthErrorMapper.toUserMessage(IOException("connection reset")))
        assertEquals("请求失败，请稍后重试", AuthErrorMapper.toUserMessage(Exception("postgresql detail with secret")))
        assertEquals("登录状态已失效，请重新登录", AuthErrorMapper.toUserMessage(Exception("JWT expired")))
        assertEquals(
            AuthErrorMapper.PASSWORD_RESET_SENT_MESSAGE,
            AuthErrorMapper.toPasswordResetMessage(Exception("user not found")),
        )
        assertEquals(
            "网络连接失败，请检查网络后重试",
            AuthErrorMapper.toPasswordResetMessage(IOException("connection reset")),
        )
        assertEquals(
            "新密码不能与当前密码相同",
            AuthErrorMapper.toPasswordUpdateMessage(Exception("New password should be different from the old password")),
        )
        assertEquals(
            "当前登录时间过久，请退出后重新登录再修改密码",
            AuthErrorMapper.toPasswordUpdateMessage(Exception("Reauthentication nonce is required")),
        )
        assertEquals(
            "密码修改失败，请稍后重试",
            AuthErrorMapper.toPasswordUpdateMessage(Exception("internal auth detail")),
        )
    }

    @Test
    fun passwordResetUsesGenericSuccessMessage() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(AuthState.Unauthenticated)
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.requestPasswordReset("test@example.com")
        advanceUntilIdle()

        assertEquals(AuthErrorMapper.PASSWORD_RESET_SENT_MESSAGE, viewModel.uiState.value.message)
        assertEquals("test@example.com", repository.resetEmail)
        assertEquals(AuthRedirects.PASSWORD_RESET, repository.resetRedirect)
    }

    @Test
    fun recoverySessionCanSetPasswordAndRequiresFreshLogin() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeAuthRepository(AuthState.Unauthenticated).apply {
            nextRecovery = AuthResult.Success
            nextPasswordUpdate = AuthResult.Success
        }
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.handlePasswordRecoveryLink(AuthRedirects.PASSWORD_RESET)
        advanceUntilIdle()
        assertTrue(viewModel.uiState.value.isPasswordRecovery)

        viewModel.updatePassword("new-password")
        advanceUntilIdle()

        assertFalse(viewModel.uiState.value.isPasswordRecovery)
        assertEquals(AuthState.Unauthenticated, viewModel.uiState.value.authState)
        assertEquals("密码已更新，请使用新密码登录", viewModel.uiState.value.message)
        assertEquals("new-password", repository.updatedPassword)
    }

    @Test
    fun accountPasswordChangeValidatesBeforeCallingRepository() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val user = AuthUser("user-1", "test@example.com", "测试用户")
        val repository = FakeAuthRepository(AuthState.Authenticated(user))
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.changeAccountPassword("short", "short")
        assertEquals("新密码至少需要 8 个字符", viewModel.uiState.value.passwordChange.message)
        assertEquals(0, repository.passwordUpdateCalls)

        viewModel.changeAccountPassword("onlyletters", "onlyletters")
        assertEquals("新密码需同时包含字母和数字", viewModel.uiState.value.passwordChange.message)
        assertEquals(0, repository.passwordUpdateCalls)

        viewModel.changeAccountPassword("new-password1", "different-password1")
        assertEquals("两次输入的密码不一致", viewModel.uiState.value.passwordChange.message)
        assertEquals(0, repository.passwordUpdateCalls)
    }

    @Test
    fun accountPasswordChangeKeepsAuthenticatedSessionOnSuccess() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val user = AuthUser("user-1", "test@example.com", "测试用户")
        val repository = FakeAuthRepository(AuthState.Authenticated(user)).apply {
            nextPasswordUpdate = AuthResult.Success
        }
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.changeAccountPassword("new-password1", "new-password1")
        advanceUntilIdle()

        assertEquals(AuthState.Authenticated(user), viewModel.uiState.value.authState)
        assertTrue(viewModel.uiState.value.passwordChange.isSuccess)
        assertEquals("登录密码已更新", viewModel.uiState.value.passwordChange.message)
        assertEquals(0, repository.signOutCalls)
        assertEquals("new-password1", repository.updatedPassword)
    }

    @Test
    fun accountPasswordChangeFailureStaysOnAuthenticatedScreen() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val user = AuthUser("user-1", "test@example.com", "测试用户")
        val repository = FakeAuthRepository(AuthState.Authenticated(user)).apply {
            nextPasswordUpdate = AuthResult.Failure("当前登录时间过久，请退出后重新登录再修改密码")
        }
        val viewModel = AuthViewModel(repository)
        advanceUntilIdle()

        viewModel.changeAccountPassword("new-password1", "new-password1")
        advanceUntilIdle()

        assertEquals(AuthState.Authenticated(user), viewModel.uiState.value.authState)
        assertFalse(viewModel.uiState.value.passwordChange.isSuccess)
        assertEquals(
            "当前登录时间过久，请退出后重新登录再修改密码",
            viewModel.uiState.value.passwordChange.message,
        )
        assertFalse(viewModel.uiState.value.passwordChange.isSubmitting)
    }

    private class FakeAuthRepository(initialState: AuthState) : AuthRepository {
        private val mutableState = MutableStateFlow(initialState)
        override val authState: StateFlow<AuthState> = mutableState
        var nextSignIn: AuthResult = AuthResult.Success
        var nextSignUp: AuthResult = AuthResult.Success
        var signInGate: CompletableDeferred<AuthResult>? = null
        var signInCalls = 0
        var nextRecovery: AuthResult = AuthResult.Failure("重置链接无效或已过期")
        var nextPasswordUpdate: AuthResult = AuthResult.Failure("密码更新失败")
        var resetEmail: String? = null
        var resetRedirect: String? = null
        var updatedPassword: String? = null
        var passwordUpdateCalls = 0
        var signOutCalls = 0

        override suspend fun initialize() {
            if (mutableState.value == AuthState.Loading) mutableState.value = AuthState.Unauthenticated
        }

        override suspend fun signIn(email: String, password: String): AuthResult {
            signInCalls++
            val result = signInGate?.await() ?: nextSignIn
            if (result is AuthResult.Success) {
                mutableState.value = AuthState.Authenticated(AuthUser("user-1", email, "测试用户"))
            } else if (result is AuthResult.Failure) {
                mutableState.value = AuthState.Error(result.message)
            }
            return result
        }

        override suspend fun signUp(nickname: String, email: String, password: String): AuthResult {
            if (nextSignUp is AuthResult.Success) {
                mutableState.value = AuthState.Authenticated(AuthUser("user-1", email, nickname))
            }
            return nextSignUp
        }

        override suspend fun signOut(): AuthResult {
            signOutCalls++
            mutableState.value = AuthState.Unauthenticated
            return AuthResult.Success
        }

        override suspend fun requestPasswordReset(email: String, redirectUrl: String): AuthResult {
            resetEmail = email
            resetRedirect = redirectUrl
            return AuthResult.Success
        }

        override suspend fun handlePasswordRecovery(deepLink: String): AuthResult {
            if (nextRecovery == AuthResult.Success) {
                mutableState.value = AuthState.Authenticated(AuthUser("user-1", "test@example.com", "测试用户"))
            }
            return nextRecovery
        }

        override suspend fun updatePassword(newPassword: String): AuthResult {
            passwordUpdateCalls++
            updatedPassword = newPassword
            return nextPasswordUpdate
        }

        fun expireSession() {
            mutableState.value = AuthState.Unauthenticated
        }
    }
}
