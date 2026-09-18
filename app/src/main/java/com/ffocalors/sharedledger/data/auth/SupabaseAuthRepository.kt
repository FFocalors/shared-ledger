package com.ffocalors.sharedledger.data.auth

import android.content.Intent
import android.net.Uri
import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.handleDeeplinks
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.auth.providers.builtin.Email
import io.github.jan.supabase.postgrest.from
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.coroutines.resume
import java.util.concurrent.atomic.AtomicLong

@Serializable
private data class ProfileDto(
    @SerialName("display_name") val displayName: String? = null,
    @SerialName("avatar_style") val avatarStyle: String? = null,
)

class SupabaseAuthRepository(
    private val client: SupabaseClient,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
) : AuthRepository {
    private val mutableAuthState = MutableStateFlow<AuthState>(AuthState.Loading)
    private val sessionEpoch = AtomicLong(0L)
    private val observerLock = Any()
    private var sessionObserverStarted = false

    override val authState: StateFlow<AuthState> = mutableAuthState

    override suspend fun initialize() {
        val shouldStartObserver = synchronized(observerLock) {
            if (sessionObserverStarted) {
                false
            } else {
                sessionObserverStarted = true
                true
            }
        }
        if (shouldStartObserver) {
            scope.launch {
                client.auth.sessionStatus.collect { status ->
                    when (status) {
                        SessionStatus.Initializing -> {
                            sessionEpoch.incrementAndGet()
                            mutableAuthState.value = AuthState.Loading
                        }
                        is SessionStatus.Authenticated -> {
                            val epoch = sessionEpoch.incrementAndGet()
                            publishCurrentUser(epoch)
                        }
                        is SessionStatus.RefreshFailure -> {
                            // A failed refresh means the session can no longer authorize
                            // requests. Publish an unauthenticated state so AuthGate can
                            // dispose all user-scoped view models and realtime subscriptions.
                            sessionEpoch.incrementAndGet()
                            mutableAuthState.value = AuthState.Unauthenticated
                        }
                        is SessionStatus.NotAuthenticated -> {
                            sessionEpoch.incrementAndGet()
                            mutableAuthState.value = AuthState.Unauthenticated
                        }
                    }
                }
            }
        }

        try {
            when (val initialStatus = client.auth.sessionStatus.first { it !is SessionStatus.Initializing }) {
                is SessionStatus.Authenticated -> {
                    if (client.auth.currentSessionOrNull() == null) {
                        sessionEpoch.incrementAndGet()
                        mutableAuthState.value = AuthState.Unauthenticated
                    } else {
                        publishCurrentUser(sessionEpoch.incrementAndGet())
                    }
                }
                is SessionStatus.NotAuthenticated,
                is SessionStatus.RefreshFailure -> {
                    sessionEpoch.incrementAndGet()
                    mutableAuthState.value = AuthState.Unauthenticated
                }
                SessionStatus.Initializing -> Unit
            }
        } catch (error: Throwable) {
            if (isSessionInvalid(error)) {
                sessionEpoch.incrementAndGet()
                mutableAuthState.value = AuthState.Unauthenticated
            } else {
                mutableAuthState.value = AuthState.Error(AuthErrorMapper.toUserMessage(error))
            }
        }
    }

    override suspend fun signIn(email: String, password: String): AuthResult = runAuthRequest {
        client.auth.signInWith(Email) {
            this.email = email
            this.password = password
        }
        publishCurrentUser(sessionEpoch.incrementAndGet())
        AuthResult.Success
    }

    override suspend fun signUp(nickname: String, email: String, password: String): AuthResult =
        runAuthRequest {
            client.auth.signUpWith(Email) {
                this.email = email
                this.password = password
                data = buildJsonObject { put("display_name", nickname) }
            }
            if (client.auth.currentSessionOrNull() == null) {
                sessionEpoch.incrementAndGet()
                mutableAuthState.value = AuthState.Unauthenticated
                AuthResult.NeedsEmailConfirmation("注册成功，请查收验证邮件后再登录")
            } else {
                publishCurrentUser(sessionEpoch.incrementAndGet())
                AuthResult.Success
            }
        }

    override suspend fun signOut(): AuthResult = runAuthRequest {
        // Invalidate any profile lookup that is still completing for the old account.
        sessionEpoch.incrementAndGet()
        client.auth.signOut()
        mutableAuthState.value = AuthState.Unauthenticated
        AuthResult.Success
    }

    override suspend fun requestPasswordReset(email: String, redirectUrl: String): AuthResult =
        try {
            client.auth.resetPasswordForEmail(email, redirectUrl = redirectUrl)
            AuthResult.Success
        } catch (error: Throwable) {
            // Keep account existence private. Transport and service failures remain actionable.
            AuthResult.Failure(AuthErrorMapper.toPasswordResetMessage(error))
        }

    override suspend fun updatePassword(newPassword: String): AuthResult = try {
        // Updating account credentials must not replace the global auth state with an
        // error. The caller can keep the authenticated screen visible and explain the
        // recoverable failure next to the password form.
        client.auth.updateUser { password = newPassword }
        AuthResult.Success
    } catch (error: Throwable) {
        AuthResult.Failure(AuthErrorMapper.toPasswordUpdateMessage(error))
    }

    override suspend fun updateAvatarStyle(styleId: String): AuthResult = try {
        val userId = client.auth.currentSessionOrNull()?.user?.id
            ?: return AuthResult.Failure("登录状态已失效，请重新登录")
        client.from("profiles").update({
            set("avatar_style", styleId)
        }) {
            filter { eq("id", userId) }
        }
        val current = mutableAuthState.value
        if (current is AuthState.Authenticated) {
            mutableAuthState.value = AuthState.Authenticated(current.user.copy(avatarStyle = styleId))
        }
        AuthResult.Success
    } catch (error: Throwable) {
        AuthResult.Failure(AuthErrorMapper.toUserMessage(error))
    }

    override suspend fun handlePasswordRecovery(deepLink: String): AuthResult {
        val uri = runCatching { Uri.parse(deepLink) }.getOrNull()
        if (uri == null || uri.scheme != "sharedledger" || uri.host != "auth") {
            return AuthResult.Failure("重置链接无效或已过期")
        }
        val hasRecoveryPayload = !uri.fragment.isNullOrBlank() || !uri.getQueryParameter("code").isNullOrBlank()
        if (!hasRecoveryPayload) return AuthResult.Failure("重置链接无效或已过期")

        return try {
            val result = withTimeoutOrNull(15_000L) {
                suspendCancellableCoroutine<AuthResult> { continuation ->
                    val intent = Intent(Intent.ACTION_VIEW, uri)
                    client.handleDeeplinks(
                        intent = intent,
                        onSessionSuccess = {
                            scope.launch {
                                if (continuation.isActive) {
                                    publishCurrentUser(sessionEpoch.incrementAndGet())
                                    continuation.resume(AuthResult.Success)
                                }
                            }
                        },
                        onError = { error ->
                            if (continuation.isActive) {
                                continuation.resume(AuthResult.Failure(AuthErrorMapper.toUserMessage(error)))
                            }
                        },
                    )
                }
            }
            result ?: AuthResult.Failure("重置链接无效或已过期")
        } catch (error: Throwable) {
            AuthResult.Failure(AuthErrorMapper.toUserMessage(error))
        }
    }

    private suspend fun publishCurrentUser(expectedEpoch: Long) {
        val session = client.auth.currentSessionOrNull()
        val user = session?.user
        if (user == null) {
            if (sessionEpoch.get() == expectedEpoch) {
                mutableAuthState.value = AuthState.Unauthenticated
            }
            return
        }
        val profile = runCatching {
            client.from("profiles").select {
                filter { eq("id", user.id) }
            }.decodeSingle<ProfileDto>()
        }.getOrNull()
        // Profile loading may outlive a logout or an account switch. Do not let that
        // late result restore the previous account's authenticated state.
        if (sessionEpoch.get() != expectedEpoch ||
            client.auth.currentSessionOrNull()?.user?.id != user.id
        ) return
        mutableAuthState.value = AuthState.Authenticated(
            AuthUser(
                id = user.id,
                email = user.email.orEmpty(),
                displayName = profile?.displayName?.takeIf(String::isNotBlank) ?: user.email.orEmpty(),
                avatarStyle = profile?.avatarStyle,
            ),
        )
    }

    private suspend fun runAuthRequest(block: suspend () -> AuthResult): AuthResult = try {
        block()
    } catch (error: Throwable) {
        val message = AuthErrorMapper.toUserMessage(error)
        mutableAuthState.value = AuthState.Error(message)
        AuthResult.Failure(message)
    }

    private fun isSessionInvalid(error: Throwable): Boolean {
        val message = error.message.orEmpty().lowercase()
        return message.contains("session") ||
            message.contains("refresh token") ||
            message.contains("jwt") && message.contains("expir")
    }
}

class UnavailableAuthRepository(
    private val message: String = "尚未配置 Supabase，请在 local.properties 中配置连接信息",
) : AuthRepository {
    private val mutableAuthState = MutableStateFlow<AuthState>(AuthState.Error(message))
    override val authState: StateFlow<AuthState> = mutableAuthState
    override suspend fun initialize() = Unit
    override suspend fun signIn(email: String, password: String) = AuthResult.Failure(message)
    override suspend fun signUp(nickname: String, email: String, password: String) = AuthResult.Failure(message)
    override suspend fun requestPasswordReset(email: String, redirectUrl: String) = AuthResult.Failure(message)
    override suspend fun updatePassword(newPassword: String) = AuthResult.Failure(message)
    override suspend fun updateAvatarStyle(styleId: String) = AuthResult.Failure(message)
    override suspend fun handlePasswordRecovery(deepLink: String) = AuthResult.Failure(message)
    override suspend fun signOut(): AuthResult {
        mutableAuthState.value = AuthState.Unauthenticated
        return AuthResult.Success
    }
}

object AuthRepositoryFactory {
    fun create(): AuthRepository = SupabaseClientProvider.createOrNull()?.let(::SupabaseAuthRepository)
        ?: UnavailableAuthRepository()
}
