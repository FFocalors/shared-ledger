package com.ffocalors.sharedledger.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

/**
 * 语义化圆角，按「浮层 > 容器 > 控件」分层收敛，避免同类表面混用多档圆角：
 *
 * - [ExtraLarge] / [BottomActionBar]：浮层与「机械质感」主卡、弹窗、底部面板。
 * - [Large]：容器/面板 —— 带阴影的主卡片、表单分区。
 * - [Input]：文本输入框专用。
 * - [Medium]：控件与内层表面 —— 键盘按键、分组列表、行、chip、内层输入区域。
 * - [Small]：内层 chip、锁提示、状态小格。
 * - [Full]：胶囊/按钮/头像。
 */
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
