package com.ffocalors.sharedledger.data.agent

import org.junit.Assert.*
import org.junit.Test

class AgentPrivateAddressTest {
    @Test fun privateAddressesRequireDebugOptIn() {
        for (host in listOf("10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.2")) {
            assertTrue(AgentConfig("http://$host:8765", true).isConfigured)
            assertFalse(AgentConfig("http://$host:8765", false).isConfigured)
            assertTrue(AgentConfig("https://$host:8765", false).isConfigured)
        }
    }
    @Test fun rejectsNonPrivateAndMalformedAddresses() {
        for (host in listOf("0.0.0.0", "169.254.1.1", "8.8.8.8", "172.15.1.1", "172.32.1.1", "192.169.1.1", "10.256.1.1", "224.0.0.1", "[fe80::1]")) {
            assertFalse(host, AgentConfig("http://$host:8765", true).isConfigured)
        }
    }
}
