package com.ffocalors.sharedledger.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.auth.AuthRepository
import com.ffocalors.sharedledger.data.auth.AuthResult
import com.ffocalors.sharedledger.data.auth.AuthState
import com.ffocalors.sharedledger.data.auth.AuthErrorMapper
import com.ffocalors.sharedledger.data.auth.AuthRedirects
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

data class AuthUiState(
    val authState: AuthState = AuthState.Loading,
    val isSubmitting: Boolean = false,
    val message: String? = null,
    val isPasswordRecovery: Boolean = false,
)

class AuthViewModel(private val repository: AuthRepository) : ViewModel() {
    private val mutableUiState = MutableStateFlow(AuthUiState())
    private var requestInFlight = false
    private var suppressSessionExpiryMessage = false
    val uiState: StateFlow<AuthUiState> = mutableUiState.asStateFlow()

    init {
        viewModelScope.launch {
            repository.authState.collect { state ->
                val previousState = mutableUiState.value.authState
                val sessionExpired = state == AuthState.Unauthenticated &&
                    previousState is AuthState.Authenticated &&
                    !suppressSessionExpiryMessage
                mutableUiState.value = mutableUiState.value.copy(
                    authState = state,
                    message = when {
                        state is AuthState.Error -> state.message
                        sessionExpired -> "登录状态已失效，请重新登录"
                        else -> mutableUiState.value.message
                    },
                )
            }
        }
        viewModelScope.launch { repository.initialize() }
    }

    fun signIn(email: String, password: String) {
        suppressSessionExpiryMessage = false
        submit(request = { repository.signIn(email, password) })
    }

    fun signUp(nickname: String, email: String, password: String) {
        suppressSessionExpiryMessage = false
        submit(request = { repository.signUp(nickname, email, password) })
    }

    fun signOut() {
        suppressSessionExpiryMessage = true
        submit(request = { repository.signOut() }, clearMessageOnSuccess = true)
    }

    fun requestPasswordReset(email: String) {
        val normalizedEmail = email.trim()
        if (normalizedEmail.isBlank()) {
            showMessage("请输入邮箱后再申请重置密码")
            return
        }
        if (!Regex("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$").matches(normalizedEmail)) {
            showMessage("请输入正确的邮箱地址")
            return
        }
        submit(
            request = { repository.requestPasswordReset(normalizedEmail, AuthRedirects.PASSWORD_RESET) },
            successMessage = AuthErrorMapper.PASSWORD_RESET_SENT_MESSAGE,
        )
    }

    fun handlePasswordRecoveryLink(deepLink: String) {
        if (requestInFlight || deepLink.isBlank()) return
        requestInFlight = true
        mutableUiState.value = mutableUiState.value.copy(
            isSubmitting = true,
            isPasswordRecovery = true,
            message = null,
        )
        viewModelScope.launch {
            val result = repository.handlePasswordRecovery(deepLink)
            mutableUiState.value = mutableUiState.value.copy(
                isSubmitting = false,
                isPasswordRecovery = result is AuthResult.Success,
                message = when (result) {
                    AuthResult.Success -> null
                    is AuthResult.NeedsEmailConfirmation -> result.message
                    is AuthResult.Failure -> result.message
                },
            )
            requestInFlight = false
        }
    }

    fun updatePassword(newPassword: String) {
        if (requestInFlight) return
        requestInFlight = true
        mutableUiState.value = mutableUiState.value.copy(isSubmitting = true, message = null)
        viewModelScope.launch {
            val result = repository.updatePassword(newPassword)
            if (result == AuthResult.Success) {
                // The recovery session is deliberately one-shot. The user signs in again with
                // the new password, which also gives a clear end to the recovery flow.
                repository.signOut()
                mutableUiState.value = mutableUiState.value.copy(
                    authState = AuthState.Unauthenticated,
                    isSubmitting = false,
                    isPasswordRecovery = false,
                    message = "密码已更新，请使用新密码登录",
                )
            } else {
                mutableUiState.value = mutableUiState.value.copy(
                    isSubmitting = false,
                    message = when (result) {
                        is AuthResult.NeedsEmailConfirmation -> result.message
                        is AuthResult.Failure -> result.message
                        AuthResult.Success -> null
                    },
                )
            }
            requestInFlight = false
        }
    }

    fun showMessage(message: String) {
        mutableUiState.value = mutableUiState.value.copy(message = message)
    }

    private fun submit(
        request: suspend () -> AuthResult,
        successMessage: String? = null,
        clearMessageOnSuccess: Boolean = false,
    ) {
        if (requestInFlight) return
        requestInFlight = true
        mutableUiState.value = mutableUiState.value.copy(isSubmitting = true, message = null)
        viewModelScope.launch {
            val result = request()
            val resultMessage = when (result) {
                AuthResult.Success -> successMessage
                is AuthResult.NeedsEmailConfirmation -> result.message
                is AuthResult.Failure -> result.message
            }
            mutableUiState.value = mutableUiState.value.copy(
                isSubmitting = false,
                message = if (result == AuthResult.Success && clearMessageOnSuccess) {
                    null
                } else {
                    resultMessage ?: mutableUiState.value.message
                },
            )
            if (clearMessageOnSuccess) suppressSessionExpiryMessage = false
            requestInFlight = false
        }
    }

    class Factory(private val repository: AuthRepository) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(AuthViewModel::class.java))
            return AuthViewModel(repository) as T
        }
    }
}
