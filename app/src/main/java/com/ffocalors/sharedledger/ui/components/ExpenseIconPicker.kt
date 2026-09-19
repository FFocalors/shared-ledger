package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AttachMoney
import androidx.compose.material.icons.rounded.CardGiftcard
import androidx.compose.material.icons.rounded.ConfirmationNumber
import androidx.compose.material.icons.rounded.DirectionsCar
import androidx.compose.material.icons.rounded.Flight
import androidx.compose.material.icons.rounded.Hotel
import androidx.compose.material.icons.rounded.LocalGasStation
import androidx.compose.material.icons.rounded.LocalGroceryStore
import androidx.compose.material.icons.rounded.MedicalServices
import androidx.compose.material.icons.rounded.Movie
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.ShoppingBag
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.data.expense.ExpenseIconKey
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest

@Immutable
private data class ExpenseIconOption(
    val key: String,
    val label: String,
    val icon: ImageVector,
)

private val ExpenseIconOptions = listOf(
    ExpenseIconOption(ExpenseIconKey.MONEY, "通用", Icons.Rounded.AttachMoney),
    ExpenseIconOption(ExpenseIconKey.DINING, "餐饮", Icons.Rounded.Restaurant),
    ExpenseIconOption(ExpenseIconKey.SHOPPING, "购物", Icons.Rounded.ShoppingBag),
    ExpenseIconOption(ExpenseIconKey.TRANSPORT, "交通", Icons.Rounded.DirectionsCar),
    ExpenseIconOption(ExpenseIconKey.HOTEL, "住宿", Icons.Rounded.Hotel),
    ExpenseIconOption(ExpenseIconKey.TICKET, "票券", Icons.Rounded.ConfirmationNumber),
    ExpenseIconOption(ExpenseIconKey.FUEL, "加油", Icons.Rounded.LocalGasStation),
    ExpenseIconOption(ExpenseIconKey.ENTERTAINMENT, "娱乐", Icons.Rounded.Movie),
    ExpenseIconOption(ExpenseIconKey.MEDICAL, "医疗", Icons.Rounded.MedicalServices),
    ExpenseIconOption(ExpenseIconKey.GIFT, "礼物", Icons.Rounded.CardGiftcard),
    ExpenseIconOption(ExpenseIconKey.GROCERY, "日用", Icons.Rounded.LocalGroceryStore),
    ExpenseIconOption(ExpenseIconKey.FLIGHT, "出行", Icons.Rounded.Flight),
)

fun expenseIconVector(iconKey: String?): ImageVector {
    val normalized = ExpenseIconKey.normalize(iconKey)
    return ExpenseIconOptions.firstOrNull { it.key == normalized }?.icon ?: Icons.Rounded.AttachMoney
}

fun expenseIconLabel(iconKey: String?): String {
    val normalized = ExpenseIconKey.normalize(iconKey)
    return ExpenseIconOptions.firstOrNull { it.key == normalized }?.label ?: "通用"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseIconPickerSheet(
    selectedKey: String,
    onSelected: (String) -> Unit,
    onDismissRequest: () -> Unit,
) {
    val normalizedSelected = ExpenseIconKey.normalize(selectedKey)
    // 点选后先播放选中反馈，再播放面板滑出动画（hide 为入场动画的倒放），最后通知父级移除。
    var pendingSelection by remember { mutableStateOf<String?>(null) }
    var exiting by remember { mutableStateOf(false) }
    val sheetState = androidx.compose.material3.rememberModalBottomSheetState(
        skipPartiallyExpanded = true,
    )
    // 退场时淡出与滑出并行播放，两段动画重叠成一段连续运动。
    val contentAlpha by androidx.compose.animation.core.animateFloatAsState(
        targetValue = if (exiting) 0f else 1f,
        animationSpec = androidx.compose.animation.core.tween(durationMillis = 200),
        label = "iconPickerContentAlpha",
    )
    LaunchedEffect(pendingSelection) {
        val key = pendingSelection ?: return@LaunchedEffect
        kotlinx.coroutines.delay(150)
        onSelected(key)
        exiting = true
        runCatching { sheetState.hide() }
        onDismissRequest()
    }
    ModalBottomSheet(
        onDismissRequest = onDismissRequest,
        sheetState = sheetState,
        containerColor = SurfaceWarmLowest,
        shape = SharedLedgerRadius.ExtraLarge,
        tonalElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(bottom = SharedLedgerSpacing.Large)
                .alpha(contentAlpha),
        ) {
            Text(
                text = "选择消费图标",
                modifier = Modifier.padding(
                    start = SharedLedgerSpacing.Large,
                    end = SharedLedgerSpacing.Large,
                    bottom = SharedLedgerSpacing.Medium,
                ),
                style = SharedLedgerTextStyles.SectionTitle,
                color = MaterialTheme.colorScheme.onSurface,
            )
            LazyVerticalGrid(
                columns = GridCells.Fixed(4),
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 360.dp),
                contentPadding = PaddingValues(horizontal = SharedLedgerSpacing.Large),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            ) {
                items(ExpenseIconOptions, key = ExpenseIconOption::key) { option ->
                    val isSelected = if (pendingSelection != null) {
                        option.key == pendingSelection
                    } else {
                        option.key == normalizedSelected
                    }
                    Surface(
                        onClick = {
                            if (pendingSelection == null) pendingSelection = option.key
                        },
                        enabled = pendingSelection == null,
                        modifier = Modifier
                            .heightIn(min = 76.dp)
                            .semantics {
                                selected = isSelected
                                role = Role.RadioButton
                                contentDescription = "${option.label}图标"
                            },
                        shape = SharedLedgerRadius.Medium,
                        color = if (isSelected) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            MaterialTheme.colorScheme.surface
                        },
                        contentColor = if (isSelected) {
                            MaterialTheme.colorScheme.onPrimaryContainer
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        border = BorderStroke(
                            SharedLedgerDimens.OutlineWidth,
                            if (isSelected) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.outlineVariant.copy(alpha = .55f),
                        ),
                    ) {
                        Column(
                            modifier = Modifier.padding(
                                horizontal = SharedLedgerSpacing.XSmall,
                                vertical = SharedLedgerSpacing.Small,
                            ),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                        ) {
                            Surface(
                                shape = SharedLedgerRadius.Full,
                                color = if (isSelected) {
                                    MaterialTheme.colorScheme.primary.copy(alpha = .13f)
                                } else {
                                    MaterialTheme.colorScheme.surfaceVariant
                                },
                                contentColor = if (isSelected) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.onSurfaceVariant
                                },
                            ) {
                                Box(
                                    modifier = Modifier.padding(SharedLedgerSpacing.XSmall),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(
                                        imageVector = option.icon,
                                        contentDescription = null,
                                        modifier = Modifier.size(SharedLedgerDimens.ActionIcon),
                                    )
                                }
                            }
                            Text(
                                text = option.label,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                textAlign = TextAlign.Center,
                                style = SharedLedgerTextStyles.Label,
                            )
                        }
                    }
                }
            }
        }
    }
}
