package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.data.financial.PrepaymentAccount
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PrepaymentScreenTest {
    private val current = ParticipantInfo("current", "当前用户")
    private val target = ParticipantInfo("target", "目标参与人")

    @Test
    fun fundDirectionUsesCurrentOwnerAndSelectedCustodian() {
        val candidate = buildPrepaymentCandidate(PrepaymentMode.FUND, current.participantId, target)

        assertEquals(current.participantId, candidate.ownerId)
        assertEquals(target.participantId, candidate.custodianId)
        assertTrue(isValidPrepaymentDirection(candidate))
    }

    @Test
    fun fundCandidateKeepsExistingAccountWithoutApplyingReturnLimit() {
        val account = PrepaymentAccount(
            accountId = "account",
            owner = current,
            custodian = target,
            balance = BigDecimal("100.0"),
            usedAmount = BigDecimal("100.0"),
        )

        val candidate = buildPrepaymentCandidate(PrepaymentMode.FUND, current.participantId, target, account)

        assertEquals(account, candidate.account)
        assertEquals(BigDecimal("100.0"), candidate.account?.balance)
        assertEquals(BigDecimal("100.0"), candidate.account?.usedAmount)
        assertTrue(isValidPrepaymentDirection(candidate))
        assertEquals(null, prepaymentAmountLimit(PrepaymentMode.FUND, candidate))
    }

    @Test
    fun returnDirectionUsesAccountOwnerAndCurrentCustodian() {
        val account = PrepaymentAccount(
            accountId = "account",
            owner = target,
            custodian = current,
            balance = BigDecimal("20.0"),
        )

        val candidate = buildPrepaymentCandidate(PrepaymentMode.RETURN, current.participantId, target, account)

        assertEquals(target.participantId, candidate.ownerId)
        assertEquals(current.participantId, candidate.custodianId)
        assertEquals(target, candidate.person)
        assertTrue(isValidPrepaymentDirection(candidate))
        assertEquals(BigDecimal("20.0"), prepaymentAmountLimit(PrepaymentMode.RETURN, candidate))
    }

    @Test
    fun sameOwnerAndCustodianIsRejectedBeforeRpc() {
        val candidate = PrepaymentCandidate(
            ownerId = current.participantId,
            custodianId = current.participantId,
            person = current,
            account = null,
        )

        assertFalse(isValidPrepaymentDirection(candidate))
    }

    @Test
    fun proxyCandidateRequiresAnUnclaimedOnBehalfParticipant() {
        val proxy = buildPrepaymentPairCandidate(
            mode = PrepaymentMode.FUND,
            owner = ParticipantInfo("unclaimed-owner", "代记所有者"),
            custodian = target,
            account = null,
            unclaimedParticipants = listOf(ParticipantInfo("unclaimed-owner", "代记所有者")),
        )

        assertFalse(isValidPrepaymentActingParty(proxy, current.participantId, null))
        assertTrue(isValidPrepaymentActingParty(proxy, current.participantId, "unclaimed-owner"))
    }

    @Test
    fun candidateContainingCurrentParticipantCanUseNoOnBehalf() {
        val own = buildPrepaymentCandidate(PrepaymentMode.FUND, current.participantId, target)

        assertTrue(isValidPrepaymentActingParty(own, current.participantId, null))
    }
}
