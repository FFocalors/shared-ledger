package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.ComponentSizes
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles

private val FlagRed = Color(0xFFD43D2A)
private val FlagWhite = Color(0xFFF6F3EF)
private val FlagBlue = Color(0xFF2B4C9B)
private val FlagNavy = Color(0xFF1E3A6E)
private val FlagYellow = Color(0xFFF2C53D)
private val FlagGreen = Color(0xFF2E7D46)
private val FlagLightGreen = Color(0xFF4CAF6D)
private val FlagOrange = Color(0xFFF2913D)
private val FlagSaffron = Color(0xFFFF9933)
private val FlagIndiaGreen = Color(0xFF138808)
private val FlagCantonBlue = Color(0xFF3E5AA8)
private val FlagUnknown = Color(0xFFE7E3DE)

/** 币种代码 → 中文名。覆盖 ECB 参考汇率的全部常见币种；未知返回空串，调用方回退代码。 */
internal fun currencyNameZh(code: String): String = when (code.uppercase()) {
    "CNY" -> "人民币"
    "JPY" -> "日元"
    "USD" -> "美元"
    "EUR" -> "欧元"
    "GBP" -> "英镑"
    "HKD" -> "港元"
    "AUD" -> "澳元"
    "CAD" -> "加元"
    "KRW" -> "韩元"
    "SGD" -> "新加坡元"
    "BRL" -> "巴西雷亚尔"
    "CHF" -> "瑞士法郎"
    "CZK" -> "捷克克朗"
    "DKK" -> "丹麦克朗"
    "SEK" -> "瑞典克朗"
    "NOK" -> "挪威克朗"
    "NZD" -> "新西兰元"
    "MXN" -> "墨西哥比索"
    "INR" -> "印度卢比"
    "IDR" -> "印度尼西亚盾"
    "MYR" -> "马来西亚林吉特"
    "PHP" -> "菲律宾比索"
    "THB" -> "泰铢"
    "ZAR" -> "南非兰特"
    "TRY" -> "土耳其里拉"
    "PLN" -> "波兰兹罗提"
    "HUF" -> "匈牙利福林"
    "RON" -> "罗马尼亚列伊"
    "BGN" -> "保加利亚列弗"
    "ILS" -> "以色列新谢克尔"
    "ISK" -> "冰岛克朗"
    else -> ""
}

/**
 * 简化版圆角矩形国旗（约 24×16dp，4dp 圆角），纯色几何块绘制、可辨认即可。
 * 未知币种退化为浅灰底 + 代码首字母。
 */
@Composable
fun CurrencyFlag(
    currencyCode: String,
    modifier: Modifier = Modifier,
) {
    val code = currencyCode.uppercase().trim()
    if (currencyNameZh(code).isEmpty()) {
        Box(
            modifier = modifier
                .size(CurrencyFlagWidth, CurrencyFlagHeight)
                .clip(FlagShape)
                .background(FlagUnknown),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = code.take(1).ifBlank { "?" },
                style = SharedLedgerTextStyles.Label,
                color = Color(0xFF8A8580),
            )
        }
        return
    }
    Box(
        modifier = modifier
            .size(CurrencyFlagWidth, CurrencyFlagHeight)
            .clip(FlagShape),
    ) {
        androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
            drawFlag(code)
        }
    }
}

private val CurrencyFlagWidth = 24.dp
private val CurrencyFlagHeight = 16.dp
private val FlagShape = RoundedCornerShape(4.dp)

private fun DrawScope.drawFlag(code: String) {
    val w = size.width
    val h = size.height
    fun base(color: Color) = drawRect(color, size = Size(w, h))
    fun hBand(color: Color, top: Float, fraction: Float) =
        drawRect(color, topLeft = Offset(0f, h * top), size = Size(w, h * fraction))
    fun vBand(color: Color, left: Float, fraction: Float) =
        drawRect(color, topLeft = Offset(w * left, 0f), size = Size(w * fraction, h))
    fun disk(color: Color, cx: Float, cy: Float, r: Float) =
        drawCircle(color, radius = r * h, center = Offset(w * cx, h * cy))
    fun cross(vertical: Color, horizontal: Color, vx: Float = 0.5f, vy: Float = 0.5f, t: Float = 0.2f) {
        drawRect(vertical, topLeft = Offset(w * (vx - t / 2), 0f), size = Size(w * t, h))
        drawRect(horizontal, topLeft = Offset(0f, h * (vy - t / 2)), size = Size(w, h * t))
    }

    when (code) {
        "CNY" -> {
            base(FlagRed)
            disk(FlagYellow, 0.24f, 0.32f, 0.16f)
            disk(FlagYellow, 0.45f, 0.16f, 0.05f)
            disk(FlagYellow, 0.52f, 0.32f, 0.05f)
            disk(FlagYellow, 0.52f, 0.5f, 0.05f)
            disk(FlagYellow, 0.45f, 0.62f, 0.05f)
        }
        "JPY" -> {
            base(FlagWhite)
            disk(FlagRed, 0.5f, 0.5f, 0.3f)
        }
        "USD" -> {
            base(FlagWhite)
            for (i in 0 until 7 step 2) hBand(FlagRed, i / 7f, 1f / 7f)
            drawRect(FlagNavy, size = Size(w * 0.45f, h * 4f / 7f))
            for (row in 0 until 3) for (col in 0 until 4) {
                disk(FlagWhite, 0.06f + col * 0.11f, 0.09f + row * 0.14f, 0.03f)
            }
        }
        "EUR" -> {
            base(FlagCantonBlue)
            disk(FlagYellow, 0.5f, 0.5f, 0.18f)
        }
        "GBP" -> {
            base(FlagNavy)
            drawLine(FlagWhite, Offset(0f, 0f), Offset(w, h), strokeWidth = h * 0.18f)
            drawLine(FlagWhite, Offset(w, 0f), Offset(0f, h), strokeWidth = h * 0.18f)
            cross(FlagWhite, FlagWhite, t = 0.3f)
            cross(FlagRed, FlagRed, t = 0.14f)
        }
        "HKD" -> {
            base(FlagRed)
            drawCircle(FlagWhite, radius = h * 0.2f, center = Offset(w * 0.5f, h * 0.5f), style = androidx.compose.ui.graphics.drawscope.Stroke(h * 0.05f))
            disk(FlagWhite, 0.5f, 0.5f, 0.06f)
        }
        "AUD", "NZD" -> {
            base(FlagNavy)
            val cw = w * 0.45f
            val ch = h * 0.5f
            drawRect(FlagBlue, size = Size(cw, ch))
            drawLine(FlagWhite, Offset(0f, 0f), Offset(cw, ch), strokeWidth = h * 0.12f)
            drawLine(FlagWhite, Offset(cw, 0f), Offset(0f, ch), strokeWidth = h * 0.12f)
            drawRect(FlagWhite, topLeft = Offset(cw * 0.4f, 0f), size = Size(cw * 0.2f, ch))
            drawRect(FlagWhite, topLeft = Offset(0f, ch * 0.4f), size = Size(cw, ch * 0.2f))
            if (code == "NZD") {
                disk(FlagRed, 0.22f, 0.32f, 0.06f)
                disk(FlagRed, 0.75f, 0.25f, 0.05f)
                disk(FlagRed, 0.85f, 0.5f, 0.05f)
                disk(FlagRed, 0.7f, 0.72f, 0.05f)
                disk(FlagRed, 0.85f, 0.82f, 0.05f)
            } else {
                disk(FlagWhite, 0.22f, 0.72f, 0.07f)
                disk(FlagWhite, 0.6f, 0.32f, 0.04f)
                disk(FlagWhite, 0.75f, 0.55f, 0.04f)
                disk(FlagWhite, 0.62f, 0.78f, 0.04f)
                disk(FlagWhite, 0.85f, 0.78f, 0.04f)
            }
        }
        "CAD" -> {
            base(FlagWhite)
            vBand(FlagRed, 0f, 0.25f)
            vBand(FlagRed, 0.75f, 0.25f)
            disk(FlagRed, 0.5f, 0.5f, 0.16f)
        }
        "KRW" -> {
            base(FlagWhite)
            val center = Offset(w * 0.5f, h * 0.5f)
            val r = h * 0.28f
            drawArc(FlagRed, startAngle = 180f, sweepAngle = 180f, useCenter = true, topLeft = Offset(center.x - r, center.y - r), size = Size(r * 2, r * 2))
            drawArc(FlagBlue, startAngle = 0f, sweepAngle = 180f, useCenter = true, topLeft = Offset(center.x - r, center.y - r), size = Size(r * 2, r * 2))
            disk(FlagWhite, 0.2f, 0.24f, 0.03f)
            disk(FlagWhite, 0.8f, 0.24f, 0.03f)
            disk(FlagWhite, 0.2f, 0.76f, 0.03f)
            disk(FlagWhite, 0.8f, 0.76f, 0.03f)
        }
        "SGD" -> {
            base(FlagWhite)
            hBand(FlagRed, 0f, 0.5f)
            disk(FlagWhite, 0.24f, 0.26f, 0.13f)
            disk(FlagYellow, 0.34f, 0.26f, 0.1f)
            disk(FlagWhite, 0.45f, 0.14f, 0.03f)
            disk(FlagWhite, 0.5f, 0.24f, 0.03f)
            disk(FlagWhite, 0.45f, 0.34f, 0.03f)
        }
        "BRL" -> {
            base(FlagGreen)
            val path = Path().apply {
                moveTo(w * 0.5f, h * 0.12f)
                lineTo(w * 0.88f, h * 0.5f)
                lineTo(w * 0.5f, h * 0.88f)
                lineTo(w * 0.12f, h * 0.5f)
                close()
            }
            drawPath(path, FlagYellow)
            disk(FlagBlue, 0.5f, 0.5f, 0.16f)
        }
        "CHF" -> {
            base(FlagRed)
            cross(FlagWhite, FlagWhite, t = 0.22f)
        }
        "CZK" -> {
            base(FlagWhite)
            hBand(FlagRed, 0.5f, 0.5f)
            val path = Path().apply {
                moveTo(0f, 0f)
                lineTo(0f, h)
                lineTo(w * 0.5f, h * 0.5f)
                close()
            }
            drawPath(path, FlagCantonBlue)
        }
        "DKK" -> {
            base(FlagRed)
            cross(FlagWhite, FlagWhite, vx = 0.32f, t = 0.2f)
        }
        "SEK" -> {
            base(FlagBlue)
            cross(FlagYellow, FlagYellow, vx = 0.32f, t = 0.2f)
        }
        "NOK", "ISK" -> {
            base(if (code == "NOK") FlagRed else FlagBlue)
            cross(FlagWhite, FlagWhite, vx = 0.32f, t = 0.24f)
            cross(
                if (code == "NOK") FlagBlue else FlagRed,
                if (code == "NOK") FlagBlue else FlagRed,
                vx = 0.32f,
                t = 0.1f,
            )
        }
        "MXN" -> {
            vBand(FlagGreen, 0f, 1f / 3f)
            vBand(FlagWhite, 1f / 3f, 1f / 3f)
            vBand(FlagRed, 2f / 3f, 1f / 3f)
            disk(Color(0xFF7A5A2E), 0.5f, 0.5f, 0.1f)
        }
        "INR" -> {
            hBand(FlagSaffron, 0f, 1f / 3f)
            hBand(FlagWhite, 1f / 3f, 1f / 3f)
            hBand(FlagIndiaGreen, 2f / 3f, 1f / 3f)
            disk(FlagCantonBlue, 0.5f, 0.5f, 0.11f)
        }
        "IDR", "HUF", "PLN" -> {
            base(if (code == "HUF" || code == "PLN") FlagWhite else FlagRed)
            if (code == "HUF") {
                hBand(FlagRed, 0f, 1f / 3f)
                hBand(FlagIndiaGreen, 2f / 3f, 1f / 3f)
            } else {
                hBand(if (code == "PLN") FlagRed else FlagWhite, 0.5f, 0.5f)
            }
        }
        "MYR" -> {
            base(FlagWhite)
            for (i in 0 until 8 step 2) hBand(FlagRed, i / 8f, 1f / 8f)
            drawRect(FlagNavy, size = Size(w * 0.5f, h * 0.5f))
            disk(FlagYellow, 0.2f, 0.25f, 0.1f)
            disk(FlagNavy, 0.26f, 0.25f, 0.08f)
            disk(FlagYellow, 0.36f, 0.25f, 0.04f)
        }
        "PHP" -> {
            hBand(FlagBlue, 0f, 0.5f)
            hBand(FlagRed, 0.5f, 0.5f)
            val path = Path().apply {
                moveTo(0f, 0f)
                lineTo(0f, h)
                lineTo(w * 0.45f, h * 0.5f)
                close()
            }
            drawPath(path, FlagWhite)
            disk(FlagYellow, 0.15f, 0.5f, 0.07f)
        }
        "THB" -> {
            base(FlagRed)
            hBand(FlagWhite, 1f / 6f, 1f / 6f)
            hBand(FlagBlue, 2f / 6f, 2f / 6f)
            hBand(FlagWhite, 4f / 6f, 1f / 6f)
        }
        "ZAR" -> {
            base(FlagRed)
            hBand(FlagWhite, 0.28f, 0.05f)
            hBand(FlagGreen, 0.33f, 0.34f)
            hBand(FlagWhite, 0.67f, 0.05f)
            hBand(FlagBlue, 0.72f, 0.28f)
        }
        "TRY" -> {
            base(FlagRed)
            disk(FlagWhite, 0.36f, 0.5f, 0.2f)
            disk(FlagRed, 0.42f, 0.5f, 0.16f)
            disk(FlagWhite, 0.64f, 0.5f, 0.05f)
        }
        "RON" -> {
            vBand(FlagCantonBlue, 0f, 1f / 3f)
            vBand(FlagYellow, 1f / 3f, 1f / 3f)
            vBand(FlagRed, 2f / 3f, 1f / 3f)
        }
        "BGN" -> {
            base(FlagWhite)
            hBand(FlagLightGreen, 1f / 3f, 1f / 3f)
            hBand(FlagRed, 2f / 3f, 1f / 3f)
        }
        "ILS" -> {
            base(FlagWhite)
            hBand(FlagBlue, 0.12f, 0.14f)
            hBand(FlagBlue, 0.74f, 0.14f)
            val path = Path().apply {
                moveTo(w * 0.5f, h * 0.34f)
                lineTo(w * 0.6f, h * 0.58f)
                lineTo(w * 0.4f, h * 0.58f)
                close()
            }
            drawPath(path, FlagBlue)
        }
        else -> base(FlagUnknown)
    }
}

/**
 * App 风格币种下拉菜单：surface 底色 + outlineVariant 边框 + Large 圆角，
 * 无原生 tonal elevation 紫灰。菜单项 = 国旗 + 中文名 + 代码，高 48dp，
 * 选中项带 ✓。调用方需将其放置在锚点 Box 内部。
 */
@Composable
fun SharedLedgerCurrencyDropdownMenu(
    expanded: Boolean,
    onDismissRequest: () -> Unit,
    currencyCodes: List<String>,
    selectedCode: String,
    onCurrencySelected: (String) -> Unit,
    modifier: Modifier = Modifier,
    offset: DpOffset = DpOffset(0.dp, SharedLedgerSpacing.Small),
) {
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismissRequest,
        modifier = modifier
            .widthIn(min = ComponentSizes.DropdownMinWidth, max = ComponentSizes.DropdownMaxWidth)
            .heightIn(max = ComponentSizes.DropdownMaxHeight),
        offset = offset,
        shape = SharedLedgerRadius.Large,
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
        shadowElevation = SharedLedgerElevation.Floating,
        border = androidx.compose.foundation.BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            MaterialTheme.colorScheme.outlineVariant,
        ),
    ) {
        currencyCodes.forEach { code ->
            val selected = code.equals(selectedCode, ignoreCase = true)
            DropdownMenuItem(
                text = {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                    ) {
                        CurrencyFlag(code)
                        Text(
                            text = currencyNameZh(code).ifBlank { code },
                            modifier = Modifier.weight(1f),
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = if (selected) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            },
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = code.uppercase(),
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                trailingIcon = {
                    if (selected) {
                        Icon(
                            Icons.Rounded.Check,
                            contentDescription = "当前币种",
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                        )
                    }
                },
                onClick = { onCurrencySelected(code) },
                modifier = Modifier.defaultMinSize(minHeight = ComponentSizes.DropdownItemMinHeight),
            )
        }
    }
}
