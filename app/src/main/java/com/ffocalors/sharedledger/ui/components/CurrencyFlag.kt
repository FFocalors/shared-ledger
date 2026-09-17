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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.ComponentSizes
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

private val FlagRed = Color(0xFFD22630)
private val FlagWhite = Color(0xFFFFFFFF)
private val FlagNavy = Color(0xFF012169)
private val FlagYellow = Color(0xFFFFD700)
private val FlagLightGreen = Color(0xFF00966E)
private val FlagSaffron = Color(0xFFFF9933)
private val FlagIndiaGreen = Color(0xFF138808)
private val FlagCantonBlue = Color(0xFF11457E)
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
 * 圆角矩形国旗（24×16dp，4dp 圆角）。在小尺寸下保留真实配色、分区比例和主要徽记。
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
            val borderWidth = 0.5.dp.toPx()
            drawRoundRect(
                color = Color.Black.copy(alpha = 0.12f),
                topLeft = Offset(borderWidth / 2f, borderWidth / 2f),
                size = Size(size.width - borderWidth, size.height - borderWidth),
                cornerRadius = CornerRadius(4.dp.toPx() - borderWidth / 2f),
                style = Stroke(borderWidth),
            )
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
    fun star(
        color: Color,
        cx: Float,
        cy: Float,
        outerRadius: Float,
        innerRatio: Float = 0.42f,
        points: Int = 5,
        rotationDegrees: Float = -90f,
    ) {
        val center = Offset(w * cx, h * cy)
        val outer = h * outerRadius
        val inner = outer * innerRatio
        val path = Path()
        repeat(points * 2) { index ->
            val angle = (rotationDegrees + index * 180f / points) * PI.toFloat() / 180f
            val radius = if (index % 2 == 0) outer else inner
            val point = Offset(
                center.x + cos(angle) * radius,
                center.y + sin(angle) * radius,
            )
            if (index == 0) path.moveTo(point.x, point.y) else path.lineTo(point.x, point.y)
        }
        path.close()
        drawPath(path, color)
    }
    fun unionJack(left: Float, top: Float, width: Float, height: Float) {
        val x = w * left
        val y = h * top
        val cw = w * width
        val ch = h * height
        drawRect(FlagNavy, topLeft = Offset(x, y), size = Size(cw, ch))
        drawLine(FlagWhite, Offset(x, y), Offset(x + cw, y + ch), strokeWidth = ch * 0.19f)
        drawLine(FlagWhite, Offset(x + cw, y), Offset(x, y + ch), strokeWidth = ch * 0.19f)
        drawLine(Color(0xFFC8102E), Offset(x, y), Offset(x + cw, y + ch), strokeWidth = ch * 0.08f)
        drawLine(Color(0xFFC8102E), Offset(x + cw, y), Offset(x, y + ch), strokeWidth = ch * 0.08f)
        drawRect(FlagWhite, topLeft = Offset(x + cw * 0.39f, y), size = Size(cw * 0.22f, ch))
        drawRect(FlagWhite, topLeft = Offset(x, y + ch * 0.36f), size = Size(cw, ch * 0.28f))
        drawRect(Color(0xFFC8102E), topLeft = Offset(x + cw * 0.44f, y), size = Size(cw * 0.12f, ch))
        drawRect(Color(0xFFC8102E), topLeft = Offset(x, y + ch * 0.43f), size = Size(cw, ch * 0.14f))
    }
    fun nordicCross(background: Color, outer: Color, inner: Color? = null) {
        base(background)
        val verticalX = w * 0.34f
        val outerWidth = w * 0.18f
        val outerHeight = h * 0.24f
        drawRect(outer, topLeft = Offset(verticalX - outerWidth / 2f, 0f), size = Size(outerWidth, h))
        drawRect(outer, topLeft = Offset(0f, h * 0.5f - outerHeight / 2f), size = Size(w, outerHeight))
        if (inner != null) {
            val innerWidth = outerWidth * 0.45f
            val innerHeight = outerHeight * 0.45f
            drawRect(inner, topLeft = Offset(verticalX - innerWidth / 2f, 0f), size = Size(innerWidth, h))
            drawRect(inner, topLeft = Offset(0f, h * 0.5f - innerHeight / 2f), size = Size(w, innerHeight))
        }
    }

    when (code) {
        "CNY" -> {
            base(Color(0xFFDE2910))
            star(Color(0xFFFFDE00), 0.22f, 0.30f, 0.14f)
            star(Color(0xFFFFDE00), 0.39f, 0.14f, 0.045f, rotationDegrees = -65f)
            star(Color(0xFFFFDE00), 0.47f, 0.28f, 0.045f, rotationDegrees = -45f)
            star(Color(0xFFFFDE00), 0.47f, 0.47f, 0.045f, rotationDegrees = -25f)
            star(Color(0xFFFFDE00), 0.39f, 0.60f, 0.045f, rotationDegrees = -5f)
        }
        "JPY" -> {
            base(FlagWhite)
            disk(Color(0xFFBC002D), 0.5f, 0.5f, 0.30f)
        }
        "USD" -> {
            base(FlagWhite)
            for (i in 0 until 13 step 2) hBand(Color(0xFFB22234), i / 13f, 1f / 13f)
            drawRect(Color(0xFF3C3B6E), size = Size(w * 0.42f, h * 7f / 13f))
            for (row in 0 until 5) for (col in 0 until 6) {
                val offset = if (row % 2 == 0) 0f else 0.025f
                disk(FlagWhite, 0.035f + offset + col * 0.067f, 0.045f + row * 0.10f, 0.012f)
            }
        }
        "EUR" -> {
            base(Color(0xFF003399))
            repeat(12) { index ->
                val angle = index * 2.0 * PI / 12.0 - PI / 2.0
                star(
                    color = Color(0xFFFFCC00),
                    cx = 0.5f + (cos(angle) * 0.13f).toFloat(),
                    cy = 0.5f + (sin(angle) * 0.20f).toFloat(),
                    outerRadius = 0.035f,
                )
            }
        }
        "GBP" -> {
            unionJack(0f, 0f, 1f, 1f)
        }
        "HKD" -> {
            base(Color(0xFFDE2408))
            val center = Offset(w * 0.5f, h * 0.5f)
            repeat(5) { index ->
                rotate(index * 72f, pivot = center) {
                    drawOval(
                        color = FlagWhite,
                        topLeft = Offset(center.x - h * 0.035f, center.y - h * 0.25f),
                        size = Size(h * 0.12f, h * 0.25f),
                    )
                    disk(Color(0xFFDE2408), 0.505f, 0.32f, 0.018f)
                }
            }
        }
        "AUD", "NZD" -> {
            base(Color(0xFF00247D))
            unionJack(0f, 0f, 0.5f, 0.5f)
            if (code == "NZD") {
                listOf(Triple(0.72f, 0.25f, 0.075f), Triple(0.84f, 0.46f, 0.065f), Triple(0.67f, 0.62f, 0.065f), Triple(0.81f, 0.80f, 0.065f)).forEach { (x, y, r) ->
                    star(FlagWhite, x, y, r)
                    star(Color(0xFFCC142B), x, y, r * 0.72f)
                }
            } else {
                star(FlagWhite, 0.25f, 0.74f, 0.11f, points = 7)
                star(FlagWhite, 0.68f, 0.25f, 0.06f, points = 7)
                star(FlagWhite, 0.80f, 0.48f, 0.06f, points = 7)
                star(FlagWhite, 0.66f, 0.73f, 0.06f, points = 7)
                star(FlagWhite, 0.88f, 0.76f, 0.06f, points = 7)
                star(FlagWhite, 0.81f, 0.63f, 0.035f, points = 5)
            }
        }
        "CAD" -> {
            base(FlagWhite)
            vBand(Color(0xFFD80621), 0f, 0.25f)
            vBand(Color(0xFFD80621), 0.75f, 0.25f)
            val leaf = Path().apply {
                moveTo(w * 0.50f, h * 0.16f)
                lineTo(w * 0.54f, h * 0.33f)
                lineTo(w * 0.63f, h * 0.27f)
                lineTo(w * 0.60f, h * 0.43f)
                lineTo(w * 0.70f, h * 0.46f)
                lineTo(w * 0.60f, h * 0.57f)
                lineTo(w * 0.64f, h * 0.72f)
                lineTo(w * 0.53f, h * 0.65f)
                lineTo(w * 0.51f, h * 0.86f)
                lineTo(w * 0.49f, h * 0.86f)
                lineTo(w * 0.47f, h * 0.65f)
                lineTo(w * 0.36f, h * 0.72f)
                lineTo(w * 0.40f, h * 0.57f)
                lineTo(w * 0.30f, h * 0.46f)
                lineTo(w * 0.40f, h * 0.43f)
                lineTo(w * 0.37f, h * 0.27f)
                lineTo(w * 0.46f, h * 0.33f)
                close()
            }
            drawPath(leaf, Color(0xFFD80621))
        }
        "KRW" -> {
            base(FlagWhite)
            val center = Offset(w * 0.5f, h * 0.5f)
            val r = h * 0.28f
            drawArc(Color(0xFFCD2E3A), startAngle = 180f, sweepAngle = 180f, useCenter = true, topLeft = Offset(center.x - r, center.y - r), size = Size(r * 2, r * 2))
            drawArc(Color(0xFF0047A0), startAngle = 0f, sweepAngle = 180f, useCenter = true, topLeft = Offset(center.x - r, center.y - r), size = Size(r * 2, r * 2))
            drawCircle(Color(0xFFCD2E3A), radius = r / 2f, center = Offset(center.x - r / 2f, center.y))
            drawCircle(Color(0xFF0047A0), radius = r / 2f, center = Offset(center.x + r / 2f, center.y))
            val ink = Color(0xFF111111)
            val line = h * 0.045f
            repeat(3) { index ->
                val dy = index * h * 0.07f
                drawLine(ink, Offset(w * 0.16f, h * 0.27f + dy), Offset(w * 0.29f, h * 0.20f + dy), line)
                drawLine(ink, Offset(w * 0.71f, h * 0.80f - dy), Offset(w * 0.84f, h * 0.73f - dy), line)
            }
        }
        "SGD" -> {
            base(FlagWhite)
            hBand(Color(0xFFEF3340), 0f, 0.5f)
            disk(FlagWhite, 0.23f, 0.25f, 0.16f)
            disk(Color(0xFFEF3340), 0.29f, 0.25f, 0.13f)
            repeat(5) { index ->
                val angle = index * 2.0 * PI / 5.0 - PI / 2.0
                star(
                    FlagWhite,
                    0.42f + (cos(angle) * 0.07f).toFloat(),
                    0.25f + (sin(angle) * 0.105f).toFloat(),
                    0.027f,
                )
            }
        }
        "BRL" -> {
            base(Color(0xFF009C3B))
            val path = Path().apply {
                moveTo(w * 0.5f, h * 0.12f)
                lineTo(w * 0.88f, h * 0.5f)
                lineTo(w * 0.5f, h * 0.88f)
                lineTo(w * 0.12f, h * 0.5f)
                close()
            }
            drawPath(path, Color(0xFFFFDF00))
            disk(Color(0xFF002776), 0.5f, 0.5f, 0.18f)
            drawArc(
                FlagWhite,
                startAngle = 200f,
                sweepAngle = 135f,
                useCenter = false,
                topLeft = Offset(w * 0.35f, h * 0.40f),
                size = Size(w * 0.30f, h * 0.24f),
                style = Stroke(h * 0.035f),
            )
        }
        "CHF" -> {
            base(Color(0xFFD52B1E))
            drawRect(FlagWhite, topLeft = Offset(w * 0.43f, h * 0.22f), size = Size(w * 0.14f, h * 0.56f))
            drawRect(FlagWhite, topLeft = Offset(w * 0.31f, h * 0.41f), size = Size(w * 0.38f, h * 0.18f))
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
            nordicCross(Color(0xFFC60C30), FlagWhite)
        }
        "SEK" -> {
            nordicCross(Color(0xFF006AA7), Color(0xFFFECC02))
        }
        "NOK", "ISK" -> {
            if (code == "NOK") {
                nordicCross(Color(0xFFBA0C2F), FlagWhite, Color(0xFF00205B))
            } else {
                nordicCross(Color(0xFF02529C), FlagWhite, Color(0xFFDC1E35))
            }
        }
        "MXN" -> {
            vBand(Color(0xFF006847), 0f, 1f / 3f)
            vBand(FlagWhite, 1f / 3f, 1f / 3f)
            vBand(Color(0xFFCE1126), 2f / 3f, 1f / 3f)
            drawArc(
                Color(0xFF3A7D44),
                15f,
                150f,
                false,
                topLeft = Offset(w * 0.40f, h * 0.42f),
                size = Size(w * 0.20f, h * 0.28f),
                style = Stroke(h * 0.055f),
            )
            val eagle = Path().apply {
                moveTo(w * 0.44f, h * 0.48f)
                lineTo(w * 0.50f, h * 0.35f)
                lineTo(w * 0.57f, h * 0.45f)
                lineTo(w * 0.53f, h * 0.56f)
                lineTo(w * 0.46f, h * 0.57f)
                close()
            }
            drawPath(eagle, Color(0xFF7A5A2E))
        }
        "INR" -> {
            hBand(FlagSaffron, 0f, 1f / 3f)
            hBand(FlagWhite, 1f / 3f, 1f / 3f)
            hBand(FlagIndiaGreen, 2f / 3f, 1f / 3f)
            val chakra = Color(0xFF000080)
            val center = Offset(w * 0.5f, h * 0.5f)
            val radius = h * 0.11f
            drawCircle(chakra, radius, center, style = Stroke(h * 0.025f))
            repeat(8) { index ->
                val angle = index * PI / 4.0
                drawLine(
                    chakra,
                    center,
                    Offset(center.x + cos(angle).toFloat() * radius, center.y + sin(angle).toFloat() * radius),
                    h * 0.012f,
                )
            }
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
            for (i in 0 until 14 step 2) hBand(Color(0xFFCC0001), i / 14f, 1f / 14f)
            drawRect(Color(0xFF010066), size = Size(w * 0.52f, h * 8f / 14f))
            disk(Color(0xFFFFCC00), 0.20f, 0.28f, 0.16f)
            disk(Color(0xFF010066), 0.25f, 0.28f, 0.13f)
            star(Color(0xFFFFCC00), 0.39f, 0.28f, 0.09f, points = 14, innerRatio = 0.64f)
        }
        "PHP" -> {
            hBand(Color(0xFF0038A8), 0f, 0.5f)
            hBand(Color(0xFFCE1126), 0.5f, 0.5f)
            val path = Path().apply {
                moveTo(0f, 0f)
                lineTo(0f, h)
                lineTo(w * 0.45f, h * 0.5f)
                close()
            }
            drawPath(path, FlagWhite)
            disk(Color(0xFFFCD116), 0.17f, 0.5f, 0.08f)
            star(Color(0xFFFCD116), 0.055f, 0.14f, 0.04f)
            star(Color(0xFFFCD116), 0.055f, 0.86f, 0.04f)
            star(Color(0xFFFCD116), 0.36f, 0.5f, 0.04f)
        }
        "THB" -> {
            base(Color(0xFFA51931))
            hBand(FlagWhite, 1f / 6f, 1f / 6f)
            hBand(Color(0xFF2D2A4A), 2f / 6f, 2f / 6f)
            hBand(FlagWhite, 4f / 6f, 1f / 6f)
        }
        "ZAR" -> {
            hBand(Color(0xFFE03C31), 0f, 0.5f)
            hBand(Color(0xFF001489), 0.5f, 0.5f)
            val whiteY = Path().apply {
                moveTo(0f, 0f)
                lineTo(w * 0.38f, h * 0.38f)
                lineTo(w, h * 0.38f)
                lineTo(w, h * 0.62f)
                lineTo(w * 0.38f, h * 0.62f)
                lineTo(0f, h)
                close()
            }
            drawPath(whiteY, FlagWhite)
            val greenY = Path().apply {
                moveTo(0f, h * 0.10f)
                lineTo(w * 0.34f, h * 0.43f)
                lineTo(w, h * 0.43f)
                lineTo(w, h * 0.57f)
                lineTo(w * 0.34f, h * 0.57f)
                lineTo(0f, h * 0.90f)
                close()
            }
            drawPath(greenY, Color(0xFF007749))
            val goldTriangle = Path().apply {
                moveTo(0f, h * 0.12f)
                lineTo(w * 0.32f, h * 0.5f)
                lineTo(0f, h * 0.88f)
                close()
            }
            drawPath(goldTriangle, Color(0xFFFFB81C))
            val blackTriangle = Path().apply {
                moveTo(0f, h * 0.22f)
                lineTo(w * 0.23f, h * 0.5f)
                lineTo(0f, h * 0.78f)
                close()
            }
            drawPath(blackTriangle, Color.Black)
        }
        "TRY" -> {
            base(Color(0xFFE30A17))
            disk(FlagWhite, 0.36f, 0.5f, 0.2f)
            disk(Color(0xFFE30A17), 0.42f, 0.5f, 0.16f)
            star(FlagWhite, 0.62f, 0.5f, 0.09f, rotationDegrees = -90f)
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
            val israelBlue = Color(0xFF0038B8)
            hBand(israelBlue, 0.14f, 0.10f)
            hBand(israelBlue, 0.76f, 0.10f)
            val upper = Path().apply {
                moveTo(w * 0.5f, h * 0.31f)
                lineTo(w * 0.62f, h * 0.60f)
                lineTo(w * 0.38f, h * 0.60f)
                close()
            }
            val lower = Path().apply {
                moveTo(w * 0.5f, h * 0.69f)
                lineTo(w * 0.62f, h * 0.40f)
                lineTo(w * 0.38f, h * 0.40f)
                close()
            }
            drawPath(upper, israelBlue, style = Stroke(h * 0.035f))
            drawPath(lower, israelBlue, style = Stroke(h * 0.035f))
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
