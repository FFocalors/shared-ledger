package com.ffocalors.sharedledger.ui.demo

import com.ffocalors.sharedledger.ui.components.ActivityCardUiModel
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.components.ActivityStatus
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import java.math.BigDecimal

/** Stable IDs used by the V0.1 navigation demo; these are not domain entities. */
object DemoRouteIds {
    const val JOIN_ACTIVITY = "demo-join"
    const val NORMAL_ACTIVITY = "demo-normal"
    const val LARGE_ACTIVITY = "demo-large"
    const val BREAKFAST_LEDGER = "demo-breakfast"
    const val TICKET_LEDGER = "demo-ticket"
    const val HOTEL_LEDGER = "demo-hotel"
    const val DINNER_EXPENSE = "demo-expense-dinner"
    const val TAXI_EXPENSE = "demo-expense-taxi"
    const val TICKET_EXPENSE = "demo-expense-ticket"
    const val TRANSFER = "demo-transfer-001"
    const val CREATED_NORMAL_ACTIVITY = "demo-created-normal"
    const val CREATED_LARGE_ACTIVITY = "demo-created-large"

    /** Stable demo identity for a locally completed transfer submission. */
    fun transfer(
        activityId: String,
        ledgerUnitId: String?,
        mode: String,
        participantId: String,
    ): String = listOf(
        "demo-transfer",
        activityId,
        ledgerUnitId ?: "activity",
        mode,
        participantId,
    ).joinToString("-")

    fun finalSettlementTransfer(activityId: String): String = "demo-final-settlement-$activityId"
}

/** Shared display fixtures. They intentionally remain UI models, not persistence entities. */
object DemoData {
    val japanTravel = ActivityCardUiModel(
        name = "日本旅行",
        kind = ActivityKind.Large,
        participantCount = 6,
        status = ActivityStatus.PendingSettlement,
        totalAmount = BigDecimal("1240.5"),
        updatedAt = "12:30",
        activityId = DemoRouteIds.LARGE_ACTIVITY,
        participants = listOf(
            ParticipantUiModel("张三"),
            ParticipantUiModel("李四", WarmOrangeContainer),
            ParticipantUiModel("王五"),
            ParticipantUiModel("赵六", IconContainerSage),
            ParticipantUiModel("陈七"),
            ParticipantUiModel("周八", WarmOrangeContainer),
        ),
    )

    val weekendDinner = ActivityCardUiModel(
        name = "周末聚餐",
        kind = ActivityKind.Standard,
        participantCount = 5,
        status = ActivityStatus.Settled,
        totalAmount = null,
        updatedAt = "昨天",
        activityId = DemoRouteIds.NORMAL_ACTIVITY,
        participants = listOf(
            ParticipantUiModel("王五", WarmOrangeContainer),
            ParticipantUiModel("李四"),
        ),
    )
}
