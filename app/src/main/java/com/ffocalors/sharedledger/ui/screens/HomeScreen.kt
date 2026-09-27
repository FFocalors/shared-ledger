package com.ffocalors.sharedledger.ui.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.spring
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
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
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.lerp
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.material3.ripple
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalDensity
import kotlinx.coroutines.launch
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
import com.ffocalors.sharedledger.ui.components.HomeActivityCardSkeleton
import com.ffocalors.sharedledger.ui.components.LoadingState
import com.ffocalors.sharedledger.ui.components.ParticipantAvatarGroup
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.components.StatusChip
import com.ffocalors.sharedledger.ui.components.rememberPressScaleState
import com.ffocalors.sharedledger.ui.components.pressInnerShadow
import com.ffocalors.sharedledger.ui.components.specularMachinedBorder
import com.ffocalors.sharedledger.ui.theme.rememberSharedLedgerHaptics
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
    userAvatarStyle: String? = null,
    userId: String = "",
    onProfileClick: (() -> Unit)? = null,
) {
    val pagerState = rememberPagerState(initialPage = 0) { HomeTab.entries.size }
    val coroutineScope = rememberCoroutineScope()
    var sheetVisible by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val hazeState = rememberSharedLedgerHazeState()
    val haptics = rememberSharedLedgerHaptics()

    // 翻页到位时触发磁吸咬合触觉反馈（过滤初次进入）
    var isInitialSettled by remember { mutableStateOf(true) }
    LaunchedEffect(pagerState) {
        snapshotFlow { pagerState.settledPage }.collect {
            if (isInitialSettled) {
                isInitialSettled = false
            } else {
                haptics.snap()
            }
        }
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            SharedLedgerTopBar(
                title = "SharedLedger",
                avatarName = userDisplayName,
                avatarStyle = userAvatarStyle,
                avatarStableKey = userId,
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
                            haptics.click()
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
            Column(
                modifier = Modifier
                    .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                    .fillMaxSize()
                    .padding(top = innerPadding.calculateTopPadding()),
            ) {
                // 固定在顶部的标签切换栏（带连续平滑滑动指示器）
                HomeTabs(
                    pagerState = pagerState,
                    onTabSelected = { tab ->
                        coroutineScope.launch {
                            pagerState.animateScrollToPage(
                                page = tab.ordinal,
                                animationSpec = spring(
                                    dampingRatio = 0.85f,
                                    stiffness = 380f,
                                ),
                            )
                        }
                    },
                    modifier = Modifier.padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                )

                // 左右横滑与点击联动的双页面 HorizontalPager
                HorizontalPager(
                    state = pagerState,
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                ) { page ->
                    val tab = HomeTab.entries[page]
                    val contentPadding = PaddingValues(
                        top = SharedLedgerSpacing.Medium,
                        bottom = innerPadding.calculateBottomPadding() + SharedLedgerDimens.FabClearance,
                    )
                    when (tab) {
                        HomeTab.InProgress -> {
                            val visibleActivities = activities.filter { it.status != ActivityStatus.Archived }
                            HomeActivityList(
                                activities = visibleActivities,
                                isLoading = isLoading,
                                errorMessage = errorMessage,
                                onRetry = onRetry,
                                onActivityClick = onActivityClick,
                                showAmount = true,
                                emptyTitle = "暂无进行中的活动",
                                emptyDescription = "点击右下角按钮创建或加入一个活动。",
                                contentPadding = contentPadding,
                                hazeState = hazeState,
                            )
                        }
                        HomeTab.Archived -> {
                            val archivedActivities = activities.filter { it.status == ActivityStatus.Archived }
                            HomeActivityList(
                                activities = archivedActivities,
                                isLoading = isLoading,
                                errorMessage = errorMessage,
                                onRetry = onRetry,
                                onActivityClick = onActivityClick,
                                showAmount = false,
                                emptyTitle = "暂无已归档活动",
                                emptyDescription = null,
                                contentPadding = contentPadding,
                                hazeState = hazeState,
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

/**
 * 首页切换标签栏（精密连续滑动指示条 + 随滑动手势平滑插值变色）
 */
@Composable
private fun HomeTabs(
    pagerState: androidx.compose.foundation.pager.PagerState,
    onTabSelected: (HomeTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    val haptics = rememberSharedLedgerHaptics()
    val density = LocalDensity.current

    var tabsRootLeftPx by remember { mutableFloatStateOf(0f) }
    var tab0TextLeftPx by remember { mutableFloatStateOf(0f) }
    var tab0TextWidthPx by remember { mutableFloatStateOf(0f) }
    var tab1TextLeftPx by remember { mutableFloatStateOf(0f) }
    var tab1TextWidthPx by remember { mutableFloatStateOf(0f) }

    // 连续位置插值 (0f..1f)，手势滑动与动画滚动均平滑过渡
    val position = (pagerState.currentPage + pagerState.currentPageOffsetFraction)
        .coerceIn(0f, (HomeTab.entries.size - 1).toFloat())

    // 亚像素级连续滑动的指示条坐标与宽度（精准吸附在文本下方）
    val indicatorLeftPx = if (tab0TextWidthPx > 0f && tab1TextWidthPx > 0f) {
        val rel0 = tab0TextLeftPx - tabsRootLeftPx
        val rel1 = tab1TextLeftPx - tabsRootLeftPx
        rel0 + (rel1 - rel0) * position
    } else {
        0f
    }
    val indicatorWidthPx = if (tab0TextWidthPx > 0f && tab1TextWidthPx > 0f) {
        tab0TextWidthPx + (tab1TextWidthPx - tab0TextWidthPx) * position
    } else {
        0f
    }

    val selectedColor = MaterialTheme.colorScheme.primary
    val unselectedColor = MaterialTheme.colorScheme.onSurfaceVariant

    // 标签文字颜色跟随滑动进度连续平滑插值
    val inProgressColor = lerp(
        start = unselectedColor,
        stop = selectedColor,
        fraction = (1f - position).coerceIn(0f, 1f),
    )
    val archivedColor = lerp(
        start = unselectedColor,
        stop = selectedColor,
        fraction = position.coerceIn(0f, 1f),
    )

    Column(
        modifier = modifier
            .fillMaxWidth()
            .onGloballyPositioned { coordinates ->
                tabsRootLeftPx = coordinates.positionInRoot().x
            },
    ) {
        Box(modifier = Modifier.fillMaxWidth()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Large),
            ) {
                // Tab 0: 进行中（全圆角药丸水波纹与交互轮廓，杜绝直角阴影）
                val tab0InteractionSource = remember { MutableInteractionSource() }
                Box(
                    modifier = Modifier
                        .clip(SharedLedgerRadius.Full)
                        .clickable(
                            interactionSource = tab0InteractionSource,
                            indication = ripple(
                                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.08f),
                            ),
                            role = androidx.compose.ui.semantics.Role.Tab,
                            onClick = {
                                if (pagerState.currentPage != HomeTab.InProgress.ordinal) {
                                    haptics.tick()
                                }
                                onTabSelected(HomeTab.InProgress)
                            },
                        )
                        .padding(horizontal = SharedLedgerSpacing.Small, vertical = SharedLedgerSpacing.MediumSmall),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "进行中",
                        modifier = Modifier.onGloballyPositioned { coordinates ->
                            tab0TextLeftPx = coordinates.positionInRoot().x
                            tab0TextWidthPx = coordinates.size.width.toFloat()
                        },
                        style = SharedLedgerTextStyles.CardTitle,
                        color = inProgressColor,
                        maxLines = 1,
                        softWrap = false,
                    )
                }

                // Tab 1: 已归档（全圆角药丸水波纹与交互轮廓，杜绝直角阴影）
                val tab1InteractionSource = remember { MutableInteractionSource() }
                Box(
                    modifier = Modifier
                        .clip(SharedLedgerRadius.Full)
                        .clickable(
                            interactionSource = tab1InteractionSource,
                            indication = ripple(
                                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.08f),
                            ),
                            role = androidx.compose.ui.semantics.Role.Tab,
                            onClick = {
                                if (pagerState.currentPage != HomeTab.Archived.ordinal) {
                                    haptics.tick()
                                }
                                onTabSelected(HomeTab.Archived)
                            },
                        )
                        .padding(horizontal = SharedLedgerSpacing.Small, vertical = SharedLedgerSpacing.MediumSmall),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "已归档",
                        modifier = Modifier.onGloballyPositioned { coordinates ->
                            tab1TextLeftPx = coordinates.positionInRoot().x
                            tab1TextWidthPx = coordinates.size.width.toFloat()
                        },
                        style = SharedLedgerTextStyles.CardTitle,
                        color = archivedColor,
                        maxLines = 1,
                        softWrap = false,
                    )
                }
            }

            // 精密滑动指示条（绝对定位在底部分割线上方，圆角冷光质感）
            if (indicatorWidthPx > 0f) {
                val indicatorLeftDp = with(density) { indicatorLeftPx.toDp() }
                val indicatorWidthDp = with(density) { indicatorWidthPx.toDp() }

                Box(
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .offset(x = indicatorLeftDp)
                        .width(indicatorWidthDp)
                        .height(3.dp)
                        .clip(SharedLedgerRadius.Full)
                        .background(selectedColor),
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))
    }
}

/**
 * 独立的活动列表容器，各自维护滚动状态并支持毛玻璃虚化
 */
@Composable
private fun HomeActivityList(
    activities: List<ActivityCardUiModel>,
    isLoading: Boolean,
    errorMessage: String?,
    onRetry: () -> Unit,
    onActivityClick: (ActivityCardUiModel) -> Unit,
    showAmount: Boolean,
    emptyTitle: String,
    emptyDescription: String? = null,
    contentPadding: PaddingValues,
    hazeState: dev.chrisbanes.haze.HazeState,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .sharedLedgerHazeSource(hazeState),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        contentPadding = contentPadding,
    ) {
        if (isLoading) {
            items(3, key = { "home-skeleton-$it" }) {
                HomeActivityCardSkeleton(modifier = Modifier.animateItem())
            }
        } else if (errorMessage != null) {
            item { ErrorState(message = errorMessage, onRetry = onRetry) }
        } else if (activities.isEmpty()) {
            item {
                EmptyState(
                    title = emptyTitle,
                    description = emptyDescription,
                )
            }
        } else {
            items(activities, key = { it.activityId }) { activity ->
                HomeActivityCard(
                    activity = activity,
                    onClick = { onActivityClick(activity) },
                    modifier = Modifier
                        .animateItem()
                        .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
                    showAmount = showAmount,
                )
            }
        }
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
        modifier = pressScale.modifier.then(modifier).fillMaxWidth()
            .pressInnerShadow(SharedLedgerRadius.ExtraLarge, pressScale.shadowAlpha)
            .specularMachinedBorder(SharedLedgerRadius.ExtraLarge, highlightAlpha = 0.32f),
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
        Box(
            modifier = Modifier
                .size(SharedLedgerDimens.IconContainerLarge)
                .clip(CircleShape)
                .background(WarmOrangeContainer),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSecondaryContainer,
            )
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
