package com.ffocalors.sharedledger.ui.navigation

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DemoAuthTest {
    @Test
    fun acceptsOnlyTheDebugDemoAdminCredentials() {
        assertTrue(DemoAdminCredentials.matches(" admin@sharedledger.test ", "Admin123!", demoEnabled = true))
        assertFalse(DemoAdminCredentials.matches("admin@sharedledger.test", "wrong-password", demoEnabled = true))
        assertFalse(DemoAdminCredentials.matches("someone@example.com", "Admin123!", demoEnabled = true))
    }

    @Test
    fun releaseModeCannotUseTheDemoCredentialShortcut() {
        assertFalse(DemoAdminCredentials.matches(DemoAdminCredentials.EMAIL, DemoAdminCredentials.PASSWORD, demoEnabled = false))
    }
}
