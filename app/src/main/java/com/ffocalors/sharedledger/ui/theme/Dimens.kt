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

/** 组件尺寸：仅收语义明确的布局专用尺寸，无语义的孤立 dp 值不强行 token 化。 */
object ComponentSizes {
    /** 下拉菜单（如币种选择）的最小宽度。 */
    val DropdownMinWidth = 184.dp
    /** 下拉菜单的最大宽度。 */
    val DropdownMaxWidth = 248.dp
    /** 下拉菜单的最大高度（超出可滚动）。 */
    val DropdownMaxHeight = 336.dp
    /** 下拉菜单单项的最小触摸高度。 */
    val DropdownItemMinHeight = 48.dp
    /** 分段控件（如"手动分摊/AA均摊"）的最大宽度。 */
    val SegmentedControlMaxWidth = 172.dp
    /** 消费凭证附件缩略图的宽度。 */
    val AttachmentCardWidth = 180.dp
    /** 消费凭证附件缩略图的高度。 */
    val AttachmentCardHeight = 116.dp
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
