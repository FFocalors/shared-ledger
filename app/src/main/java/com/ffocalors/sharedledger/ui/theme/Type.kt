package com.ffocalors.sharedledger.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.R

private val SharedLedgerFontFamily = FontFamily.SansSerif

/** Tabular display face for monetary figures; reinforces the mechanical "gauge" identity. */
private val SharedLedgerNumeralFontFamily = FontFamily(
    Font(R.font.barlow_semi_condensed_medium, FontWeight.Medium),
    Font(R.font.barlow_semi_condensed_semibold, FontWeight.SemiBold),
)

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
    val CardTitle = SectionTitle
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
    val SummaryAmount: TextStyle get() = AmountLarge
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
        fontFamily = SharedLedgerNumeralFontFamily,
        fontSize = 40.sp,
        lineHeight = 48.sp,
        letterSpacing = 0.sp,
        fontWeight = FontWeight.SemiBold,
        fontFeatureSettings = "tnum",
    )
    val AmountMedium = TextStyle(
        fontFamily = SharedLedgerNumeralFontFamily,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        letterSpacing = 0.sp,
        fontWeight = FontWeight.SemiBold,
        fontFeatureSettings = "tnum",
    )
    val AmountSmall = TextStyle(
        fontFamily = SharedLedgerNumeralFontFamily,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        fontWeight = FontWeight.SemiBold,
        fontFeatureSettings = "tnum",
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
