package com.ffocalors.sharedledger.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.auth.AuthRepository
import com.ffocalors.sharedledger.data.auth.AuthResult
import com.ffocalors.sharedledger.data.auth.AuthState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

data class AuthUiState(
    val authState: AuthState = AuthState.Loading,
    val isSubmitting: Boolean = false,
    val message: String? = null,
)

class AuthViewModel(private val repository: AuthRepository) : ViewModel() {
    private val mutableUiState = MutableStateFlow(AuthUiState())
    private var requestInFlight = false
    val uiState: StateFlow<AuthUiState> = mutableUiState.asStateFlow()

    init {
        viewModelScope.launch {
            repository.authState.collect { state ->
                mutableUiState.value = mutableUiState.value.copy(
                    authState = state,
                    message = (state as? AuthState.Error)?.message,
                )
            }
        }
        viewModelScope.launch { repository.initialize() }
    }

    fun signIn(email: String, password: String) {
        submit { repository.signIn(email, password) }
    }

    fun signUp(nickname: String, email: String, password: String) {
        submit { repository.signUp(nickname, email, password) }
    }

    fun signOut() {
        submit { repository.signOut() }
    }

    fun showMessage(message: String) {
        mutableUiState.value = mutableUiState.value.copy(message = message)
    }

    private fun submit(request: suspend () -> AuthResult) {
        if (requestInFlight) return
        requestInFlight = true
        mutableUiState.value = mutableUiState.value.copy(isSubmitting = true, message = null)
        viewModelScope.launch {
            val result = request()
            val resultMessage = when (result) {
                AuthResult.Success -> null
                is AuthResult.NeedsEmailConfirmation -> result.message
                is AuthResult.Failure -> result.message
            }
            mutableUiState.value = mutableUiState.value.copy(
                isSubmitting = false,
                message = resultMessage ?: mutableUiState.value.message,
            )
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
