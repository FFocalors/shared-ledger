package com.ffocalors.sharedledger.ui.components

import org.junit.Assert.assertEquals
import org.junit.Test

class NumericKeypadStateTest {
    @Test
    fun inputAppendsMultipleIntegerDigits() {
        var value = ""
        val keypad = NumericKeypadState()
        keypad.bind({ value }, { value = it })

        keypad.input("1")
        keypad.input("1")
        keypad.input("1")

        assertEquals("111", value)
    }

    @Test
    fun inputAppendsDigitsBeforeTheBoundGetterRecomposes() {
        var renderedValue = ""
        var emittedValue = ""
        val keypad = NumericKeypadState()
        keypad.bind({ renderedValue }, { emittedValue = it })

        // The getter intentionally remains stale, matching the short window
        // between a Compose state write and the next recomposition.
        keypad.input("1")
        keypad.input("2")
        keypad.input("3")

        assertEquals("123", emittedValue)
    }

    @Test
    fun externalValueAndFieldSwitchResetTheWorkingValue() {
        var firstValue = "12"
        var secondValue = "9"
        val firstChange: (String) -> Unit = { firstValue = it }
        val secondChange: (String) -> Unit = { secondValue = it }
        val firstGetter: () -> String = { firstValue }
        val secondGetter: () -> String = { secondValue }
        val keypad = NumericKeypadState()

        keypad.bind(firstGetter, firstChange)
        keypad.input("3")
        assertEquals("123", firstValue)

        firstValue = "7"
        keypad.input("8")
        assertEquals("78", firstValue)

        keypad.unbind(firstChange)
        keypad.bind(secondGetter, secondChange)
        keypad.input("0")
        assertEquals("90", secondValue)
    }

    @Test
    fun inputKeepsDecimalAndTotalLengthLimits() {
        var value = ""
        val keypad = NumericKeypadState()
        keypad.bind({ value }, { value = it })

        "123456789".forEach { keypad.input(it.toString()) }
        keypad.input(".")
        keypad.input("4")
        keypad.input("5")
        keypad.input("6")

        assertEquals("123456789.45", value)
    }
}
