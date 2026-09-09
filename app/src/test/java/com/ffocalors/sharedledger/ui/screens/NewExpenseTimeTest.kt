package com.ffocalors.sharedledger.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

class NewExpenseTimeTest {
    @Test
    fun parsesBackendInstantForUtc8Display() {
        assertEquals(
            LocalDateTime.of(2026, 9, 7, 12, 0, 41),
            parseExpenseOccurredAt("2026-09-07T04:00:41Z"),
        )
    }

    @Test
    fun pickerDateRoundTripsWithoutUtc8DateShift() {
        val date = LocalDate.of(2026, 9, 7)

        assertEquals(date, pickerMillisToExpenseDate(expenseDateToPickerMillis(date)))
    }

    @Test
    fun combinesDisplayedDateAndTimeIntoUtcInstant() {
        assertEquals(
            "2026-09-07T04:30:00Z",
            expenseOccurredAt(LocalDate.of(2026, 9, 7), LocalTime.of(12, 30)),
        )
    }
}
