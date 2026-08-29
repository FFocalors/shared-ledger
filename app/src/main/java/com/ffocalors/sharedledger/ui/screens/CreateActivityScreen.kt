package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowForward
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.CurrencyExchange
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.Payments
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer

/**
 * Static V0.1 create-activity form. The integration layer owns navigation and
 * receives the selected [ActivityKind] from [onCreate].
 */
@Composable
fun CreateActivityScreen(
    modifier: Modifier = Modifier,
    onBackClick: () -> Unit = {},
    onCreate: (ActivityKind) -> Unit = {},
) {
    var activityName by rememberSaveable { mutableStateOf("") }
    var selectedKindName by rememberSaveable { mutableStateOf(ActivityKind.Standard.name) }
    var multiCurrencyEnabled by rememberSaveable { mutableStateOf(false) }
    val selectedKind = ActivityKind.values().firstOrNull { it.name == selectedKindName }
        ?: ActivityKind.Standard

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            SharedLedgerTopBar(
                title = "创建活动",
                showBackButton = true,
                onBackClick = onBackClick,
                modifier = Modifier.statusBarsPadding(),
                // The shared top bar keeps its standard trailing action slot;
                // it is intentionally inert on this transactional screen.
                onMoreClick = {},
            )
        },
        bottomBar = {
            CreateActivityBottomBar(onClick = { onCreate(selectedKind) })
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .padding(
                        start = SharedLedgerDimens.PageHorizontalPadding,
                        top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                        end = SharedLedgerDimens.PageHorizontalPadding,
                        bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Large,
                    )
                    .verticalScroll(rememberScrollState())
                    .imePadding(),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
            ) {
                CreateActivityNameSection(
                    value = activityName,
                    onValueChange = { activityName = it },
                )
                CreateActivityTypeSection(
                    selectedKind = selectedKind,
                    onKindSelected = { selectedKindName = it.name },
                )
                CreateActivitySettingsSection(
                    multiCurrencyEnabled = multiCurrencyEnabled,
                    onMultiCurrencyChange = { multiCurrencyEnabled = it },
                )
            }
        }
    }
}

@Composable
private fun CreateActivityNameSection(
    value: String,
    onValueChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        CreateSectionLabel(text = "活动名称")
        SharedLedgerTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.fillMaxWidth(),
            placeholder = "例如：毕业旅行",
        )
    }
}

@Composable
private fun CreateActivityTypeSection(
    selectedKind: ActivityKind,
    onKindSelected: (ActivityKind) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        CreateSectionLabel(text = "活动类型")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            ActivityTypeCard(
                kind = ActivityKind.Standard,
                title = "普通活动",
                description = "适合聚餐、短途游，\n按笔结算。",
                icon = Icons.Rounded.Restaurant,
                selected = selectedKind == ActivityKind.Standard,
                onClick = { onKindSelected(ActivityKind.Standard) },
                modifier = Modifier.weight(1f),
            )
            ActivityTypeCard(
                kind = ActivityKind.Large,
                title = "大型活动",
                description = "适合长途旅行，支持\n多阶段记账。",
                icon = Icons.Rounded.FlightTakeoff,
                selected = selectedKind == ActivityKind.Large,
                onClick = { onKindSelected(ActivityKind.Large) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun ActivityTypeCard(
    kind: ActivityKind,
    title: String,
    description: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val surfaceColor = if (selected) {
        MaterialTheme.colorScheme.surface
    } else {
        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.34f)
    }
    val iconContainer = if (selected) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    val iconTint = if (selected) {
        MaterialTheme.colorScheme.onPrimaryContainer
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        modifier = modifier
            .height(150.dp)
            .clickable(onClick = onClick),
        shape = SharedLedgerRadius.ExtraLarge,
        color = surfaceColor,
        border = BorderStroke(
            width = if (selected) 2.dp else 1.dp,
            color = if (selected) MaterialTheme.colorScheme.primary
            else Color.Transparent,
        ),
        shadowElevation = if (selected) SharedLedgerElevation.Card else 0.dp,
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            ) {
                Surface(
                    modifier = Modifier.padding(bottom = SharedLedgerSpacing.Small),
                    shape = CircleShape,
                    color = iconContainer,
                    contentColor = iconTint,
                ) {
                    Box(
                        modifier = Modifier.padding(10.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = icon,
                            contentDescription = null,
                            modifier = Modifier.width(20.dp),
                        )
                    }
                }
                Text(
                    text = title,
                    style = SharedLedgerTextStyles.CardTitle,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = description,
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (selected) {
                Surface(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(SharedLedgerSpacing.Medium),
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Check,
                        contentDescription = "已选择${if (kind == ActivityKind.Standard) "普通活动" else "大型活动"}",
                        modifier = Modifier.padding(3.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun CreateActivitySettingsSection(
    multiCurrencyEnabled: Boolean,
    onMultiCurrencyChange: (Boolean) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        CreateSectionLabel(text = "基础设置")
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = SharedLedgerRadius.ExtraLarge,
            color = MaterialTheme.colorScheme.surface,
            border = BorderStroke(
                width = SharedLedgerDimens.OutlineWidth,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
            ),
            shadowElevation = SharedLedgerElevation.Card,
        ) {
            Column {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {}
                        .padding(SharedLedgerSpacing.MediumLarge),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
                ) {
                    SettingsIcon(icon = Icons.Rounded.Payments)
                    Text(
                        text = "主货币",
                        modifier = Modifier.weight(1f),
                        style = SharedLedgerTextStyles.Body,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "CNY 人民币",
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Icon(
                        imageVector = Icons.Rounded.ChevronRight,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(SharedLedgerDimens.OutlineWidth)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.68f)),
                )
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SharedLedgerSpacing.MediumLarge),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall),
                ) {
                    SettingsIcon(icon = Icons.Rounded.CurrencyExchange)
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "开启多币种",
                            style = SharedLedgerTextStyles.Body,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = "支持在活动中记录不同货币",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }
                    Switch(
                        checked = multiCurrencyEnabled,
                        onCheckedChange = onMultiCurrencyChange,
                        modifier = Modifier.scale(0.86f),
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                            checkedTrackColor = MaterialTheme.colorScheme.primary,
                            uncheckedThumbColor = MaterialTheme.colorScheme.surface,
                            uncheckedTrackColor = MaterialTheme.colorScheme.surfaceVariant,
                            uncheckedBorderColor = Color.Transparent,
                        ),
                    )
                }
            }
        }
    }
}

@Composable
private fun SettingsIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
) {
    Surface(
        modifier = Modifier.width(32.dp),
        shape = CircleShape,
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Box(
            modifier = Modifier.padding(6.dp),
            contentAlignment = Alignment.Center,
        ) {
            Icon(imageVector = icon, contentDescription = null)
        }
    }
}

@Composable
private fun CreateSectionLabel(text: String) {
    Text(
        text = text,
        modifier = Modifier.padding(start = SharedLedgerSpacing.XSmall),
        style = SharedLedgerTextStyles.BodySecondary,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun CreateActivityBottomBar(onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    colors = listOf(Color.Transparent, AppBackground),
                ),
            )
            .imePadding()
            .navigationBarsPadding()
            .padding(
                start = SharedLedgerDimens.PageHorizontalPadding,
                top = SharedLedgerSpacing.XLarge,
                end = SharedLedgerDimens.PageHorizontalPadding,
                bottom = SharedLedgerSpacing.Large,
            ),
    ) {
        Button(
            onClick = onClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
            shape = androidx.compose.foundation.shape.RoundedCornerShape(20.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = WarmOrangeContainer,
                contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
            ),
            elevation = ButtonDefaults.buttonElevation(defaultElevation = 2.dp),
        ) {
            Text(
                text = "创建活动",
                style = SharedLedgerTextStyles.CardTitle,
            )
            Spacer(modifier = Modifier.width(SharedLedgerSpacing.Small))
            Icon(
                imageVector = Icons.Rounded.ArrowForward,
                contentDescription = null,
            )
        }
    }
}

@Preview(name = "创建活动", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun CreateActivityScreenPreview() {
    SharedLedgerTheme {
        CreateActivityScreen()
    }
}
