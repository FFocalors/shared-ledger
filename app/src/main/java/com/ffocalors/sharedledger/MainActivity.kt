package com.ffocalors.sharedledger

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.navigation.SharedLedgerApp
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SharedLedgerTheme {
                SharedLedgerApp()
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun GreetingPreview() {
    SharedLedgerTheme {
        SharedLedgerApp()
    }
}
