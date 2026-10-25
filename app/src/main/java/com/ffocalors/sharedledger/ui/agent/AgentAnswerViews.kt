package com.ffocalors.sharedledger.ui.agent

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountBalanceWallet
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.HourglassTop
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.ReceiptLong
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material.icons.outlined.Undo
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ffocalors.sharedledger.data.agent.MissingSlot
import com.ffocalors.sharedledger.ui.theme.AgentSimulationContainer
import com.ffocalors.sharedledger.ui.theme.AgentSimulationContent
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.ErrorContainer
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.IconContainerNeutral
import com.ffocalors.sharedledger.ui.theme.IconContainerNeutralTint
import com.ffocalors.sharedledger.ui.theme.IconContainerOrange
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.IconTintOrange
import com.ffocalors.sharedledger.ui.theme.IconTintSage
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SoftCharcoal
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import kotlin.math.min
import kotlinx.coroutines.delay

// Ledger reveal: the sheet frame appears, then each row fades in. Fade only, no movement.
private const val RowFadeMs = 160
private const val RowStaggerMs = 70
private const val RowRevealCapMs = 560

private val RowPadding = 12.dp
private val PlateSize = 28.dp

/**
 * An assistant reply. Prose streams in; records the Agent listed (debts, expenses, activities, refunds,
 * prepayments) become one ledger sheet; "no result" statements become a status strip. Lines the parser
 * does not recognise stay prose, so nothing the Agent said is hidden.
 */
@Composable
internal fun AssistantAnswer(
    text: String,
    animate: Boolean,
    playKey: String,
    onPlayed: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val segments = remember(text) { AnswerBlocks.parse(text) }
    // A sheet that follows streamed prose waits for that prose to finish.
    val leadIns = remember(segments, animate) {
        var acc = 0
        segments.map { segment ->
            val delayMs = acc
            if (animate && segment is AnswerSegment.Prose) acc += streamDurationMs(segment.text.length)
            delayMs
        }
    }
    LaunchedEffect(playKey) { if (animate) onPlayed(playKey) }
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        segments.forEachIndexed { index, segment ->
            when (segment) {
                is AnswerSegment.Prose -> StreamingText(
                    text = segment.text,
                    animate = animate,
                    style = SharedLedgerTextStyles.Body,
                    color = DeepCharcoal,
                    modifier = Modifier.fillMaxWidth(),
                )
                is AnswerSegment.Ledger -> LedgerSheet(segment, animate, leadIns[index])
                is AnswerSegment.Notice -> StatusStrip(
                    tone = if (segment.incomplete) StripTone.Reconciling else StripTone.Neutral,
                    text = segment.text,
                    animate = false,
                    glyph = if (segment.incomplete) Icons.Outlined.WarningAmber else Icons.Outlined.Info,
                )
            }
        }
    }
}

// ---- ledger sheet ------------------------------------------------------------------------------

@Composable
private fun LedgerSheet(sheet: AnswerSegment.Ledger, animate: Boolean, startDelayMs: Int) {
    val rowCount = sheet.entries.size + if (sheet.lead != null) 1 else 0
    val stepMs = if (rowCount <= 1) 0 else min(RowStaggerMs, (RowRevealCapMs - RowFadeMs) / (rowCount - 1))
    val totalMs = RowFadeMs + stepMs * (rowCount - 1).coerceAtLeast(0)
    val progress = remember(sheet) { Animatable(if (animate) 0f else totalMs.toFloat()) }
    LaunchedEffect(sheet, animate) {
        if (animate) {
            delay(startDelayMs.toLong())
            progress.animateTo(totalMs.toFloat(), tween(totalMs, easing = LinearEasing))
        }
    }
    val alphaOf: (Int) -> Float = { index -> ((progress.value - index * stepMs) / RowFadeMs).coerceIn(0f, 1f) }
    val headerRows = if (sheet.lead != null) 1 else 0

    Column(
        modifier = Modifier
            .fillMaxWidth()
            // The page frame shows as soon as the reveal starts; rows are then "written" onto it.
            .graphicsLayer { alpha = if (progress.value > 0f) 1f else 0f }
            .clip(SharedLedgerRadius.Medium)
            .background(AppSurface)
            .border(1.dp, AppOutlineVariant, SharedLedgerRadius.Medium),
    ) {
        if (sheet.lead != null) {
            LedgerHeader(sheet.lead, sheet.partial, Modifier.graphicsLayer { alpha = alphaOf(0) })
        }
        sheet.entries.forEachIndexed { index, entry ->
            if (index > 0 || sheet.lead != null) HorizontalDivider(color = AppOutlineVariant)
            Box(Modifier.graphicsLayer { alpha = alphaOf(index + headerRows) }) { LedgerRow(entry) }
        }
    }
}

@Composable
private fun LedgerHeader(lead: String, partial: Boolean, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(if (partial) IconContainerOrange else Color.Transparent)
            .padding(horizontal = RowPadding, vertical = SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (partial) Icons.Outlined.WarningAmber else Icons.Outlined.CheckCircle,
            contentDescription = null,
            tint = if (partial) IconTintOrange else IconTintSage,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(SharedLedgerSpacing.Small))
        Text(
            text = lead,
            style = SharedLedgerTextStyles.BodySecondary,
            color = if (partial) IconTintOrange else SoftCharcoal,
        )
    }
}

@Composable
private fun LedgerRow(entry: LedgerEntry) {
    when (entry) {
        is LedgerEntry.Debt -> DebtRow(entry)
        is LedgerEntry.Expense -> ExpenseRow(entry)
        is LedgerEntry.Activity -> ActivityRow(entry)
        is LedgerEntry.Fact -> FactRow(entry)
        is LedgerEntry.Note -> NoteRow(entry)
    }
}

/** One glyph plate shared by every row type: the type is told by the glyph, not by colour. */
@Composable
private fun IconPlate(glyph: ImageVector, modifier: Modifier = Modifier, warning: Boolean = false) {
    Box(
        modifier = modifier
            .size(PlateSize)
            .clip(CircleShape)
            .background(if (warning) IconContainerOrange else IconContainerNeutral),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = glyph,
            contentDescription = null,
            tint = if (warning) IconTintOrange else IconContainerNeutralTint,
            modifier = Modifier.size(16.dp),
        )
    }
}

@Composable
private fun DebtRow(entry: LedgerEntry.Debt) {
    val description = buildString {
        append(entry.debtor).append(" 欠 ").append(entry.creditor)
        entry.amount?.let { append(' ').append(it.amount).append(' ').append(it.currency) }
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) { contentDescription = description }
            .padding(horizontal = RowPadding, vertical = 10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        IconPlate(Icons.Outlined.SwapHoriz)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                text = buildAnnotatedString {
                    append(entry.debtor)
                    withStyle(SpanStyle(color = SoftCharcoal)) { append("  →  ") }
                    append(entry.creditor)
                },
                style = SharedLedgerTextStyles.SummaryStatValue,
                color = DeepCharcoal,
            )
            entry.note?.let { RowDetail(it) }
        }
        entry.amount?.let {
            Spacer(Modifier.width(10.dp))
            AmountText(it)
        }
    }
}

@Composable
private fun ExpenseRow(entry: LedgerEntry.Expense) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = RowPadding, vertical = 10.dp)
            .semantics(mergeDescendants = true) {},
    ) {
        Row(verticalAlignment = Alignment.Top) {
            IconPlate(Icons.Outlined.ReceiptLong)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(entry.title, style = SharedLedgerTextStyles.SummaryStatValue, color = DeepCharcoal)
                val base = entry.base
                if (base != null && base != entry.amount) RowDetail("基准 ${base.amount} ${base.currency}")
            }
            entry.amount?.let {
                Spacer(Modifier.width(10.dp))
                AmountText(it)
            }
        }
        entry.lines.forEach { line ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = PlateSize + 10.dp, top = 6.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Text(
                    text = listOf(line.role, line.name).filter { it.isNotEmpty() }.joinToString(" "),
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = SoftCharcoal,
                    modifier = Modifier.weight(1f),
                )
                line.amount?.let {
                    Spacer(Modifier.width(10.dp))
                    Text(
                        text = it.amount,
                        style = SharedLedgerTextStyles.BodySecondary.copy(fontFeatureSettings = "tnum"),
                        color = DeepCharcoal,
                        textAlign = TextAlign.End,
                    )
                }
            }
        }
    }
}

@Composable
private fun ActivityRow(entry: LedgerEntry.Activity) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) {}
            .padding(horizontal = RowPadding, vertical = 10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        IconPlate(Icons.Outlined.FolderOpen)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(entry.name, style = SharedLedgerTextStyles.SummaryStatValue, color = DeepCharcoal)
            if (entry.details.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    entry.details.forEach { MiniTag(activityDetailLabel(it)) }
                }
            }
        }
    }
}

@Composable
private fun FactRow(entry: LedgerEntry.Fact) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) {}
            .padding(horizontal = RowPadding, vertical = 10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        IconPlate(if (entry.kind == FactKind.Refund) Icons.Outlined.Undo else Icons.Outlined.AccountBalanceWallet)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(entry.title, style = SharedLedgerTextStyles.SummaryStatValue, color = DeepCharcoal)
            entry.details.forEach { RowDetail(it) }
        }
        entry.amount?.let {
            Spacer(Modifier.width(10.dp))
            AmountText(it)
        }
    }
}

@Composable
private fun NoteRow(entry: LedgerEntry.Note) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = RowPadding, vertical = 10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        IconPlate(if (entry.incomplete) Icons.Outlined.WarningAmber else Icons.Outlined.Info, warning = entry.incomplete)
        Spacer(Modifier.width(10.dp))
        Text(entry.text, style = SharedLedgerTextStyles.BodySecondary, color = DeepCharcoal, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun RowDetail(text: String) {
    Text(text, style = SharedLedgerTextStyles.Label, color = SoftCharcoal)
}

/** The server's digits, set in the app's tabular number face, with the currency as a small suffix. */
@Composable
private fun AmountText(money: Money, modifier: Modifier = Modifier) {
    Text(
        text = buildAnnotatedString {
            append(money.amount)
            withStyle(
                SpanStyle(
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    color = SoftCharcoal,
                ),
            ) { append(" ${money.currency}") }
        },
        style = SharedLedgerTextStyles.AmountSmall,
        color = DeepCharcoal,
        textAlign = TextAlign.End,
        softWrap = false,
        modifier = modifier,
    )
}

private fun activityDetailLabel(raw: String): String = when (raw) {
    "normal" -> "普通活动"
    "large" -> "大型活动"
    else -> raw
}

/** Small outlined tag: structure that carries a fact (kind, status, currency, what is missing). */
@Composable
internal fun MiniTag(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = SharedLedgerTextStyles.Label,
        color = SoftCharcoal,
        modifier = modifier
            .clip(SharedLedgerRadius.Full)
            .border(1.dp, AppOutlineVariant, SharedLedgerRadius.Full)
            .padding(horizontal = 10.dp, vertical = 3.dp),
    )
}

// ---- status strip ------------------------------------------------------------------------------

internal enum class StripTone { Success, Rejected, Closed, Reconciling, Neutral }

/** One line with a round glyph: execution results, receipts and result notices share this look. */
@Composable
internal fun StatusStrip(
    tone: StripTone,
    text: String,
    animate: Boolean,
    modifier: Modifier = Modifier,
    glyph: ImageVector = defaultGlyph(tone),
    emphasis: Boolean = false,
) {
    val (container, tint) = when (tone) {
        StripTone.Success -> IconContainerSage to IconTintSage
        StripTone.Rejected -> ErrorContainer to ErrorRed
        StripTone.Closed -> AgentSimulationContainer to AgentSimulationContent
        StripTone.Reconciling -> IconContainerOrange to IconTintOrange
        StripTone.Neutral -> IconContainerNeutral to IconContainerNeutralTint
    }
    // The glyph "stamps" in when it appears as the consequence of the user's own confirmation.
    val scale = remember { Animatable(if (animate) 0.6f else 1f) }
    LaunchedEffect(Unit) {
        if (animate) scale.animateTo(1f, spring(dampingRatio = 0.55f, stiffness = Spring.StiffnessMediumLow))
    }
    Row(modifier = modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(20.dp)
                .graphicsLayer {
                    scaleX = scale.value
                    scaleY = scale.value
                }
                .clip(CircleShape)
                .background(container),
            contentAlignment = Alignment.Center,
        ) {
            Icon(glyph, contentDescription = null, tint = tint, modifier = Modifier.size(13.dp))
        }
        Spacer(Modifier.width(SharedLedgerSpacing.Small))
        Text(
            text = text,
            style = if (emphasis) SharedLedgerTextStyles.BottomActionEmphasizedLabel else SharedLedgerTextStyles.BodySecondary,
            color = if (emphasis) DeepCharcoal else SoftCharcoal,
            modifier = Modifier.weight(1f),
        )
    }
}

private fun defaultGlyph(tone: StripTone): ImageVector = when (tone) {
    StripTone.Success -> Icons.Outlined.Check
    StripTone.Rejected -> Icons.Outlined.Close
    StripTone.Closed -> Icons.Outlined.Lock
    StripTone.Reconciling -> Icons.Outlined.HourglassTop
    StripTone.Neutral -> Icons.Outlined.Info
}

/** Glyph for a submitted-execution receipt line. */
internal val ReceiptGlyph: ImageVector get() = Icons.Outlined.ReceiptLong

// ---- clarification -----------------------------------------------------------------------------

/** The Agent needs more from you: an amber margin rule, the question, and what is still missing. */
@Composable
internal fun ClarificationBlock(
    prompt: String,
    missing: List<MissingSlot>,
    animate: Boolean,
    playKey: String,
    onPlayed: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(playKey) { if (animate) onPlayed(playKey) }
    val labels = remember(missing) {
        missing.filter { it != MissingSlot.UNKNOWN }.map(AgentStatusCopy::missingSlotLabel).distinct()
    }
    Row(modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(
            Modifier
                .width(3.dp)
                .fillMaxHeight()
                .clip(RoundedCornerShape(2.dp))
                .background(WarmOrangeContainer),
        )
        Spacer(Modifier.width(10.dp))
        Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
            StreamingText(
                text = prompt,
                animate = animate,
                style = SharedLedgerTextStyles.Body,
                color = DeepCharcoal,
                modifier = Modifier.fillMaxWidth(),
            )
            if (labels.isNotEmpty()) {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = "还缺",
                        style = SharedLedgerTextStyles.Label,
                        color = SoftCharcoal,
                        modifier = Modifier.align(Alignment.CenterVertically),
                    )
                    labels.forEach { MiniTag(it) }
                }
            }
        }
    }
}
