package com.ffocalors.sharedledger.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ActivityManagementTest {
    @Test
    fun ownershipTransferTargetsSelectedNonCreatorOnly() {
        val creator = ActivityManagementMember(
            name = "Alice",
            isCreator = true,
            memberId = "member-alice",
        )
        val successor = ActivityManagementMember(
            name = "Charlie",
            isCreator = false,
            memberId = "member-charlie",
        )

        assertNull(ownershipTransferTargetId(creator))
        assertEquals("member-charlie", ownershipTransferTargetId(successor))
    }
}
