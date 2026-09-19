package com.ffocalors.sharedledger.ui.components

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.Transition
import androidx.compose.animation.core.animateDp
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.updateTransition
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.ComponentSizes
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerMotion
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles

/**
 * 币种胶囊 → 面板的就地流体形态变换（替代 SharedLedgerCurrencyDropdownMenu popup）。
 *
 * 展开时一个 Surface 从胶囊的位置/尺寸生长为完整币种列表面板：宽度、高度、圆角
 * 同步使用高阻尼 spring（见 [SharedLedgerMotion.Springs.FluidMorph]，damping 0.92 /
 * stiffness 260，无弹跳、丝滑减速），内容从收起态 crossfade 到选项列表（列表
 * fade + slide 进入，150~200ms）。收起为同一曲线的逆过程。
 *
 * 收起交互：点击展开态面板顶部当前币种行，或选中任一币种。展开期间不锁滚动、
 * 无全局外部点击层（就地组件位于 LazyColumn 内，天然被下方内容避让）。
 *
 * collapsedContent 自定义收起态外观（默认 "国旗 + 代码 + ▾" 胶囊）；其稳定收起
 * 尺寸作为形态变换的起始尺寸。
 */
@Composable
fun SharedLedgerFluidCurrencyPicker(
    expanded: Boolean,
    onExpandedChange: (Boolean) -> Unit,
    currencyCodes: List<String>,
    selectedCode: String,
    onSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    collapsedContent: @Composable () -> Unit = {
        DefaultCurrencyCapsule(selectedCode, enabled)
    },
) {
    val density = LocalDensity.current
    var collapsedSize by remember { mutableStateOf<DpSize?>(null) }
    var lastCollapsedSize by remember { mutableStateOf<DpSize?>(null) }
    val currencyListState = rememberLazyListState()
    // Keep drag and fling leftovers inside the currency panel. LazyColumn still
    // consumes every delta it can; only the remainder at either edge is
    // swallowed here instead of bubbling into the form's outer scrollable.
    val isolatedPanelScroll = remember {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource,
            ): Offset = Offset(x = 0f, y = available.y)

            override suspend fun onPostFling(
                consumed: Velocity,
                available: Velocity,
            ): Velocity = Velocity(x = 0f, y = available.y)
        }
    }
    val transition = updateTransition(expanded, label = "currencyFluidMorph")

    // 动画结束后把最近一次测得的收起态尺寸写回起始值：动画期间起始尺寸保持
    // 锁定，避免过渡中的中间尺寸被重新采样为目标值造成跳变。
    LaunchedEffect(transition.isRunning, lastCollapsedSize) {
        if (!transition.isRunning) {
            lastCollapsedSize?.let { collapsedSize = it }
        }
    }

    BoxWithConstraints(modifier) {
        val capsuleWidth = collapsedSize?.width ?: ComponentSizes.DropdownMinWidth
        val capsuleHeight = collapsedSize?.height ?: 36.dp
        val panelWidth = maxWidth.coerceIn(
            ComponentSizes.DropdownMinWidth,
            ComponentSizes.DropdownMaxWidth,
        )
        val optionsHeight = (currencyCodes.size * ComponentSizes.DropdownItemMinHeight.value).dp
            .coerceAtMost(ComponentSizes.DropdownMaxHeight - ComponentSizes.DropdownItemMinHeight)
        val panelHeight = ComponentSizes.DropdownItemMinHeight + optionsHeight

        val width by transition.fluidSize(capsuleWidth, panelWidth, "fluidWidth")
        val height by transition.fluidSize(capsuleHeight, panelHeight, "fluidHeight")
        val corner by transition.fluidSize(capsuleHeight / 2, SharedLedgerRadius.LargeCorner, "fluidCorner")
        val verticalInset by transition.fluidSize(
            0.dp,
            SharedLedgerSpacing.Small,
            "fluidVerticalInset",
        )
        // A spring may overshoot its target by a tiny amount even with high
        // damping. Keep layout-only values inside their valid ranges so a
        // reverse transition cannot produce negative padding or invalid
        // constraints, while all geometry still follows the same spring.
        val safeWidth = width.coerceBetween(capsuleWidth, panelWidth)
        val safeHeight = height.coerceBetween(capsuleHeight, panelHeight)
        val safeCorner = corner.coerceBetween(capsuleHeight / 2, SharedLedgerRadius.LargeCorner)
        val safeVerticalInset = verticalInset.coerceBetween(0.dp, SharedLedgerSpacing.Small)
        val listAlpha by transition.animateFloat(
            transitionSpec = { tween(SharedLedgerMotion.Durations.Content) },
            label = "listCrossfade",
        ) { if (it) 1f else 0f }

        Surface(
            modifier = Modifier
                // Keep the expanded panel visually detached from the enclosing
                // text-field/card border. The inset participates in the same
                // transition, so the collapsed capsule keeps its original size.
                .padding(vertical = safeVerticalInset)
                .widthIn(min = safeWidth, max = safeWidth)
                .heightIn(min = safeHeight, max = safeHeight),
            shape = RoundedCornerShape(safeCorner),
            color = if (expanded) {
                MaterialTheme.colorScheme.surface
            } else {
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.72f)
            },
            tonalElevation = 0.dp,
            shadowElevation = if (expanded) SharedLedgerElevation.Floating else 0.dp,
            border = BorderStroke(
                SharedLedgerDimens.OutlineWidth,
                MaterialTheme.colorScheme.outlineVariant.copy(
                    alpha = if (expanded) 1f else 0.52f,
                ),
            ),
        ) {
            Crossfade(
                targetState = expanded,
                animationSpec = tween(SharedLedgerMotion.Durations.Icon),
                label = "currencyContent",
            ) { isExpanded ->
                if (!isExpanded) {
                    Box(
                        modifier = Modifier
                            .onSizeChanged { px ->
                                // 无条件记录收起内容最新尺寸；仅在动画静止时
                                // （见上面的 LaunchedEffect）才写回起始尺寸。
                                if (px.width > 0) {
                                    lastCollapsedSize = with(density) {
                                        DpSize(px.width.toDp(), px.height.toDp())
                                    }
                                }
                            }
                            .then(
                                if (enabled) {
                                    Modifier.clickable { onExpandedChange(true) }
                                } else {
                                    Modifier
                                },
                            ),
                    ) {
                        collapsedContent()
                    }
                } else {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(listAlpha),
                    ) {
                        // 顶部当前币种行：点击收起。
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .defaultMinSize(minHeight = ComponentSizes.DropdownItemMinHeight)
                                .clickable { onExpandedChange(false) }
                                .padding(horizontal = SharedLedgerSpacing.Medium),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        ) {
                            CurrencyFlag(selectedCode)
                            Text(
                                text = currencyNameZh(selectedCode).ifBlank { selectedCode },
                                modifier = Modifier.weight(1f),
                                style = SharedLedgerTextStyles.BodySecondary,
                                color = MaterialTheme.colorScheme.primary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = selectedCode.uppercase(),
                                style = SharedLedgerTextStyles.Label,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Icon(
                                Icons.Rounded.KeyboardArrowDown,
                                contentDescription = "收起币种选择",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                            )
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        LazyColumn(
                            modifier = Modifier
                                .fillMaxWidth()
                                .weight(1f)
                                .nestedScroll(isolatedPanelScroll),
                            state = currencyListState,
                        ) {
                            items(
                                items = currencyCodes,
                                key = { it.uppercase() },
                            ) { code ->
                                val selected = code.equals(selectedCode, ignoreCase = true)
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .defaultMinSize(minHeight = ComponentSizes.DropdownItemMinHeight)
                                        .clickable {
                                            onSelected(code)
                                            onExpandedChange(false)
                                        }
                                        .padding(horizontal = SharedLedgerSpacing.Medium),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                                ) {
                                    CurrencyFlag(code)
                                    Text(
                                        text = currencyNameZh(code).ifBlank { code },
                                        modifier = Modifier.weight(1f),
                                        style = SharedLedgerTextStyles.BodySecondary,
                                        color = if (selected) {
                                            MaterialTheme.colorScheme.primary
                                        } else {
                                            MaterialTheme.colorScheme.onSurface
                                        },
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        text = code.uppercase(),
                                        style = SharedLedgerTextStyles.Label,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    if (selected) {
                                        Icon(
                                            Icons.Rounded.Check,
                                            contentDescription = "当前币种",
                                            tint = MaterialTheme.colorScheme.primary,
                                            modifier = Modifier.size(SharedLedgerDimens.IconSmall),
                                        )
                                    } else {
                                        Box(modifier = Modifier.size(SharedLedgerDimens.IconSmall))
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DefaultCurrencyCapsule(code: String, enabled: Boolean) {
    Row(
        modifier = Modifier.padding(
            horizontal = SharedLedgerSpacing.MediumSmall,
            vertical = SharedLedgerSpacing.Small,
        ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
    ) {
        CurrencyFlag(code)
        Text(
            code.uppercase(),
            style = SharedLedgerTextStyles.Label,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (enabled) {
            Icon(
                Icons.Rounded.KeyboardArrowDown,
                contentDescription = "展开币种选择",
                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
            )
        }
    }
}

@Composable
private fun Transition<Boolean>.fluidSize(capsule: Dp, panel: Dp, label: String) =
    animateDp(
        transitionSpec = { SharedLedgerMotion.Springs.FluidMorph },
        label = label,
    ) { if (it) panel else capsule }

private fun Dp.coerceBetween(first: Dp, second: Dp): Dp =
    coerceIn(minOf(first, second), maxOf(first, second))
