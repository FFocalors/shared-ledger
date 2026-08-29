package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.GroupAdd
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.TaskAlt
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.components.ActivityStatus
import com.ffocalors.sharedledger.ui.components.ActivityCardUiModel
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.demo.DemoData
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmHighest
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.theme.sharedLedgerColors
import kotlinx.coroutines.launch

/**
 * 首页活动流。
 *
 * This screen intentionally owns only presentational/demo state. Navigation and
 * activity creation/joining are supplied by the host through callbacks.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onJapanTravelClick: () -> Unit,
    onWeekendDinnerClick: () -> Unit,
    modifier: Modifier = Modifier,
    onFabClick: () -> Unit = {},
    onCreateActivity: () -> Unit = {},
    onJoinActivity: () -> Unit = {},
) {
    var selectedTab by rememberSaveable { mutableStateOf(HomeTab.InProgress) }
    var sheetVisible by rememberSaveable { mutableStateOf(false) }
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            SharedLedgerTopBar(
                title = "SharedLedger",
                avatarName = "我",
                containerColor = AppBackground,
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
        floatingActionButton = {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .navigationBarsPadding(),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    modifier = Modifier
                        .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                        .fillMaxWidth()
                        .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                    contentAlignment = Alignment.CenterEnd,
                ) {
                    FloatingActionButton(
                        onClick = {
                            onFabClick()
                            sheetVisible = true
                        },
                        containerColor = FabOrange,
                        contentColor = Color.White,
                        shape = CircleShape,
                        elevation = androidx.compose.material3.FloatingActionButtonDefaults.elevation(
                            defaultElevation = SharedLedgerElevation.Floating,
                        ),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Add,
                            contentDescription = "添加活动",
                            modifier = Modifier.size(28.dp),
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
            LazyColumn(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxWidth()
                    .padding(innerPadding),
                contentPadding = PaddingValues(bottom = 96.dp),
            ) {
            item {
                HomeTabs(
                    selectedTab = selectedTab,
                    onSelected = { selectedTab = it },
                    modifier = Modifier.padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                )
            }

            item {
                Spacer(Modifier.height(SharedLedgerSpacing.Large))
            }

            if (selectedTab == HomeTab.InProgress) {
                item {
                    HomeActivityCard(
                        activity = DemoData.japanTravel,
                        onClick = onJapanTravelClick,
                        modifier = Modifier.padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                        showAmount = true,
                    )
                }
                item {
                    Spacer(Modifier.height(SharedLedgerSpacing.Large))
                }
                item {
                    HomeActivityCard(
                        activity = DemoData.weekendDinner,
                        onClick = onWeekendDinnerClick,
                        modifier = Modifier.padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                        showAmount = false,
                    )
                }
            } else {
                item {
                    EmptyArchivedState(
                        modifier = Modifier.padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                    )
                }
            }
            }
        }
    }

    if (sheetVisible) {
        ModalBottomSheet(
            onDismissRequest = { sheetVisible = false },
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
        ) {
            AddActivitySheetOption(
                icon = Icons.Rounded.Add,
                title = "创建活动",
                subtitle = "新建一个共享账本",
                onClick = {
                    sheetVisible = false
                    onCreateActivity()
                },
            )
            AddActivitySheetOption(
                icon = Icons.Rounded.GroupAdd,
                title = "加入活动",
                subtitle = "使用邀请码加入已有活动",
                onClick = {
                    sheetVisible = false
                    onJoinActivity()
                    scope.launch {
                        snackbarHostState.showSnackbar("加入活动功能将在后续接入")
                    }
                },
            )
            Spacer(Modifier.navigationBarsPadding().height(16.dp))
        }
    }
}

private enum class HomeTab {
    InProgress,
    Archived,
}

@Composable
private fun HomeTabs(
    selectedTab: HomeTab,
    onSelected: (HomeTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
        ) {
            HomeTabButton(
                label = "进行中",
                selected = selectedTab == HomeTab.InProgress,
                onClick = { onSelected(HomeTab.InProgress) },
            )
            HomeTabButton(
                label = "已归档",
                selected = selectedTab == HomeTab.Archived,
                onClick = { onSelected(HomeTab.Archived) },
            )
        }
        Divider(color = MaterialTheme.colorScheme.surfaceVariant)
    }
}

@Composable
private fun HomeTabButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val indicatorColor = MaterialTheme.colorScheme.primary
    Column(
        modifier = Modifier
            .clickable(onClick = onClick)
            .padding(top = 1.dp)
            .drawBehind {
                if (selected) {
                    val indicatorHeight = (SharedLedgerSpacing.XSmall / 2).toPx()
                    drawRect(
                        color = indicatorColor,
                        topLeft = Offset(0f, size.height - indicatorHeight),
                        size = Size(size.width, indicatorHeight),
                    )
                }
            },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = label,
            style = SharedLedgerTextStyles.CardTitle,
            color = if (selected) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            maxLines = 1,
            softWrap = false,
        )
        Spacer(Modifier.height(8.dp))
    }
}

/** The card markup follows the Stitch home frame; the generic ActivityCard has a different icon-led layout. */
@Composable
private fun HomeActivityCard(
    activity: ActivityCardUiModel,
    onClick: () -> Unit,
    showAmount: Boolean,
    modifier: Modifier = Modifier,
) {
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(1.dp, SurfaceWarmHighest.copy(alpha = 0.25f)),
        elevation = CardDefaults.cardElevation(defaultElevation = SharedLedgerElevation.Card),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Medium),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = activity.name,
                        style = SharedLedgerTextStyles.CardTitle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Icon(
                            imageVector = if (activity.kind == ActivityKind.Large) {
                                Icons.Rounded.FlightTakeoff
                            } else {
                                Icons.Rounded.Restaurant
                            },
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            text = activity.kind.label() + " · ${activity.participantCount}人",
                            style = SharedLedgerTextStyles.Label,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                HomeStatusBadge(status = activity.status)
            }

            if (showAmount && activity.totalAmount != null) {
                Spacer(Modifier.height(SharedLedgerSpacing.Large))
                Text(
                    text = "总金额",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                AmountDisplay(
                    amount = activity.totalAmount,
                    currencyCode = activity.currencyCode,
                    size = AmountSize.Large,
                    emphasis = AmountEmphasis.Primary,
                )
                Spacer(Modifier.height(SharedLedgerSpacing.Large))
            } else {
                Spacer(Modifier.height(SharedLedgerSpacing.Medium))
            }

            Divider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = SharedLedgerSpacing.Small),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "更新于 ${activity.updatedAt}",
                    modifier = Modifier.weight(1f),
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.outline,
                )
                ParticipantAvatarGroup(
                    participants = activity.participants,
                    avatarSize = 32.dp,
                    maxVisible = if (showAmount) 3 else 1,
                )
            }
        }
    }
}

@Composable
private fun HomeStatusBadge(
    status: ActivityStatus,
    modifier: Modifier = Modifier,
) {
    val semantic = MaterialTheme.sharedLedgerColors
    val isSettled = status == ActivityStatus.Settled
    Surface(
        modifier = modifier,
        shape = CircleShape,
        color = if (isSettled) semantic.successContainer else MaterialTheme.colorScheme.errorContainer,
        contentColor = if (isSettled) semantic.onSuccessContainer else MaterialTheme.colorScheme.onErrorContainer,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            if (isSettled) {
                Icon(
                    imageVector = Icons.Rounded.TaskAlt,
                    contentDescription = null,
                    modifier = Modifier.size(14.dp),
                )
            } else {
                Box(
                    modifier = Modifier
                        .size(6.dp),
                ) {
                    Surface(
                        modifier = Modifier.fillMaxSize(),
                        color = MaterialTheme.colorScheme.error,
                        shape = CircleShape,
                    ) {}
                }
            }
            Text(text = if (isSettled) "已结清" else "待结算", style = SharedLedgerTextStyles.Label)
        }
    }
}

@Composable
private fun AddActivitySheetOption(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Surface(
            modifier = Modifier.size(48.dp),
            shape = CircleShape,
            color = WarmOrangeContainer,
            contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(imageVector = icon, contentDescription = null)
            }
        }
        Column {
            Text(text = title, style = SharedLedgerTextStyles.CardTitle, color = DeepCharcoal)
            Text(
                text = subtitle,
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun EmptyArchivedState(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 72.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "暂无已归档活动",
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private fun ActivityKind.label(): String = when (this) {
    ActivityKind.Standard -> "普通活动"
    ActivityKind.Large -> "大型活动"
}

private val FabOrange = Color(0xFFFF9800)

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun HomeScreenPreview() {
    com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme {
        HomeScreen(
            onJapanTravelClick = {},
            onWeekendDinnerClick = {},
        )
    }
}
