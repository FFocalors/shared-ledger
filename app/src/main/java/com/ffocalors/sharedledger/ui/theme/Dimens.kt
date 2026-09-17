package com.ffocalors.sharedledger.ui.theme

import androidx.compose.ui.unit.dp

object SharedLedgerDimens {
    val ContentMaxWidth = 480.dp
    val PageHorizontalPadding = 24.dp
    val TopBarHeight = 72.dp
    val CardPadding = 16.dp
    val ButtonHeight = 56.dp
    val TextFieldMinHeight = 56.dp
    val BottomActionBarHeight = 76.dp
    val BottomActionBarPadding = 8.dp
    val BottomActionBarMaxWidth = 400.dp
    val TopBarActionSize = 48.dp
    val AvatarSmall = 32.dp
    val AvatarMedium = 40.dp
    val AvatarLarge = 48.dp
    val AvatarBorder = 2.dp
    val AvatarOverlap = (-8).dp
    val ParticipantAmountFieldWidth = 112.dp
    val OutlineWidth = 1.dp
    val CardBorderAlpha = 0.3f
    val IconSmall = 18.dp
    val IconMedium = 24.dp
    val IconLarge = 32.dp
    val IconContainerLarge = 48.dp
    val ActionIconContainer = 40.dp
    val ActionIcon = 20.dp
    val SummaryDecorativeSize = 128.dp
    val SummaryDecorativeOffset = 40.dp
    val AddSubActivityBorderWidth = 2.dp
    /** Scroll-content bottom clearance for pages with a 56dp FAB (FAB + 16dp margin + 16dp gap). */
    val FabClearance = 88.dp
}

object SharedLedgerElevation {
    /** Tier 1: static content surfaces — no shadow. */
    val Flat = 0.dp
    /** Tier 1: list cards resting on the background — hairline depth only. */
    val Static = 1.dp
    /** Tier 2: interactive or summary cards. */
    val Card = 2.dp
    /** Tier 3: floating elements — FAB and bottom action bars. */
    val Floating = 8.dp
}
