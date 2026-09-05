package com.ffocalors.sharedledger.data.auth

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.auth.providers.builtin.Email
import io.github.jan.supabase.postgrest.from
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

@Serializable
private data class ProfileDto(
    @SerialName("display_name") val displayName: String? = null,
)

class SupabaseAuthRepository(
    private val client: SupabaseClient,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
) : AuthRepository {
    private val mutableAuthState = MutableStateFlow<AuthState>(AuthState.Loading)
    private var sessionObserverStarted = false

    override val authState: StateFlow<AuthState> = mutableAuthState

    override suspend fun initialize() {
        if (!sessionObserverStarted) {
            sessionObserverStarted = true
            scope.launch {
                client.auth.sessionStatus.collect { status ->
                    when (status) {
                        SessionStatus.Initializing -> mutableAuthState.value = AuthState.Loading
                        is SessionStatus.Authenticated -> publishCurrentUser()
                        is SessionStatus.RefreshFailure -> {
                            mutableAuthState.value = AuthState.Error("登录状态已失效，请重新登录")
                        }
                        is SessionStatus.NotAuthenticated -> {
                            mutableAuthState.value = AuthState.Unauthenticated
                        }
                    }
                }
            }
        }

        try {
            client.auth.sessionStatus.first { it !is SessionStatus.Initializing }
            if (client.auth.currentSessionOrNull() == null) {
                mutableAuthState.value = AuthState.Unauthenticated
            } else {
                publishCurrentUser()
            }
        } catch (error: Throwable) {
            mutableAuthState.value = AuthState.Error(AuthErrorMapper.toUserMessage(error))
        }
    }

    override suspend fun signIn(email: String, password: String): AuthResult = runAuthRequest {
        client.auth.signInWith(Email) {
            this.email = email
            this.password = password
        }
        publishCurrentUser()
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
                mutableAuthState.value = AuthState.Unauthenticated
                AuthResult.NeedsEmailConfirmation("注册成功，请查收验证邮件后再登录")
            } else {
                publishCurrentUser()
                AuthResult.Success
            }
        }

    override suspend fun signOut(): AuthResult = runAuthRequest {
        client.auth.signOut()
        mutableAuthState.value = AuthState.Unauthenticated
        AuthResult.Success
    }

    private suspend fun publishCurrentUser() {
        val session = client.auth.currentSessionOrNull()
        val user = session?.user
        if (user == null) {
            mutableAuthState.value = AuthState.Unauthenticated
            return
        }
        val profile = runCatching {
            client.from("profiles").select {
                filter { eq("id", user.id) }
            }.decodeSingle<ProfileDto>()
        }.getOrNull()
        mutableAuthState.value = AuthState.Authenticated(
            AuthUser(
                id = user.id,
                email = user.email.orEmpty(),
                displayName = profile?.displayName?.takeIf(String::isNotBlank) ?: user.email.orEmpty(),
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
}

class UnavailableAuthRepository(
    private val message: String = "尚未配置 Supabase，请在 local.properties 中配置连接信息",
) : AuthRepository {
    private val mutableAuthState = MutableStateFlow<AuthState>(AuthState.Error(message))
    override val authState: StateFlow<AuthState> = mutableAuthState
    override suspend fun initialize() = Unit
    override suspend fun signIn(email: String, password: String) = AuthResult.Failure(message)
    override suspend fun signUp(nickname: String, email: String, password: String) = AuthResult.Failure(message)
    override suspend fun signOut(): AuthResult {
        mutableAuthState.value = AuthState.Unauthenticated
        return AuthResult.Success
    }
}

object AuthRepositoryFactory {
    fun create(): AuthRepository = SupabaseClientProvider.createOrNull()?.let(::SupabaseAuthRepository)
        ?: UnavailableAuthRepository()
}
