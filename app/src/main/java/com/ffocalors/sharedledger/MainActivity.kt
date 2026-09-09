package com.ffocalors.sharedledger

import android.os.Bundle
import android.content.Intent
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.navigation.SharedLedgerApp
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme

class MainActivity : ComponentActivity() {
    private var pendingAuthDeepLink by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingAuthDeepLink = intent?.dataString
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
        setContent {
            SharedLedgerTheme {
                SharedLedgerApp(
                    pendingAuthDeepLink = pendingAuthDeepLink,
                    onAuthDeepLinkConsumed = { pendingAuthDeepLink = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pendingAuthDeepLink = intent.dataString
    }
}

@Preview(showBackground = true)
@Composable
private fun GreetingPreview() {
    SharedLedgerTheme {
        SharedLedgerApp()
    }
}
