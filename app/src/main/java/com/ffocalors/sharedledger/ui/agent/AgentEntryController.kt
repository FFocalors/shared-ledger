package com.ffocalors.sharedledger.ui.agent

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.ffocalors.sharedledger.data.agent.TurnState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Tucked / revealed state of the floating entry plus its auto-retract rules. Pure (no Android
 * dependencies); the timer runs on [scope], so tests drive it with a test scheduler.
 *
 * - tap tucked -> reveal; tap revealed -> open the sheet (stays revealed while the sheet is open)
 * - revealed with no interaction for [autoRetractMs] -> tuck (null disables the timer)
 * - sheet closes -> tuck immediately; route changes -> tuck immediately
 */
class AgentEntryController(
    private val scope: CoroutineScope,
    private val autoRetractMs: Long? = DEFAULT_AUTO_RETRACT_MS,
    initialRevealed: Boolean = false,
) {
    var revealed: Boolean by mutableStateOf(initialRevealed)
        private set

    private var sheetOpen = false
    private var timer: Job? = null
    private var routeSeen = false
    private var lastRoute: String? = null

    init {
        if (initialRevealed) restartTimer()
    }

    fun reveal() {
        revealed = true
        restartTimer()
    }

    fun tuck() {
        cancelTimer()
        revealed = false
    }

    /** Tapping the entry: reveal when tucked, otherwise open the sheet. */
    fun onTap(openSheet: () -> Unit) {
        if (!revealed) reveal() else open(openSheet)
    }

    /** Opens the sheet regardless of state (accessibility action). */
    fun open(openSheet: () -> Unit) {
        sheetOpen = true
        cancelTimer()
        openSheet()
    }

    /** Any touch on the entry restarts the countdown while revealed. */
    fun onInteraction() {
        if (revealed) restartTimer()
    }

    fun onSheetOpenChanged(open: Boolean) {
        if (open) {
            sheetOpen = true
            cancelTimer()
        } else if (sheetOpen) {
            sheetOpen = false
            tuck()
        }
    }

    fun onRouteChanged(route: String?) {
        if (routeSeen && route != lastRoute) tuck()
        routeSeen = true
        lastRoute = route
    }

    private fun restartTimer() {
        cancelTimer()
        val timeout = autoRetractMs ?: return
        if (sheetOpen) return
        timer = scope.launch {
            delay(timeout)
            revealed = false
        }
    }

    private fun cancelTimer() {
        timer?.cancel()
        timer = null
    }

    companion object {
        const val DEFAULT_AUTO_RETRACT_MS = 4_000L
    }
}

/** True when a turn is still going or waiting on the user, i.e. the grip should be amber. */
fun agentEntryNeedsAttention(turn: TurnState?): Boolean =
    turn != null && turn != TurnState.UNKNOWN && !turn.isTerminal
