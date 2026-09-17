package com.ffocalors.sharedledger.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

object SharedLedgerRadius {
    val Small = RoundedCornerShape(8.dp)
    val Medium = RoundedCornerShape(12.dp)
    /** Raw size of [Large] for draw-scope code that cannot read a shape back as Dp. */
    val LargeCorner = 16.dp
    val Large = RoundedCornerShape(LargeCorner)
    val Input = RoundedCornerShape(18.dp)
    val ExtraLarge = RoundedCornerShape(24.dp)
    val BottomActionBar = RoundedCornerShape(32.dp)
    val Full = RoundedCornerShape(percent = 50)
}
