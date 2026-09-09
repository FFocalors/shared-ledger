package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.ui.demo.DemoRouteIds

/** Test-only compatibility fixture for the legacy transfer identity contract. */
data class TransferCreationResult(
    val transferId: String,
    val activityId: String,
    val ledgerUnitId: String?,
)

internal fun demoCreateTransfer(draft: TransferDraft): TransferCreationResult = TransferCreationResult(
    transferId = DemoRouteIds.transfer(
        activityId = draft.activityId,
        ledgerUnitId = draft.ledgerUnitId,
        mode = if (draft.mode == TransferMode.RECEIVE) "receive" else "transfer",
        participantId = draft.participantId,
    ),
    activityId = draft.activityId,
    ledgerUnitId = draft.ledgerUnitId,
)
