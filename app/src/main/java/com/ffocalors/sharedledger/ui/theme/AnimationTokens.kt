package com.ffocalors.sharedledger.ui.theme

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.ui.unit.dp

/**
 * 全局动效令牌（阶段 E：统一、克制、有目的的动效）。
 *
 * 规范来源：前端优化计划阶段 E，适用于财务协作工具场景——所有动效必须短促、
 * 可被快速交互打断、跟随系统 animator duration scale（Compose 默认行为，
 * 系统动画关闭时自动退化为无动画，功能不受影响）。
 *
 * 禁止：循环呼吸 CTA、强弹簧/弹跳、全屏缩放、滚动绑定动画、长时间 blur、
 * 长列表逐项 stagger、链式排队动画。
 */
object SharedLedgerMotion {

    /** 统一时长（毫秒）。 */
    object Durations {
        /** Tab / 分段控件选中指示器位移或颜色过渡。 */
        const val TabIndicator = 200

        /** 展开/收起、错误提示出现、空态↔内容切换。 */
        const val Content = 200

        /** 图标/内容 crossfade（loading↔普通、复制反馈等）。 */
        const val Icon = 160

        /** 按下缩放反馈：按下 80ms，回弹 120ms。 */
        const val PressScale = 80
        const val PressReturn = 120
    }

    /** 统一缓动。 */
    object Easing {
        /** 常规进入/位置移动：先快后慢。 */
        val Standard = FastOutSlowInEasing

        /** 位置移动（指示器、转场位移）：线性起步慢出。 */
        val Position = LinearOutSlowInEasing
    }

    /** 卡片按下时的缩放比例（轻微、非弹跳）。 */
    const val PressScale = 0.98f

    /** 转场/展开位移上限。 */
    val MaxSlide = 8.dp
}
