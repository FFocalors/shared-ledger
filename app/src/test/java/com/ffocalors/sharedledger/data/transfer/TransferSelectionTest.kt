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
        val names = mapOf("me" to "Me", "alice" to "Alice", "bob" to "Bob")

        assertEquals(listOf("alice"), selectSettlementCandidates("me", SettlementDirection.TRANSFER, debts, names).map { it.participantId })
        assertEquals(listOf("bob"), selectSettlementCandidates("me", SettlementDirection.RECEIVE, debts, names).map { it.participantId })
        assertEquals(BigDecimal("30.0"), selectSettlementCandidates("me", SettlementDirection.TRANSFER, debts, names).single().amount)
    }

    @Test
    fun creatorClaimedAsZhyOnlySeesOwnReceiveDebtsInPersonalCandidates() {
        val debts = listOf(
            BilateralDebtRowDto("hzl", "whr", JsonPrimitive("52.0")),
            BilateralDebtRowDto("whr", "zhy", JsonPrimitive("147.9")),
            BilateralDebtRowDto("hzl", "zhy", JsonPrimitive("107.0")),
        )
        val names = mapOf(
            "zhy" to "zhy",
            "whr" to "whr",
            "hzl" to "hzl",
        )

        val candidates = selectSettlementCandidates(
            currentParticipantId = "zhy",
            direction = SettlementDirection.RECEIVE,
            debts = debts,
            participantNames = names,
        )

        assertEquals(listOf("whr", "hzl"), candidates.map { it.participantId })
        assertEquals(listOf(BigDecimal("147.9"), BigDecimal("107.0")), candidates.map { it.amount })
        assertEquals(false, candidates.any { it.fromParticipantId == "hzl" && it.toParticipantId == "whr" })
    }

    @Test
    fun creatorOnBehalfCandidatesAreSeparateAndDirectionSpecific() {
        val debts = listOf(BilateralDebtRowDto("hzl", "whr", JsonPrimitive("52.0")))
        val names = mapOf("zhy" to "zhy", "whr" to "whr", "hzl" to "hzl")

        val candidates = selectOnBehalfSettlementCandidates(
            currentParticipantId = "zhy",
            direction = SettlementDirection.TRANSFER,
            debts = debts,
            participantNames = names,
            canActOnBehalf = true,
            claimedParticipantIds = setOf("zhy"),
        )

        assertEquals(1, candidates.size)
        assertEquals("hzl", candidates.single().fromParticipantId)
        assertEquals("whr", candidates.single().toParticipantId)
        assertEquals(SettlementCandidateKind.ON_BEHALF, candidates.single().kind)
        assertEquals(listOf("hzl"), candidates.single().onBehalfOptions.map { it.participantId })
    }
}
