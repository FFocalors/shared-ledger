package com.ffocalors.sharedledger.ui.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.GroupAdd
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.components.ActivityKind
import com.ffocalors.sharedledger.ui.components.ActivityStatus
import com.ffocalors.sharedledger.ui.components.ActivityCardUiModel
import com.ffocalors.sharedledger.ui.components.AmountDisplay
import com.ffocalors.sharedledger.ui.components.AmountEmphasis
import com.ffocalors.sharedledger.ui.components.AmountSize
import com.ffocalors.sharedledger.ui.components.EmptyState
import com.ffocalors.sharedledger.ui.components.ErrorState
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.StatusChip
import com.ffocalors.sharedledger.ui.components.rememberPressScaleState
import com.ffocalors.sharedledger.ui.demo.DemoData
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.DeepCharcoal
import com.ffocalors.sharedledger.ui.theme.IconTintOrange
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmHighest
import com.ffocalors.sharedledger.ui.theme.SurfaceWarmLowest
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer

/**
 * 首页活动流。
 *
 * This screen renders activity data supplied by the host. Navigation and
 * activity creation/joining are supplied through callbacks.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onActivityClick: (ActivityCardUiModel) -> Unit,
    modifier: Modifier = Modifier,
    activities: List<ActivityCardUiModel> = emptyList(),
    isLoading: Boolean = false,
    errorMessage: String? = null,
    onRetry: () -> Unit = {},
    onFabClick: () -> Unit = {},
    onCreateActivity: () -> Unit = {},
    onJoinActivity: () -> Unit = {},
    userDisplayName: String = "我",
    onProfileClick: (() -> Unit)? = null,
) {
    var selectedTab by rememberSaveable { mutableStateOf(HomeTab.InProgress) }
    var sheetVisible by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val hazeState = rememberSharedLedgerHazeState()

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            SharedLedgerTopBar(
                title = "SharedLedger",
                avatarName = userDisplayName,
                onAvatarClick = onProfileClick,
                containerColor = AppBackground,
                hazeState = hazeState,
            )
        },
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
                        containerColor = WarmOrangeContainer,
                        contentColor = IconTintOrange,
                        shape = CircleShape,
                        elevation = androidx.compose.material3.FloatingActionButtonDefaults.elevation(
                            defaultElevation = SharedLedgerElevation.Floating,
                        ),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Add,
                            contentDescription = "添加活动",
                            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
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
                    .fillMaxSize()
                    .sharedLedgerHazeSource(hazeState),
                verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
                contentPadding = PaddingValues(
                    top = innerPadding.calculateTopPadding(),
                    bottom = innerPadding.calculateBottomPadding() + SharedLedgerDimens.FabClearance,
                ),
            ) {
            item {
                HomeTabs(
                    selectedTab = selectedTab,
                    onSelected = { selectedTab = it },
                    modifier = Modifier.padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                )
            }

            if (isLoading) {
                item { LoadingState() }
            } else if (errorMessage != null) {
                item { ErrorState(message = errorMessage, onRetry = onRetry) }
            } else if (selectedTab == HomeTab.InProgress) {
                val visibleActivities = activities.filter { it.status != ActivityStatus.Archived }
                if (visibleActivities.isEmpty()) {
                    item {
                        EmptyState(
                            title = "暂无进行中的活动",
                            description = "点击右下角按钮创建或加入一个活动。",
                        )
                    }
                } else {
                    items(visibleActivities, key = { it.activityId }) { activity ->
                        HomeActivityCard(
                            activity = activity,
                            onClick = { onActivityClick(activity) },
                            modifier = Modifier
                                .animateItem()
                                .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                            showAmount = true,
                        )
                    }
                }
            } else {
                val archivedActivities = activities.filter { it.status == ActivityStatus.Archived }
                if (archivedActivities.isEmpty()) {
                    item { EmptyState(title = "暂无已归档活动") }
                } else {
                    items(archivedActivities, key = { it.activityId }) { activity ->
                        HomeActivityCard(
                            activity = activity,
                            onClick = { onActivityClick(activity) },
                            showAmount = false,
                            modifier = Modifier
                                .animateItem()
                                .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                        )
                    }
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
        HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
    }
}

@Composable
private fun HomeTabButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val indicatorColor = MaterialTheme.colorScheme.primary
    val indicatorAlpha by animateFloatAsState(
        targetValue = if (selected) 1f else 0f,
        animationSpec = tween(
            durationMillis = SharedLedgerMotion.Durations.TabIndicator,
            easing = SharedLedgerMotion.Easing.Position,
        ),
        label = "tabIndicator",
    )
    val textColor by animateColorAsState(
        targetValue = if (selected) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
        animationSpec = tween(
            durationMillis = SharedLedgerMotion.Durations.TabIndicator,
            easing = SharedLedgerMotion.Easing.Position,
        ),
        label = "tabText",
    )
    Column(
        modifier = Modifier
            .clickable(onClick = onClick)
            .padding(top = SharedLedgerSpacing.MediumSmall)
            .drawBehind {
                if (indicatorAlpha > 0f) {
                    val indicatorHeight = (SharedLedgerSpacing.XSmall / 2).toPx()
                    drawRect(
                        color = indicatorColor.copy(alpha = indicatorAlpha),
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
            color = textColor,
            maxLines = 1,
            softWrap = false,
        )
        Spacer(Modifier.height(SharedLedgerSpacing.MediumSmall))
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
    val pressScale = rememberPressScaleState()
    Card(
        onClick = onClick,
        modifier = pressScale.modifier.then(modifier).fillMaxWidth(),
        interactionSource = pressScale.interactionSource,
        shape = SharedLedgerRadius.ExtraLarge,
        colors = CardDefaults.cardColors(containerColor = SurfaceWarmLowest),
        border = BorderStroke(
            SharedLedgerDimens.OutlineWidth,
            SurfaceWarmHighest.copy(alpha = SharedLedgerDimens.CardBorderAlpha),
        ),
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
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
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
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
                StatusChip(activity.status)
            }

            if (showAmount) {
                Spacer(Modifier.height(SharedLedgerSpacing.Large))
                if (activity.amountAvailable && activity.totalAmount != null) {
                    Text(
                        text = "总应承担",
                        style = SharedLedgerTextStyles.Label,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    AmountDisplay(
                        amount = activity.totalAmount,
                        currencyCode = activity.currencyCode,
                        size = AmountSize.Large,
                        emphasis = AmountEmphasis.Primary,
                    )
                } else {
                    Text(
                        text = "未绑定参与人",
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(SharedLedgerSpacing.Large))
            } else {
                Spacer(Modifier.height(SharedLedgerSpacing.Medium))
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
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
            .padding(
                horizontal = SharedLedgerDimens.PageHorizontalPadding,
                vertical = SharedLedgerSpacing.MediumSmall,
            ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Surface(
            modifier = Modifier.size(SharedLedgerDimens.IconContainerLarge),
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

private fun ActivityKind.label(): String = when (this) {
    ActivityKind.Standard -> "普通活动"
    ActivityKind.Large -> "大型活动"
}

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun HomeScreenPreview() {
    com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme {
        HomeScreen(
            onActivityClick = {},
            activities = listOf(DemoData.japanTravel, DemoData.weekendDinner),
        )
    }
}
