package com.ffocalors.sharedledger.ui.util

import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** Formats backend timestamptz values for the product UI without changing raw payloads. */
object UiDateTimeFormatter {
    private val displayFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")
        .withZone(ZoneOffset.ofHours(8))

    fun format(value: String): String {
        val raw = value.trim()
        if (raw.isBlank()) return value
        return runCatching { displayFormatter.format(Instant.parse(raw)) }
            .recoverCatching { displayFormatter.format(OffsetDateTime.parse(raw).toInstant()) }
            .getOrDefault(value)
    }
}
