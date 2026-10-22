package com.ffocalors.sharedledger.ui.agent

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyItemScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.agent.SessionSummary
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppOutlineVariant
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.ErrorContainer
import com.ffocalors.sharedledger.ui.theme.ErrorRed
import com.ffocalors.sharedledger.ui.theme.SageGreenSoft
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SoftCharcoal
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter

/** Everything the sheet can ask the host to do. */
data class AgentSheetActions(
    val onDismiss: () -> Unit = {},
    val onSend: (String) -> Unit = {},
    val onStop: () -> Unit = {},
    val onRetry: () -> Unit = {},
    val onRetryMessage: () -> Unit = {},
    val onDismissBanner: () -> Unit = {},
    val onOpenHistory: () -> Unit = {},
    val onCloseHistory: () -> Unit = {},
    val onNewConversation: () -> Unit = {},
    val onOpenSession: (String) -> Unit = {},
    /** Called when an item's entrance animation starts, so it never plays twice. */
    val onEntrancePlayed: (String) -> Unit = {},
)

@Composable
fun AgentAssistantSheet(
    state: AgentUiState,
    names: AgentNameResolver,
    actions: AgentSheetActions,
    visible: Boolean = true,
    onDismissed: () -> Unit = actions.onDismiss,
    demoMode: Boolean = false,
) {
    var expandRequest by rememberSaveable { mutableIntStateOf(0) }
    AgentBottomSheet(
        visible = visible,
        onDismissed = onDismissed,
        startExpanded = state.items.isNotEmpty(),
        expandRequest = expandRequest,
    ) {
        AgentAssistantContent(
            state = state,
            names = names,
            actions = actions,
            demoMode = demoMode,
            modifier = Modifier.fillMaxSize(),
            onComposerFocused = { expandRequest++ },
        )
    }
}

/** The sheet body, free of the bottom-sheet container so previews can render it. */
@Composable
fun AgentAssistantContent(
    state: AgentUiState,
    names: AgentNameResolver,
    actions: AgentSheetActions,
    modifier: Modifier = Modifier,
    onComposerFocused: () -> Unit = {},
    demoMode: Boolean = false,
) {
    // Hoisted so the empty-state suggestions can fill the composer.
    var draft by rememberSaveable { mutableStateOf("") }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(AppBackground)
            .navigationBarsPadding()
            .imePadding(),
    ) {
        TitleRow(state.view, actions)
        if (state.view == AgentPanelView.History) {
            HistoryView(state, actions, Modifier.weight(1f))
        } else {
            if (state.pageLabel.isNotBlank()) {
                Text(
                    text = "正在看：${state.pageLabel}",
                    style = SharedLedgerTextStyles.Label,
                    color = SoftCharcoal,
                    modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium),
                )
            }
            if (demoMode) {
                Text(
                    text = "演示模式：回复由本机模拟，不会连接助手服务，也不会记账。",
                    style = SharedLedgerTextStyles.Label,
                    color = SoftCharcoal,
                    modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium),
                )
            }
            HorizontalDivider(
                modifier = Modifier.padding(top = SharedLedgerSpacing.Small),
                color = AppOutlineVariant,
            )
            Transcript(state, names, actions, { draft = it }, Modifier.weight(1f))
            Footer(state, actions, draft, onComposerFocused) { draft = it }
        }
    }
}

@Composable
private fun TitleRow(view: AgentPanelView, actions: AgentSheetActions) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = SharedLedgerSpacing.Medium, end = SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (view == AgentPanelView.History) "历史对话" else "记账助手",
            style = SharedLedgerTextStyles.SectionTitle,
            color = DeepCharcoal,
            modifier = Modifier.weight(1f),
        )
        if (view == AgentPanelView.History) {
            TextButton(onClick = actions.onCloseHistory) { Text("返回对话", color = DeepCharcoal) }
        } else {
            TextButton(onClick = actions.onOpenHistory) { Text("历史", color = DeepCharcoal) }
        }
        IconButton(onClick = actions.onDismiss) {
            Icon(Icons.Outlined.Close, contentDescription = "关闭", tint = DeepCharcoal)
        }
    }
}

@Composable
private fun Transcript(
    state: AgentUiState,
    names: AgentNameResolver,
    actions: AgentSheetActions,
    onPickSuggestion: (String) -> Unit,
    modifier: Modifier,
) {
    val listState = rememberLazyListState()
    val context = LocalContext.current
    val animationsOn = remember(state.items.size) {
        areAnimationsEnabled(context)
    }
    val motion = rememberMotionEnabled()
    LaunchedEffect(state.items.size) {
        val last = state.items.lastIndex
        if (last >= 0) {
            if (animationsOn) listState.animateScrollToItem(last) else listState.scrollToItem(last)
        }
    }
    if (state.items.isEmpty()) {
        EmptyState(onPickSuggestion, modifier)
        return
    }
    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(SharedLedgerSpacing.Medium),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
    ) {
        items(state.items, key = { it.key }) { item ->
            TranscriptRow(item, state, names, actions, motion, Modifier.entranceItem(item, motion, this))
        }
    }
}

private val Suggestions = listOf(
    "昨天烧烤 750，我付的，四个人平分",
    "这个活动现在谁还欠我钱？",
    "我这次一共花了多少？",
)

@Composable
private fun EmptyState(onPick: (String) -> Unit, modifier: Modifier) {
    Column(
        modifier = modifier.fillMaxWidth().padding(SharedLedgerSpacing.Medium),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Text(
            text = "说一笔要记的账，或者问问谁还欠多少钱。",
            style = SharedLedgerTextStyles.Body,
            color = SoftCharcoal,
        )
        Spacer(Modifier.height(SharedLedgerSpacing.XSmall))
        Suggestions.forEach { suggestion ->
            Text(
                text = suggestion,
                style = SharedLedgerTextStyles.Body,
                color = DeepCharcoal,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(SharedLedgerRadius.Input)
                    .background(AppBackground)
                    .border(1.dp, AppOutlineVariant, SharedLedgerRadius.Input)
                    .clickable(onClickLabel = "填入输入框", role = Role.Button) { onPick(suggestion) }
                    .heightIn(min = 48.dp)
                    .padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.Small),
            )
        }
    }
}

/** Newly sent user messages glide into place; everything else keeps the list's default behavior. */
private fun Modifier.entranceItem(item: TranscriptItem, motion: Boolean, scope: LazyItemScope): Modifier =
    if (motion && item is UserTextItem && item.animateEntrance) {
        with(scope) { this@entranceItem.animateItem(fadeInSpec = null, fadeOutSpec = null) }
    } else {
        this
    }

@Composable
private fun TranscriptRow(
    item: TranscriptItem,
    state: AgentUiState,
    names: AgentNameResolver,
    actions: AgentSheetActions,
    motion: Boolean,
    modifier: Modifier,
) {
    // Decided once when the row first composes: live, not yet played, and the system allows motion.
    val playKey = if (item is ProposalItem) item.proposalId else item.key
    val animate = remember(item.key) {
        motion && item.animatesEntrance() && playKey !in state.playedEntrances
    }
    when (item) {
        is UserTextItem -> UserBubble(item, animate, modifier)
        is AssistantMessageItem -> StreamedReply(item.text, animate, playKey, actions, modifier)
        is ClarificationItem -> StreamedReply(item.prompt, animate, playKey, actions, modifier)
        is ExecutionResultItem ->
            Text(item.line, style = SharedLedgerTextStyles.BodySecondary, color = SoftCharcoal, modifier = modifier)
        is ErrorItem -> ErrorRow(item.message, item.retryable, actions.onRetryMessage, modifier)
        is ProposalItem -> state.cards[item.proposalId]?.let {
            ProposalDraftCard(
                card = it,
                names = names,
                modifier = modifier,
                animateEntrance = animate,
                onEntranceStarted = { actions.onEntrancePlayed(playKey) },
            )
        }
    }
}

private fun TranscriptItem.animatesEntrance(): Boolean = when (this) {
    is UserTextItem -> animateEntrance
    is AssistantMessageItem -> animateEntrance
    is ClarificationItem -> animateEntrance
    is ProposalItem -> animateEntrance
    else -> false
}

@Composable
private fun UserBubble(item: UserTextItem, animate: Boolean, modifier: Modifier) {
    val rise = remember(item.key) { Animatable(if (animate) 12f else 0f) }
    LaunchedEffect(item.key) {
        if (animate) rise.animateTo(0f, spring(dampingRatio = 0.72f, stiffness = Spring.StiffnessMediumLow))
    }
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        Text(
            text = item.text,
            style = SharedLedgerTextStyles.Body,
            color = DeepCharcoal,
            modifier = Modifier
                .graphicsLayer { translationY = rise.value.dp.toPx() }
                .widthIn(max = 300.dp)
                .clip(SharedLedgerRadius.Large)
                .background(SageGreenSoft)
                .padding(horizontal = SharedLedgerSpacing.MediumSmall, vertical = SharedLedgerSpacing.Small),
        )
    }
}

@Composable
private fun StreamedReply(
    text: String,
    animate: Boolean,
    playKey: String,
    actions: AgentSheetActions,
    modifier: Modifier,
) {
    LaunchedEffect(playKey) { if (animate) actions.onEntrancePlayed(playKey) }
    StreamingText(
        text = text,
        animate = animate,
        style = SharedLedgerTextStyles.Body,
        color = DeepCharcoal,
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
private fun ErrorRow(message: String, canRetry: Boolean, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(SharedLedgerRadius.Medium)
            .background(ErrorContainer)
            .padding(start = SharedLedgerSpacing.MediumSmall, top = SharedLedgerSpacing.Small, bottom = SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = message,
            style = SharedLedgerTextStyles.BodySecondary,
            color = DeepCharcoal,
            modifier = Modifier.weight(1f),
        )
        if (canRetry) {
            TextButton(onClick = onRetry) { Text("重试", color = ErrorRed) }
        }
    }
}

@Composable
private fun Footer(
    state: AgentUiState,
    actions: AgentSheetActions,
    draft: String,
    onComposerFocused: () -> Unit,
    onDraftChange: (String) -> Unit) {
    Column(
        modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.Small),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        state.banner?.let { banner ->
            ErrorRow(
                message = banner.message,
                canRetry = banner.canRetry,
                onRetry = actions.onRetry,
                modifier = Modifier.clickable(onClick = actions.onDismissBanner),
            )
        }
        val line = state.notice ?: state.statusLine
        if (line != null) {
            if (state.notice == null && state.isRunning) {
                ShimmerStatus(text = line, modifier = Modifier.semantics { contentDescription = line })
            } else {
                Text(
                    text = line,
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = SoftCharcoal,
                    modifier = Modifier.semantics { contentDescription = line },
                )
            }
        }
        Composer(state, actions, draft, onComposerFocused, onDraftChange)
    }
}

@Composable
private fun Composer(
    state: AgentUiState,
    actions: AgentSheetActions,
    text: String,
    onFocused: () -> Unit,
    onTextChange: (String) -> Unit) {
    val motion = rememberMotionEnabled()
    val running = state.composer == ComposerMode.Running
    val placeholder = when (val mode = state.composer) {
        is ComposerMode.Clarification ->
            "补充：" + mode.missingSlots.joinToString("、") { AgentStatusCopy.missingSlotLabel(it) }
                .ifEmpty { "更多信息" }
        else -> "说一笔要记的账，或问谁还欠多少"
    }
    fun send() {
        val value = text.trim()
        if (value.isEmpty() || running) return
        actions.onSend(value)
        onTextChange("")
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            modifier = Modifier.weight(1f).heightIn(min = 56.dp).onFocusChanged { if (it.isFocused) onFocused() },
            enabled = !running,
            placeholder = { Text(placeholder, style = SharedLedgerTextStyles.Body) },
            textStyle = SharedLedgerTextStyles.Body,
            maxLines = 4,
            shape = SharedLedgerRadius.Input,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { send() }),
            colors = OutlinedTextFieldDefaults.colors(
                focusedContainerColor = androidx.compose.ui.graphics.Color.White,
                unfocusedContainerColor = androidx.compose.ui.graphics.Color.White,
                disabledContainerColor = AppBackground,
                focusedBorderColor = DeepCharcoal,
                unfocusedBorderColor = AppOutlineVariant,
                disabledBorderColor = AppOutlineVariant,
                disabledTextColor = SoftCharcoal,
                disabledPlaceholderColor = SoftCharcoal,
            ),
        )
        TextButton(
            onClick = if (running) actions.onStop else ::send,
            enabled = running || text.isNotBlank(),
        ) {
            AnimatedContent(
                targetState = running,
                transitionSpec = {
                    val duration = if (motion) 150 else 0
                    (fadeIn(tween(duration)) + scaleIn(tween(duration), initialScale = 0.6f))
                        .togetherWith(fadeOut(tween(duration)) + scaleOut(tween(duration), targetScale = 0.6f))
                },
                label = "sendStop",
            ) { isRunning ->
                Text(
                    text = if (isRunning) "停止" else "发送",
                    style = SharedLedgerTextStyles.Button,
                    color = if (isRunning || text.isNotBlank()) DeepCharcoal else SoftCharcoal,
                )
            }
        }
    }
}

@Composable
private fun HistoryView(state: AgentUiState, actions: AgentSheetActions, modifier: Modifier) {
    Column(modifier = modifier.fillMaxSize()) {
        TextButton(
            onClick = actions.onNewConversation,
            modifier = Modifier.padding(horizontal = SharedLedgerSpacing.Small),
        ) { Text("新对话", color = DeepCharcoal) }
        HorizontalDivider(color = AppOutlineVariant)
        state.banner?.let {
            ErrorRow(
                it.message, it.canRetry, actions.onRetry,
                Modifier.padding(SharedLedgerSpacing.Medium),
            )
        }
        when {
            state.sessions.isEmpty() && !state.sessionsLoading && state.banner == null -> Text(
                text = "还没有和助手的对话。",
                style = SharedLedgerTextStyles.Body,
                color = SoftCharcoal,
                modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            )
            else -> LazyColumn(Modifier.fillMaxWidth()) {
                items(state.sessions, key = { it.sessionId }) { session ->
                    SessionRow(session, session.sessionId == state.currentSessionId) {
                        actions.onOpenSession(session.sessionId)
                    }
                }
            }
        }
    }
}

@Composable
private fun SessionRow(session: SessionSummary, current: Boolean, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .heightIn(min = 56.dp)
            .padding(horizontal = SharedLedgerSpacing.Medium, vertical = SharedLedgerSpacing.Small),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = session.title?.takeIf { it.isNotBlank() } ?: "未命名对话",
            style = SharedLedgerTextStyles.Body,
            color = DeepCharcoal,
            maxLines = 1,
        )
        Text(
            text = UiDateTimeFormatter.format(session.updatedAt) + if (current) "，当前对话" else "",
            style = SharedLedgerTextStyles.Label,
            color = SoftCharcoal,
        )
    }
}
