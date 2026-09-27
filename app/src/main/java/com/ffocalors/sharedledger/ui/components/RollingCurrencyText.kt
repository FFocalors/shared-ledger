package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.spring
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import java.math.BigDecimal
import java.math.RoundingMode
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Currency
import java.util.Locale

/**
 * 操作系统级机械数字翻转组件（去 AI 化的实体机械翻页钟质感）。
 *
 * 核心设计规范：
 * - 采用 Tabular 等宽数字特性（"tnum"），每一位数字槽位宽度绝对一致，杜绝任何横向抖动；
 * - 货币符号与小数点标点保持基线稳定，不跳动；
 * - 垂直槽位滑动采用高阻尼精密机械弹簧（stiffness = 380f, dampingRatio = 0.85f），平稳入位无弹跳；
 * - 严格遵循工程极简与金融严谨性。
 */
@Composable
fun RollingCurrencyText(
    amount: BigDecimal?,
    modifier: Modifier = Modifier,
    currencyCode: String = "CNY",
    fractionDigitsOverride: Int? = null,
    style: TextStyle = SharedLedgerTextStyles.AmountLarge,
    textStyle: TextStyle = style,
    color: Color = MaterialTheme.colorScheme.onSurface,
    showSymbol: Boolean = true,
) {
    val actualStyle = textStyle
    val formattedNumber = remember(amount, currencyCode, fractionDigitsOverride) {
        if (amount == null) {
            "--"
        } else {
            val normalizedCode = currencyCode.uppercase(Locale.ROOT)
            val fractionDigits = fractionDigitsOverride ?: when (normalizedCode) {
                "CNY" -> 1
                else -> runCatching {
                    Currency.getInstance(normalizedCode).defaultFractionDigits
                }.getOrDefault(2).coerceAtLeast(0)
            }
            val pattern = buildString {
                append("#,##0")
                if (fractionDigits > 0) {
                    append(".")
                    repeat(fractionDigits) { append("0") }
                }
            }
            DecimalFormat(pattern, DecimalFormatSymbols(Locale.US)).apply {
                roundingMode = RoundingMode.HALF_UP
            }.format(amount)
        }
    }

    val symbol = remember(currencyCode, showSymbol) {
        if (!showSymbol) "" else resolveCurrencySymbol(currencyCode)
    }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.Bottom,
    ) {
        if (symbol.isNotBlank()) {
            Text(
                text = symbol,
                style = actualStyle.copy(
                    fontSize = actualStyle.fontSize * 0.72f,
                    lineHeight = actualStyle.lineHeight * 0.72f,
                ),
                color = color.copy(alpha = 0.85f),
            )
            // 符号与数字之间的精细间隔
            Text(
                text = " ",
                style = actualStyle.copy(
                    fontSize = actualStyle.fontSize * 0.35f,
                ),
            )
        }

        RollingAmountText(
            formattedAmount = formattedNumber,
            style = actualStyle,
            color = color,
        )
    }
}

/**
 * 单个格式化金额字符串的逐位机械翻滚渲染器。
 */
@Composable
fun RollingAmountText(
    formattedAmount: String,
    style: TextStyle,
    color: Color,
    modifier: Modifier = Modifier,
) {
    // 强制启用等宽数字字形特性（Tabular Numbers: "tnum"），消除排版抖动
    val tabularStyle = remember(style) {
        style.copy(
            fontFeatureSettings = if (style.fontFeatureSettings.isNullOrBlank()) {
                "tnum"
            } else {
                "${style.fontFeatureSettings}, tnum"
            },
        )
    }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.Bottom,
    ) {
        formattedAmount.forEachIndexed { _, char ->
            if (char.isDigit()) {
                // 数字位采用独立垂直翻转机械槽
                MechanicalDigitSlot(
                    char = char,
                    style = tabularStyle,
                    color = color,
                )
            } else {
                // 逗号、小数点、负号等非数字字符保持基线静态稳定
                Text(
                    text = char.toString(),
                    style = tabularStyle,
                    color = color,
                )
            }
        }
    }
}

@Composable
private fun MechanicalDigitSlot(
    char: Char,
    style: TextStyle,
    color: Color,
) {
    AnimatedContent(
        targetState = char,
        transitionSpec = {
            // 数字向上平滑推移入位：高阻尼弹簧平稳减速，无塑料果冻感
            (slideInVertically(
                animationSpec = spring(dampingRatio = 0.85f, stiffness = 380f),
            ) { fullHeight -> (fullHeight * 0.65f).toInt() } + fadeIn(
                animationSpec = spring(dampingRatio = 0.85f, stiffness = 380f),
            )).togetherWith(
                slideOutVertically(
                    animationSpec = spring(dampingRatio = 0.85f, stiffness = 380f),
                ) { fullHeight -> (-fullHeight * 0.65f).toInt() } + fadeOut(
                    animationSpec = spring(dampingRatio = 0.85f, stiffness = 380f),
                ),
            )
        },
        label = "mechanicalDigitSlot",
    ) { targetChar ->
        Text(
            text = targetChar.toString(),
            style = style,
            color = color,
        )
    }
}

fun resolveCurrencySymbol(currencyCode: String): String = when (currencyCode.uppercase(Locale.ROOT)) {
    "CNY", "JPY" -> "¥"
    "EUR" -> "€"
    "USD" -> "$"
    "GBP" -> "£"
    else -> "$currencyCode "
}
