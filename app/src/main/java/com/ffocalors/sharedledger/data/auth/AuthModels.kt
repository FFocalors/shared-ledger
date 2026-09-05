package com.ffocalors.sharedledger.data.auth

data class AuthUser(
    val id: String,
    val email: String,
    val displayName: String,
)

sealed interface AuthState {
    data object Loading : AuthState
    data object Unauthenticated : AuthState
    data class Authenticated(val user: AuthUser) : AuthState
    data class Error(val message: String) : AuthState
}

sealed interface AuthResult {
    data object Success : AuthResult
    data class NeedsEmailConfirmation(val message: String) : AuthResult
    data class Failure(val message: String) : AuthResult
}
