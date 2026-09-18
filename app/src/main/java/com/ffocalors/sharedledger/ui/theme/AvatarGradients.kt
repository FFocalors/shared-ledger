package com.ffocalors.sharedledger.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color

/** A bound account always uses a smoke preset; an unbound identity always uses a solid colour. */
@Immutable
sealed interface AvatarBackground {
    @Immutable
    data class Bound(
        val presetId: String?,
        /** Stable account key used only to de-synchronise the ambient smoke motion. */
        val stableKey: String? = null,
    ) : AvatarBackground

    @Immutable
    data class Unbound(val stableKey: String) : AvatarBackground
}

/** Fixed, versionable preset keys are persisted in profiles.avatar_style. */
@Immutable
data class AvatarGradient(val id: String, val colors: List<Color>)

/** Existing colour families, with a third accent for the layered smoke rendering. */
val AvatarGradientPalette: List<AvatarGradient> = listOf(
    AvatarGradient("sage", listOf(Color(0xFF536D5B), Color(0xFF9FC5A6), Color(0xFFE2B8C7))),
    AvatarGradient("terracotta", listOf(Color(0xFF9E5544), Color(0xFFE09B78), Color(0xFFF0C6A8))),
    AvatarGradient("honey", listOf(Color(0xFF9B7335), Color(0xFFE0B85E), Color(0xFFFFE4A3))),
    AvatarGradient("olive", listOf(Color(0xFF66724C), Color(0xFFADB77A), Color(0xFFD9C58C))),
    AvatarGradient("slate", listOf(Color(0xFF4F6375), Color(0xFF91A9B9), Color(0xFFD1B5D2))),
    AvatarGradient("mist", listOf(Color(0xFF4F7EA2), Color(0xFF9DCAE0), Color(0xFFD8B8E6))),
    AvatarGradient("lotus", listOf(Color(0xFF8C5E72), Color(0xFFD7A3B4), Color(0xFFF1D0BC))),
    AvatarGradient("cocoa", listOf(Color(0xFF6F4D3E), Color(0xFFB88970), Color(0xFFE4B99B))),
    AvatarGradient("moss", listOf(Color(0xFF496447), Color(0xFF86A576), Color(0xFFC6D49B))),
    AvatarGradient("apricot", listOf(Color(0xFFB66D4C), Color(0xFFEAA77C), Color(0xFFFFD0A9))),
    AvatarGradient("berry", listOf(Color(0xFF674A7C), Color(0xFFB379A4), Color(0xFFE4A5B4))),
    AvatarGradient("teal", listOf(Color(0xFF336F70), Color(0xFF7EB8A9), Color(0xFFBBDCC7))),
    AvatarGradient("coral", listOf(Color(0xFFA84F5A), Color(0xFFE78778), Color(0xFFFFC1A5))),
    AvatarGradient("steel", listOf(Color(0xFF4F657D), Color(0xFF91A9C0), Color(0xFFCAD7E7))),
    AvatarGradient("wheat", listOf(Color(0xFF8D7136), Color(0xFFD0AE65), Color(0xFFF4D7A0))),
    AvatarGradient("rose", listOf(Color(0xFF8F5369), Color(0xFFD18DA1), Color(0xFFF3C3C4))),
)

val DefaultAvatarGradient: AvatarGradient = AvatarGradientPalette.first()

private val AvatarSolidPalette: List<Color> = listOf(
    Color(0xFF7D9B76), Color(0xFFC07B5A), Color(0xFFC09A45), Color(0xFF75829A),
    Color(0xFF6E98AD), Color(0xFFAC7888), Color(0xFF7B6B9A), Color(0xFF5F9289),
    Color(0xFFB86F67), Color(0xFF7C8A58), Color(0xFF98725F), Color(0xFF8A7395),
)

fun avatarGradientFor(styleId: String?): AvatarGradient =
    AvatarGradientPalette.firstOrNull { it.id.equals(styleId, ignoreCase = true) }
        ?: DefaultAvatarGradient

/** Deterministic across recomposition, refresh and app restart. */
fun solidAvatarColorFor(stableKey: String): Color {
    var hash = 17
    stableKey.forEach { hash = hash * 31 + it.code }
    val index = ((hash % AvatarSolidPalette.size) + AvatarSolidPalette.size) % AvatarSolidPalette.size
    return AvatarSolidPalette[index]
}
