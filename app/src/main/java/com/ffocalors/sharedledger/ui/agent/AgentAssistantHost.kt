package com.ffocalors.sharedledger.ui.agent

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavBackStackEntry
import com.ffocalors.sharedledger.BuildConfig
import com.ffocalors.sharedledger.data.agent.AgentConfig
import com.ffocalors.sharedledger.data.agent.AgentRepositoryFactory
import com.ffocalors.sharedledger.ui.activity.ActivityViewModel
import java.time.Instant

private val ContextArgumentNames = listOf("activityId", "ledgerUnitId", "expenseId")

/**
 * Floating entry + assistant sheet, overlaid once above the NavHost. Renders nothing when the Agent
 * endpoint is not configured or the current route has a text-entry keypad.
 */
@Composable
fun AgentAssistantHost(
    backStackEntry: NavBackStackEntry?,
    currentUserId: String,
    activityViewModel: ActivityViewModel,
    modifier: Modifier = Modifier,
) {
    val configured = remember { AgentConfig.agentAvailable() }
    if (!configured) return

    val route = backStackEntry?.destination?.route
    val args = remember(backStackEntry) {
        ContextArgumentNames.associateWith { backStackEntry?.arguments?.getString(it) }
    }
    val activityId = args["activityId"]
    val detailFlow = remember(activityId) { activityId?.let { activityViewModel.detail(it) } }
    val detail = detailFlow?.collectAsState()?.value?.detail

    val viewModel: AgentAssistantViewModel = viewModel(
        key = "agent-assistant-$currentUserId",
        factory = AgentAssistantViewModel.Factory(remember(currentUserId) { AgentRepositoryFactory.create() }),
    )
    val state by viewModel.state.collectAsState()
    var open by rememberSaveable { mutableStateOf(false) }

    val names = remember(detail) {
        AgentNameResolver(
            participants = detail?.participants.orEmpty().associate { it.id to it.name },
            ledgerUnits = detail?.ledgerUnits.orEmpty().associate { it.id to it.name },
        )
    }
    val currentRoute by rememberUpdatedState(route)
    val currentArgs by rememberUpdatedState(args)
    val activityName by rememberUpdatedState(detail?.summary?.name)
    fun pageContext(): AgentPageContext = AgentUiContextMapper.map(
        route = currentRoute,
        args = currentArgs,
        capturedAt = Instant.now().toString(),
        clientVersion = BuildConfig.VERSION_NAME,
        activityName = { activityName },
    )

    val entryScope = rememberCoroutineScope()
    val entryController = remember(entryScope) { AgentEntryController(entryScope) }
    LaunchedEffect(open) {
        viewModel.setPanelOpen(open)
        entryController.onSheetOpenChanged(open)
    }
    LaunchedEffect(route) { entryController.onRouteChanged(route) }
    LaunchedEffect(open, route, args, detail?.summary?.name) {
        if (open) viewModel.setPageLabel(pageContext().label)
    }

    Box(modifier = modifier) {
        if (!AgentUiContextMapper.isEntryHidden(route)) {
            AgentFloatingEntry(
                controller = entryController,
                onOpen = {
                    viewModel.setPageLabel(pageContext().label)
                    open = true
                },
                attention = !open && agentEntryNeedsAttention(state.turn?.state),
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .navigationBarsPadding()
                    .padding(bottom = 112.dp),
            )
        }
        run {
            AgentAssistantSheet(
                visible = open,
                onDismissed = { open = false },
                state = state,
                demoMode = AgentConfig.isDemo,
                names = names,
                actions = AgentSheetActions(
                    onDismiss = { open = false },
                    onSend = { viewModel.submit(it, pageContext().uiContext) },
                    onStop = viewModel::cancel,
                    onRetry = viewModel::retry,
                    onRetryMessage = { viewModel.retryLastMessage(pageContext().uiContext) },
                    onDismissBanner = viewModel::dismissBanner,
                    onOpenHistory = viewModel::openHistory,
                    onCloseHistory = viewModel::closeHistory,
                    onNewConversation = viewModel::newConversation,
                    onOpenSession = viewModel::openSession,
                    onEntrancePlayed = viewModel::markEntrancePlayed,
                ),
            )
        }
    }
}
