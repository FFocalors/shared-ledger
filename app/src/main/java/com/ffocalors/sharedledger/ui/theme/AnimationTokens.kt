package com.ffocalors.sharedledger.ui.theme

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.SpringSpec
import androidx.compose.animation.core.spring
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

        /** 弹窗内容延迟出现/淡出（ms）。 */
        const val PressReturn = 120
    }

    /**
     * 弹簧曲线（阶段 E 增补）。
     *
     * - [FluidMorph]：胶囊→面板流体形态变换，高阻尼、无弹跳、丝滑减速。
     * - [PressDown]：按压下压，临界阻尼（damping 1）、快而稳，无弹跳。
     * - [PressUp]：按压回弹，轻微超调（damping 0.7）后稳定，幅度克制。
     */
    object Springs {
        val FluidMorph: SpringSpec<androidx.compose.ui.unit.Dp> =
            spring(dampingRatio = 0.92f, stiffness = 260f)

        val PressDown: SpringSpec<Float> = spring(
            dampingRatio = Spring.DampingRatioNoBouncy,
            stiffness = 1000f,
        )

        val PressUp: SpringSpec<Float> = spring(
            dampingRatio = 0.7f,
            stiffness = 500f,
        )
    }

    /** 卡片按下时的缩放比例（0.96，比旧值 0.98 更有按压深度）。 */
    const val PressScale = 0.96f

    /**
     * 按下深度内阴影 token。Compose 无原生 inner shadow，卡片在内容上层绘制
     * 一个从上边缘向下渐隐的深色渐变 overlay。深色文字卡片上若显得过重，
     * 可调低 [PressInnerShadowAlpha]（建议区间 0.10~0.15）。
     */
    const val PressInnerShadowAlpha = 0.13f
    const val PressInnerShadowHeightFraction = 1f / 3f

    /** 统一缓动。 */
    object Easing {
        /** 常规进入/位置移动：先快后慢。 */
        val Standard = FastOutSlowInEasing

        /** 位置移动（指示器、转场位移）：线性起步慢出。 */
        val Position = LinearOutSlowInEasing
    }

    /** 转场/展开位移上限。 */
    val MaxSlide = 8.dp
}
