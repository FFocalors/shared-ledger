package com.ffocalors.sharedledger.ui.components

import androidx.compose.ui.graphics.Color
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.Inverted
import com.ffocalors.sharedledger.ui.theme.InvertedContent
import com.ffocalors.sharedledger.ui.theme.Neutral
import com.ffocalors.sharedledger.ui.theme.NeutralContent
import com.ffocalors.sharedledger.ui.theme.SharedLedgerButtonColorPair
import com.ffocalors.sharedledger.ui.theme.SoftPrimary
import com.ffocalors.sharedledger.ui.theme.SoftPrimaryContent
import com.ffocalors.sharedledger.ui.theme.WarmSecondary
import com.ffocalors.sharedledger.ui.theme.WarmSecondaryContent
import com.ffocalors.sharedledger.ui.theme.hasAccessibleButtonContrast
import com.ffocalors.sharedledger.ui.theme.sharedLedgerContrastRatio
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ButtonPaletteTest {
    @Test
    fun mapsTheFourStitchButtonTonesToTheirSpecifiedColors() {
        assertEquals(
            Pair(SoftPrimary, SoftPrimaryContent),
            sharedLedgerButtonPaletteFor(SharedLedgerButtonTone.SoftPrimary).asPair(),
        )
        assertEquals(
            Pair(WarmSecondary, WarmSecondaryContent),
            sharedLedgerButtonPaletteFor(SharedLedgerButtonTone.WarmSecondary).asPair(),
        )
        assertEquals(
            Pair(Neutral, NeutralContent),
            sharedLedgerButtonPaletteFor(SharedLedgerButtonTone.Neutral).asPair(),
        )
        assertEquals(
            Pair(Inverted, InvertedContent),
            sharedLedgerButtonPaletteFor(SharedLedgerButtonTone.Inverted).asPair(),
        )
    }

    @Test
    fun everyFilledPaletteMeetsNormalTextContrastAndWarmSecondaryNeverUsesWhite() {
        val tones = listOf(
            SharedLedgerButtonTone.SoftPrimary,
            SharedLedgerButtonTone.WarmSecondary,
            SharedLedgerButtonTone.Neutral,
            SharedLedgerButtonTone.Inverted,
        )

        tones.forEach { tone ->
            assertTrue(
                "${tone.name} should meet 4.5:1 contrast",
                hasAccessibleButtonContrast(sharedLedgerButtonPaletteFor(tone)),
            )
        }
        assertNotEquals(Color.White, WarmSecondaryContent)
        assertFalse(
            sharedLedgerButtonPaletteFor(SharedLedgerButtonTone.WarmSecondary).contentColor == Color.White,
        )
    }

    @Test
    fun outlinedTonesUseHighContrastForegroundsOnThePageSurface() {
        val tones = listOf(
            SharedLedgerButtonTone.SoftPrimary,
            SharedLedgerButtonTone.WarmSecondary,
            SharedLedgerButtonTone.Neutral,
            SharedLedgerButtonTone.Inverted,
            SharedLedgerButtonTone.Success,
            SharedLedgerButtonTone.Warning,
            SharedLedgerButtonTone.Danger,
        )

        tones.forEach { tone ->
            assertTrue(
                "${tone.name} outline should meet 4.5:1 contrast",
                sharedLedgerContrastRatio(sharedLedgerButtonOutlineColor(tone), AppSurface) >= 4.5,
            )
        }
        assertEquals(ErrorRed, sharedLedgerButtonOutlineColor(SharedLedgerButtonTone.Danger))
    }

    private fun SharedLedgerButtonColorPair.asPair() =
        Pair(containerColor, contentColor)
}
