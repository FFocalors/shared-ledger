package com.ffocalors.sharedledger.ui.agent

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.agent.ConfirmableProposalCard
import com.ffocalors.sharedledger.data.agent.ExpensePreview
import com.ffocalors.sharedledger.data.agent.InactiveProposalCard
import com.ffocalors.sharedledger.data.agent.ProposalCard
import com.ffocalors.sharedledger.data.agent.ProposalMode
import com.ffocalors.sharedledger.data.agent.ProposalOperation
import com.ffocalors.sharedledger.data.agent.SimulationProposalCard
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.theme.AgentSimulationContainer
import com.ffocalors.sharedledger.ui.theme.AgentSimulationContent
import com.ffocalors.sharedledger.ui.theme.AppOutline
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SoftCharcoal
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer

private val DraftHeaderInk = Color(0xFF4A4A4A)
private val OutlineWidth = 1.5.dp
private val OutlineGap = 2.dp

/**
 * The one bold element of the panel: an unsigned voucher. Dashed outline, header strip, right-aligned
 * amount. No shadow, no gradient. Unknown card kinds render nothing.
 */
@Composable
fun ProposalDraftCard(
    card: ProposalCard,
    names: AgentNameResolver,
    modifier: Modifier = Modifier,
    /** Play the draw-on entrance. Callers pass true once per proposal_id and only for live drafts. */
    animateEntrance: Boolean = false,
    onEntranceStarted: () -> Unit = {},
    confirmState: ProposalConfirmUiState = ProposalConfirmUiState(),
    onConfirm: (String) -> Unit = {},
) {
    // A newer revision of the same draft only cross-fades; the draw-on belongs to the first card.
    val firstCard = remember { card }
    val motion = rememberMotionEnabled()
    Crossfade(
        targetState = card,
        animationSpec = tween(if (motion) RevisionFadeMs else 0),
        label = "draftRevision",
    ) { shown ->
        DraftCardContent(
            card = shown,
            names = names,
            modifier = modifier,
            animateEntrance = animateEntrance && shown === firstCard,
            onEntranceStarted = onEntranceStarted,
            confirmState = confirmState,
            onConfirm = onConfirm,
        )
    }
}

/** Per-draft confirm affordance: in flight, answered 501, or already dispatched. */
data class ProposalConfirmUiState(
    val confirming: Boolean = false,
    val unavailable: Boolean = false,
    val submitted: Boolean = false,
)

@Composable
private fun DraftCardContent(
    card: ProposalCard,
    names: AgentNameResolver,
    modifier: Modifier,
    animateEntrance: Boolean,
    onEntranceStarted: () -> Unit,
    confirmState: ProposalConfirmUiState,
    onConfirm: (String) -> Unit,
) {
    when (card) {
        is SimulationProposalCard -> DraftCardFrame(
            proposalId = card.proposalId,
            operation = card.operation,
            mode = ProposalMode.SIMULATION,
            headerNote = ProposalPresentation.SIMULATION_NOTICE,
            preview = card.preview,
            showConfirm = true,
            inactive = false,
            names = names,
            modifier = modifier,
            animateEntrance = animateEntrance,
            onEntranceStarted = onEntranceStarted,
            confirmState = ProposalConfirmUiState(),
            onConfirm = {},
        )
        is ConfirmableProposalCard -> DraftCardFrame(
            proposalId = card.proposalId,
            operation = card.operation,
            mode = ProposalMode.BACKEND,
            headerNote = null,
            preview = card.preview,
            showConfirm = !confirmState.submitted,
            inactive = false,
            names = names,
            modifier = modifier,
            animateEntrance = animateEntrance,
            onEntranceStarted = onEntranceStarted,
            confirmState = confirmState,
            onConfirm = onConfirm,
        )
        is InactiveProposalCard -> DraftCardFrame(
            proposalId = card.proposalId,
            operation = card.operation,
            mode = card.mode,
            headerNote = ProposalPresentation.statusLabel(card.status),
            preview = card.preview,
            showConfirm = false,
            inactive = true,
            names = names,
            modifier = modifier,
            animateEntrance = false,
            onEntranceStarted = {},
            confirmState = ProposalConfirmUiState(),
            onConfirm = {},
        )
        else -> Unit
    }
}

@Composable
private fun DraftCardFrame(
    proposalId: String,
    operation: ProposalOperation,
    mode: ProposalMode,
    headerNote: String?,
    preview: ExpensePreview?,
    showConfirm: Boolean,
    inactive: Boolean,
    names: AgentNameResolver,
    modifier: Modifier,
    animateEntrance: Boolean,
    onEntranceStarted: () -> Unit,
    confirmState: ProposalConfirmUiState,
    onConfirm: (String) -> Unit,
) {
    val drawOn = rememberDraftDrawOn(animateEntrance, onEntranceStarted)
    val simulation = mode == ProposalMode.SIMULATION
    val headerContainer = if (simulation) AgentSimulationContainer else WarmOrangeContainer
    val headerContent = if (simulation) AgentSimulationContent else DraftHeaderInk
    val outlineColor = if (simulation) AgentSimulationContent else AppOutline
    val density = LocalDensity.current
    val innerShape = RoundedCornerShape(SharedLedgerRadius.LargeCorner - OutlineGap)

    Column(
        modifier = modifier
            .fillMaxWidth()
            .then(if (inactive) Modifier.alpha(0.6f) else Modifier)
            .dashedOutlineDrawOn(
                color = outlineColor,
                strokeWidthPx = with(density) { OutlineWidth.toPx() },
                cornerRadiusPx = with(density) { SharedLedgerRadius.LargeCorner.toPx() },
                progress = { drawOn.outline.value },
            )
            .padding(OutlineGap + OutlineWidth)
            .clip(innerShape),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .fillFromStart(headerContainer) { drawOn.header.value }
                .padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.Small),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Text(
                text = ProposalPresentation.operationTitle(operation),
                style = SharedLedgerTextStyles.BottomActionEmphasizedLabel,
                color = headerContent,
                modifier = Modifier.weight(1f),
            )
            if (headerNote != null) {
                Text(
                    text = headerNote,
                    style = SharedLedgerTextStyles.Label,
                    color = headerContent,
                    textAlign = TextAlign.End,
                    modifier = Modifier.widthIn(max = 160.dp),
                )
            }
        }
        if (preview != null) {
            DraftBody(
                preview = preview,
                names = names,
                showConfirm = showConfirm,
                simulation = simulation,
                proposalId = proposalId,
                confirmState = confirmState,
                onConfirm = onConfirm,
                amountProgress = { drawOn.amount.value },
            )
        }
    }
}

@Composable
private fun DraftBody(
    preview: ExpensePreview,
    names: AgentNameResolver,
    showConfirm: Boolean,
    simulation: Boolean,
    proposalId: String,
    confirmState: ProposalConfirmUiState,
    onConfirm: (String) -> Unit,
    amountProgress: () -> Float,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(SharedLedgerSpacing.MediumSmall),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            Text(
                text = preview.after.title,
                style = SharedLedgerTextStyles.SectionTitle,
                color = DeepCharcoal,
                modifier = Modifier.weight(1f),
            )
            Text(
                text = rollingAmountText(preview, amountProgress()),
                style = SharedLedgerTextStyles.SubActivityAmount.copy(fontFeatureSettings = "tnum"),
                color = DeepCharcoal,
                textAlign = TextAlign.End,
            )
        }
        ProposalPresentation.rows(preview, names).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
                Text(
                    text = row.label,
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = SoftCharcoal,
                    modifier = Modifier.widthIn(min = 48.dp),
                )
                Text(
                    text = if (row.before != null) "${row.before} → ${row.after}" else row.after,
                    style = SharedLedgerTextStyles.BodySecondary.copy(fontFeatureSettings = "tnum"),
                    color = DeepCharcoal,
                    modifier = Modifier.weight(1f),
                )
            }
        }
        if (showConfirm) {
            Spacer(Modifier.height(SharedLedgerSpacing.XSmall))
            if (simulation) {
                // Simulation drafts never write the ledger, so their button never becomes usable.
                SharedLedgerButton(
                    text = ProposalPresentation.CONFIRM_LABEL,
                    onClick = {},
                    enabled = false,
                )
                Text(
                    text = ProposalPresentation.SIMULATION_CONFIRM_NOTE,
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = SoftCharcoal,
                )
            } else {
                SharedLedgerButton(
                    text = if (confirmState.confirming) {
                        ProposalPresentation.CONFIRMING_LABEL
                    } else {
                        ProposalPresentation.CONFIRM_LABEL
                    },
                    onClick = { onConfirm(proposalId) },
                    enabled = !confirmState.confirming,
                )
                Text(
                    text = if (confirmState.unavailable) {
                        ProposalPresentation.EXECUTION_UNAVAILABLE
                    } else {
                        ProposalPresentation.CONFIRM_NOTE
                    },
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = if (confirmState.unavailable) ErrorRed else SoftCharcoal,
                )
            }
        }
    }
}
