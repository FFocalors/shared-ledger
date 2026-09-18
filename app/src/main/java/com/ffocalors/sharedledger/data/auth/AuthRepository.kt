package com.ffocalors.sharedledger.data.auth

import kotlinx.coroutines.flow.StateFlow

interface AuthRepository {
    val authState: StateFlow<AuthState>

    suspend fun initialize()

    suspend fun signIn(email: String, password: String): AuthResult

    suspend fun signUp(nickname: String, email: String, password: String): AuthResult

    suspend fun signOut(): AuthResult

    /** Requests a reset email without disclosing whether the address is registered. */
    suspend fun requestPasswordReset(email: String, redirectUrl: String): AuthResult =
        AuthResult.Failure("请求失败，请稍后重试")

    /** Updates the password while the recovery session is active. */
    suspend fun updatePassword(newPassword: String): AuthResult =
        AuthResult.Failure("请求失败，请稍后重试")

    /** Imports the session carried by the Supabase recovery deep link. */
    suspend fun handlePasswordRecovery(deepLink: String): AuthResult =
        AuthResult.Failure("重置链接无效或已过期")

    /** Persists the user's chosen avatar gradient style. */
    suspend fun updateAvatarStyle(styleId: String): AuthResult =
        AuthResult.Failure("请求失败，请稍后重试")
}

object AuthRedirects {
    const val PASSWORD_RESET = "sharedledger://auth/reset"
}
