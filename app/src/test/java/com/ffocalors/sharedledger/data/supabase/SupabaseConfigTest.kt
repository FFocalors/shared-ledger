package com.ffocalors.sharedledger.data.supabase

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SupabaseConfigTest {
    @Test
    fun rejectsMissingOrPrivilegedKeys() {
        assertFalse(SupabaseConfig("", "").isUsable)
        assertFalse(SupabaseConfig("https://demo.supabase.co", "sb_secret_do_not_use").isUsable)
        assertFalse(SupabaseConfig("https://demo.supabase.co", "service_role_do_not_use").isUsable)
    }

    @Test
    fun acceptsHttpsPublishableConfiguration() {
        assertTrue(SupabaseConfig("https://demo.supabase.co", "sb_publishable_demo").isUsable)
    }

    @Test
    fun acceptsOnlyExplicitLocalHttpHostsInDebugConfiguration() {
        assertTrue(
            SupabaseConfig(
                "http://10.0.2.2:54321",
                "sb_publishable_demo",
                allowLocalHttp = true,
            ).isUsable,
        )
        assertFalse(
            SupabaseConfig(
                "http://example.com:54321",
                "sb_publishable_demo",
                allowLocalHttp = true,
            ).isUsable,
        )
        assertFalse(SupabaseConfig("http://127.0.0.1:54321", "sb_publishable_demo").isUsable)
    }
}
