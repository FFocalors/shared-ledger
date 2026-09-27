package com.ffocalors.sharedledger.ui.theme

import android.content.Context
import android.os.Build
import android.os.VibrationAttributes
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 共享账本操作系统级机械触觉引擎。
 *
 * 核心驱动策略：
 * 1. 优先调用系统级 [View.performHapticFeedback]，利用 Android 操作系统及各大手机厂商
 *    （Xiaomi、vivo、OPPO、Samsung、Honor 等）针对当前机型线性马达硬件量身调校的原生微动触感波形；
 * 2. 携带 [HapticFeedbackConstants.FLAG_IGNORE_VIEW_SETTING]，确保 Compose 嵌套容器中
 *    不因局部 View 状态而丢失触感；
 * 3. 针对定制 ROM 极端场景提供带 [VibrationAttributes.USAGE_TOUCH] 的物理短微脉冲保底。
 */
class SharedLedgerHaptics internal constructor(
    private val view: View,
    private val vibrator: Vibrator?,
) {
    private var lastKeypadTime = 0L
    private var lastTickTime = 0L
    private val asyncScope = CoroutineScope(Dispatchers.Main.immediate)

    private fun canTriggerKeypad(minIntervalMs: Long = 30L): Boolean {
        val now = System.currentTimeMillis()
        if (now - lastKeypadTime < minIntervalMs) return false
        lastKeypadTime = now
        return true
    }

    private fun canTriggerTick(minIntervalMs: Long = 35L): Boolean {
        val now = System.currentTimeMillis()
        if (now - lastTickTime < minIntervalMs) return false
        lastTickTime = now
        return true
    }

    private fun performFeedback(
        primaryConstants: IntArray,
        fallbackDurationMs: Long = 26L,
        fallbackAmplitude: Int = 200,
    ) {
        runCatching {
            view.isHapticFeedbackEnabled = true
            for (constant in primaryConstants) {
                if (view.performHapticFeedback(constant, HapticFeedbackConstants.FLAG_IGNORE_VIEW_SETTING)) {
                    return
                }
            }
            triggerVibratorFallback(fallbackDurationMs, fallbackAmplitude)
        }.onFailure {
            triggerVibratorFallback(fallbackDurationMs, fallbackAmplitude)
        }
    }

    private fun triggerVibratorFallback(durationMs: Long, amplitude: Int) {
        runCatching {
            if (vibrator?.hasVibrator() == true) {
                val effect = VibrationEffect.createOneShot(durationMs, amplitude.coerceIn(1, 255))
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    val attrs = VibrationAttributes.createForUsage(VibrationAttributes.USAGE_TOUCH)
                    vibrator.vibrate(effect, attrs)
                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    val attrs = VibrationAttributes.Builder()
                        .setUsage(VibrationAttributes.USAGE_TOUCH)
                        .build()
                    vibrator.vibrate(effect, attrs)
                } else {
                    @Suppress("DEPRECATION")
                    vibrator.vibrate(effect)
                }
            }
        }
    }

    /** 键盘专用超轻瞬态敲击：专为数字键盘打造，与退格齿轮感同级调校，干脆清爽、快速连击不粘滞。 */
    fun keypad() {
        if (!canTriggerKeypad()) return
        val constants = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            intArrayOf(
                HapticFeedbackConstants.KEYBOARD_TAP,
                HapticFeedbackConstants.SEGMENT_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        } else {
            intArrayOf(
                HapticFeedbackConstants.KEYBOARD_TAP,
                HapticFeedbackConstants.CLOCK_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        }
        performFeedback(constants, fallbackDurationMs = 20L, fallbackAmplitude = 180)
    }

    /** 机械齿轮刻度感：用于分段选择、Tab 切换、退格键单点或长按连续删除。 */
    fun tick() {
        if (!canTriggerTick()) return
        val constants = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            intArrayOf(
                HapticFeedbackConstants.SEGMENT_TICK,
                HapticFeedbackConstants.CLOCK_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        } else {
            intArrayOf(
                HapticFeedbackConstants.CLOCK_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        }
        performFeedback(constants, fallbackDurationMs = 22L, fallbackAmplitude = 190)
    }

    /** 磁吸咬合感：用于平账对齐瞬间、页面全景换页到位（settledPage）、全部结清快捷填充、开关切换。 */
    fun snap() {
        val constants = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            intArrayOf(
                HapticFeedbackConstants.TOGGLE_ON,
                HapticFeedbackConstants.CONFIRM,
                HapticFeedbackConstants.CONTEXT_CLICK,
                HapticFeedbackConstants.SEGMENT_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        } else {
            intArrayOf(
                HapticFeedbackConstants.CONFIRM,
                HapticFeedbackConstants.CONTEXT_CLICK,
                HapticFeedbackConstants.CLOCK_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        }
        performFeedback(constants, fallbackDurationMs = 28L, fallbackAmplitude = 220)
    }

    /** 实体微动开关阻尼感：用于卡片按压下陷（PressFeedback）、主要操作 CTA 提交。 */
    fun click() {
        val constants = intArrayOf(
            HapticFeedbackConstants.CONFIRM,
            HapticFeedbackConstants.VIRTUAL_KEY,
        )
        performFeedback(constants, fallbackDurationMs = 26L, fallbackAmplitude = 210)
    }

    /** 成功里程碑达成：用于账单创建成功、转账提交完成等肯定性节拍（双段微动复合节奏）。 */
    fun success() {
        tick()
        asyncScope.launch {
            delay(55L)
            snap()
        }
    }

    /** 拦截与校验阻断双震：用于金额超限拦截、未平账提交阻断、校验失败。 */
    fun reject() {
        val constants = intArrayOf(
            HapticFeedbackConstants.REJECT,
            HapticFeedbackConstants.LONG_PRESS,
        )
        performFeedback(constants, fallbackDurationMs = 38L, fallbackAmplitude = 240)
    }

    /** 沉稳警示敲击感：用于删除、归档、作废等高风险二次确认操作。 */
    fun heavy() {
        val constants = intArrayOf(
            HapticFeedbackConstants.LONG_PRESS,
        )
        performFeedback(constants, fallbackDurationMs = 45L, fallbackAmplitude = 255)
    }

    /** 滚轮与选择微刻度感：用于币种浮动选择器、滚轮细微切换。 */
    fun selection() {
        if (!canTriggerTick(25L)) return
        val constants = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            intArrayOf(
                HapticFeedbackConstants.SEGMENT_FREQUENT_TICK,
                HapticFeedbackConstants.SEGMENT_TICK,
                HapticFeedbackConstants.CLOCK_TICK,
            )
        } else {
            intArrayOf(
                HapticFeedbackConstants.CLOCK_TICK,
                HapticFeedbackConstants.VIRTUAL_KEY,
            )
        }
        performFeedback(constants, fallbackDurationMs = 15L, fallbackAmplitude = 150)
    }
}

/** 在 Composable 作用域内获取或记忆机械触觉控制器。 */
@Composable
fun rememberSharedLedgerHaptics(): SharedLedgerHaptics {
    val context = LocalContext.current
    val view = LocalView.current

    val vibrator = remember(context) {
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val manager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                manager?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }
        }.getOrNull()
    }

    return remember(view, vibrator) {
        SharedLedgerHaptics(view, vibrator)
    }
}
