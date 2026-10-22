package com.ffocalors.sharedledger.debug

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding as navPad
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.ffocalors.sharedledger.ui.agent.AgentBottomSheet
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.agent.AgentAssistantContent
import com.ffocalors.sharedledger.ui.agent.AgentEntryController
import com.ffocalors.sharedledger.ui.agent.AgentFloatingEntry
import com.ffocalors.sharedledger.ui.agent.AgentSheetActions
import com.ffocalors.sharedledger.ui.agent.PreviewNames
import com.ffocalors.sharedledger.ui.agent.agentPreviewState
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme

/** Debug-only: renders the Agent panel with fake state. Usage: --es state sheet|empty|backend|simulation|inactive|clarification|error|entry|entry-revealed|entry-active */
class AgentUiPreviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.light(
                scrim = android.graphics.Color.TRANSPARENT,
                darkScrim = android.graphics.Color.TRANSPARENT,
            ),
            navigationBarStyle = SystemBarStyle.light(
                scrim = android.graphics.Color.TRANSPARENT,
                darkScrim = android.graphics.Color.TRANSPARENT,
            ),
        )
        val name = intent.getStringExtra("state") ?: "empty"
        setContent {
            SharedLedgerTheme {
                val state = agentPreviewState(name)
                if (name == "sheet") {
                    SheetPhysicsPreview()
                } else if (state == null) {
                    Box(Modifier.fillMaxSize().background(AppBackground).navigationBarsPadding()) {
                        val scope = rememberCoroutineScope()
                        val controller = remember {
                            AgentEntryController(
                                scope = scope,
                                autoRetractMs = if (name == "entry-revealed") null else AgentEntryController.DEFAULT_AUTO_RETRACT_MS,
                                initialRevealed = name == "entry-revealed",
                            )
                        }
                        AgentFloatingEntry(
                            controller = controller,
                            onOpen = {},
                            attention = name == "entry-active",
                            modifier = Modifier.align(Alignment.BottomStart).padding(bottom = 112.dp),
                        )
                    }
                } else {
                    var open by remember { mutableStateOf(true) }
                    var expandRequest by remember { mutableIntStateOf(0) }
                    Box(Modifier.fillMaxSize().background(AppBackground).statusBarsPadding()) {
                        Text(
                            if (open) "助手面板预览页" else "面板已关闭，点这里重新打开。",
                            Modifier.clickable { open = true }.padding(16.dp),
                        )
                        AgentBottomSheet(
                            visible = open,
                            onDismissed = { open = false },
                            startExpanded = state.items.isNotEmpty(),
                            expandRequest = expandRequest,
                        ) {
                            AgentAssistantContent(
                                state = state,
                                names = PreviewNames,
                                actions = AgentSheetActions(onDismiss = { open = false }),
                                modifier = Modifier.fillMaxSize(),
                                onComposerFocused = { expandRequest++ },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SheetPhysicsPreview() {
    var open by remember { mutableStateOf(true) }
    Box(Modifier.fillMaxSize().background(AppBackground).statusBarsPadding()) {
        Column(Modifier.padding(16.dp)) {
            Text("阻尼抽屉预览页")
            Text(if (open) "拖动、甩动、在列表里滚动，感受物理。" else "抽屉已关闭，点这里重新打开。", Modifier.clickable { open = true }.padding(top = 8.dp))
        }
        AgentBottomSheet(
            visible = open,
            onDismissed = { open = false },
            startExpanded = false,
            expandRequest = 0,
        ) {
            LazyColumn(Modifier.fillMaxWidth().weight(1f).navPad()) {
                items((1..40).toList()) { n ->
                    Text("第 $n 行", Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp))
                }
            }
        }
    }
}
