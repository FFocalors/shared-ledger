package com.ffocalors.sharedledger.ui.components

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import com.ffocalors.sharedledger.ui.theme.SageGreenContainer
import java.math.BigDecimal

enum class ActivityKind {
    Standard,
    Large,
}

enum class ActivityStatus {
    InProgress,
    PendingSettlement,
    Settled,
    Archived,
    Disputed,
}

enum class AmountSize {
    Large,
    Medium,
    Small,
    SubActivity,
}

enum class AmountEmphasis {
    Primary,
    Standard,
    Muted,
    Warning,
}

enum class ParticipantAmountStatus {
    None,
    Pending,
    Paid,
    Returned,
    Disputed,
}

@Immutable
data class ParticipantUiModel(
    val name: String,
    val backgroundColor: Color = SageGreenContainer,
)

@Immutable
data class ActivityCardUiModel(
    val name: String,
    val kind: ActivityKind,
    val participantCount: Int,
    val status: ActivityStatus,
    val totalAmount: BigDecimal?,
    val currencyCode: String = "CNY",
    val updatedAt: String,
    val participants: List<ParticipantUiModel> = emptyList(),
)

@Immutable
data class SubActivityUiModel(
    val name: String,
    val amount: BigDecimal,
    val participantCount: Int,
    val updatedAt: String,
    val icon: ImageVector,
    val currencyCode: String = "CNY",
    val iconContainerColor: Color = Color.Unspecified,
    val iconTint: Color = Color.Unspecified,
    val fractionDigitsOverride: Int? = null,
)

@Immutable
data class ExpenseCardUiModel(
    val name: String,
    val amount: BigDecimal,
    val currencyCode: String = "CNY",
    val payerName: String,
    val participantCount: Int,
    val time: String? = null,
    val participants: List<ParticipantUiModel> = emptyList(),
)

@Immutable
data class SettlementStatistic(
    val label: String,
    val value: String,
)

@Immutable
data class BottomActionItem(
    val label: String,
    val icon: ImageVector,
    val onClick: () -> Unit,
)

@Immutable
data class QuickActionItem(
    val label: String,
    val icon: ImageVector,
    val onClick: () -> Unit = {},
    val iconContainerColor: Color = Color.Unspecified,
    val iconTint: Color = Color.Unspecified,
)
