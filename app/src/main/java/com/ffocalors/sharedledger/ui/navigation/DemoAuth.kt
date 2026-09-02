package com.ffocalors.sharedledger.ui.navigation

import com.ffocalors.sharedledger.BuildConfig

/**
 * Debug-only credentials for exercising the static prototype without a backend.
 * This is deliberately gated at the call site and in [matches] so release builds cannot use it
 * as an authentication shortcut.
 */
internal object DemoAdminCredentials {
    const val EMAIL = "admin@sharedledger.test"
    const val PASSWORD = "Admin123!"

    fun matches(email: String, password: String, demoEnabled: Boolean = BuildConfig.DEBUG): Boolean =
        demoEnabled && email.trim().equals(EMAIL, ignoreCase = true) && password == PASSWORD
}
