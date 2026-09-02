package com.ffocalors.sharedledger.ui.screens

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TransferAmountTest {
    @Test
    fun emptyZeroAndMalformedAmountsAreNotSubmittable() {
        assertFalse(isValidTransferAmount(""))
        assertFalse(isValidTransferAmount("0"))
        assertFalse(isValidTransferAmount("-1"))
        assertFalse(isValidTransferAmount("."))
        assertTrue(isValidTransferAmount("0.01"))
    }
}
