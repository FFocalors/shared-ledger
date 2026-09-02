package com.ffocalors.sharedledger.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val SharedLedgerFontFamily = FontFamily.SansSerif

object SharedLedgerTextStyles {
    val PageTitle = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        fontWeight = FontWeight.SemiBold,
    )
    val SectionTitle = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 18.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.Medium,
    )
    val CardTitle = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 18.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.Medium,
    )
    val Body = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.Normal,
    )
    val BodySecondary = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        fontWeight = FontWeight.Normal,
    )
    val Label = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.5.sp,
        fontWeight = FontWeight.Medium,
    )
    val SummaryLabel = Label
    val SummaryAmount = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 40.sp,
        lineHeight = 48.sp,
        letterSpacing = (-1).sp,
        fontWeight = FontWeight.SemiBold,
    )
    val SummaryCurrency = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        fontWeight = FontWeight.SemiBold,
    )
    val SubActivityAmount = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 18.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.Medium,
    )
    val SummaryStatValue = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.Medium,
    )
    val CardMeta = BodySecondary
    val ActionLabel = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 11.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.5.sp,
        fontWeight = FontWeight.Medium,
    )
    val BottomActionLabel = Label
    val BottomActionEmphasizedLabel = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        fontWeight = FontWeight.SemiBold,
    )
    val Button = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.Medium,
    )
    val AmountLarge = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 40.sp,
        lineHeight = 48.sp,
        letterSpacing = (-1).sp,
        fontWeight = FontWeight.SemiBold,
    )
    val AmountMedium = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        letterSpacing = (-0.4).sp,
        fontWeight = FontWeight.SemiBold,
    )
    val AmountSmall = TextStyle(
        fontFamily = SharedLedgerFontFamily,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.SemiBold,
    )
}

val SharedLedgerTypography = Typography(
    displayLarge = SharedLedgerTextStyles.AmountLarge,
    headlineSmall = SharedLedgerTextStyles.PageTitle,
    titleLarge = SharedLedgerTextStyles.SectionTitle,
    titleMedium = SharedLedgerTextStyles.CardTitle,
    bodyLarge = SharedLedgerTextStyles.Body,
    bodyMedium = SharedLedgerTextStyles.BodySecondary,
    labelMedium = SharedLedgerTextStyles.Label,
)
