package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CurrencyExchange
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material3.Icon
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles

/** Choice sheet shown after the standard "记一笔" action. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseActionSheet(
    onDismiss: () -> Unit,
    onNewExpense: (() -> Unit)?,
    onRefund: (() -> Unit)?,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = SharedLedgerSpacing.Large)
                .padding(bottom = SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        ) {
            Text("选择记账类型", style = SharedLedgerTextStyles.SectionTitle)
            onNewExpense?.let { callback ->
                TextButton(onClick = { onDismiss(); callback() }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Rounded.Edit, contentDescription = null)
                    Text("普通记账", modifier = Modifier.padding(start = SharedLedgerSpacing.Small))
                }
            }
            onRefund?.let { callback ->
                TextButton(onClick = { onDismiss(); callback() }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Rounded.CurrencyExchange, contentDescription = null)
                    Text("退款", modifier = Modifier.padding(start = SharedLedgerSpacing.Small))
                }
            }
        }
    }
}
