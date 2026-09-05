package com.ffocalors.sharedledger.data.auth

import kotlinx.coroutines.flow.StateFlow

interface AuthRepository {
    val authState: StateFlow<AuthState>

    suspend fun initialize()

    suspend fun signIn(email: String, password: String): AuthResult

    suspend fun signUp(nickname: String, email: String, password: String): AuthResult

    suspend fun signOut(): AuthResult
}
