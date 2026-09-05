package com.ffocalors.sharedledger.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Test

class JoinActivityScreenTest {
    @Test
    fun participantsPresentWithoutSelectionCompletesJoinWithoutClaim() {
        val state = JoinActivityUiState(
            status = JoinActivityStatus.ReadyToJoin,
            preview = JoinActivityPreview(
                participants = listOf(
                    JoinActivityParticipant(
                        name = "可选参与人",
                        state = JoinParticipantState.Available,
                        participantId = "participant-1",
                    ),
                ),
            ),
            selectedParticipantId = null,
        )

        assertEquals(
            JoinConfirmationAction.CompleteWithoutClaim,
            resolveJoinConfirmationAction(state),
        )
    }

    @Test
    fun selectedAvailableParticipantStillClaims() {
        val state = JoinActivityUiState(
            status = JoinActivityStatus.ReadyToJoin,
            preview = JoinActivityPreview(
                participants = listOf(
                    JoinActivityParticipant(
                        name = "已选择参与人",
                        state = JoinParticipantState.Available,
                        participantId = "participant-1",
                    ),
                ),
            ),
            selectedParticipantId = "participant-1",
        )

        assertEquals(
            JoinConfirmationAction.ClaimSelectedParticipant,
            resolveJoinConfirmationAction(state),
        )
    }
}
