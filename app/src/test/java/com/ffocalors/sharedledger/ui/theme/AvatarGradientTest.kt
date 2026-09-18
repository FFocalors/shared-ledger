package com.ffocalors.sharedledger.ui.theme

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class AvatarGradientTest {
    @Test
    fun styleIdHitIsCaseInsensitive() {
        val expected = AvatarGradientPalette.first { it.id == "sage" }
        assertEquals(expected, avatarGradientFor("sage"))
        assertEquals(expected, avatarGradientFor("SAGE"))
    }

    @Test
    fun unknownAndEmptyStylesUseStableAccountDefault() {
        assertEquals(DefaultAvatarGradient, avatarGradientFor(null))
        assertEquals(DefaultAvatarGradient, avatarGradientFor("unknown"))
    }

    @Test
    fun unboundSolidColourIsStable() {
        assertEquals(solidAvatarColorFor("participant-1"), solidAvatarColorFor("participant-1"))
        assertNotEquals(solidAvatarColorFor("participant-1"), solidAvatarColorFor("participant-2"))
    }
}
