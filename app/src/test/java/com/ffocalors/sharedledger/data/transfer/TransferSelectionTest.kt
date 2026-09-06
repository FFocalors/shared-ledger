package com.ffocalors.sharedledger.data.transfer

import java.math.BigDecimal
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

class TransferSelectionTest {
    @Test
    fun transferAndReceiveUseOppositeDebtDirections() {
        val debts = listOf(
            BilateralDebtRowDto("me", "alice", JsonPrimitive("30.0")),
            BilateralDebtRowDto("bob", "me", JsonPrimitive("20.0")),
            BilateralDebtRowDto("me", "ignored", JsonPrimitive("0.0")),
        )
        val names = mapOf("alice" to "Alice", "bob" to "Bob")

        assertEquals(listOf("alice"), selectSettlementCandidates("me", SettlementDirection.TRANSFER, debts, names).map { it.participantId })
        assertEquals(listOf("bob"), selectSettlementCandidates("me", SettlementDirection.RECEIVE, debts, names).map { it.participantId })
        assertEquals(BigDecimal("30.0"), selectSettlementCandidates("me", SettlementDirection.TRANSFER, debts, names).single().amount)
    }
}
