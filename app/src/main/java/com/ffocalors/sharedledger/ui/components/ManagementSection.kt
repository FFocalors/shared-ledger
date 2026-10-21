package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import com.ffocalors.sharedledger.ui.theme.AppSurface
import com.ffocalors.sharedledger.ui.theme.AppSurfaceVariant
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles

/** 分组卡片的标题行（图标 + 标题），供管理页各分组复用。 */
@Composable
fun ManagementCardHeader(
    icon: ImageVector,
    title: String,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(SharedLedgerDimens.IconMedium),
        )
        Text(
            text = title,
            style = SharedLedgerTextStyles.CardTitle,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics { heading() },
        )
    }
}

/** 分组内行间的细分割线。 */
@Composable
fun ManagementDivider(color: Color = AppSurfaceVariant.copy(alpha = 0.55f)) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(SharedLedgerDimens.OutlineWidth)
            .background(color),
    )
}

/**
 * 主卡片（tier A）：带阴影、较大圆角与更宽松的内边距，用于页面里唯一的「主角」操作卡，
 * 例如参与人管理与基本信息。其余信息分组请使用 [ManagementGroup] 扁平化处理。
 */
@Composable
fun ManagementCard(
    modifier: Modifier = Modifier,
    contentSpacing: Dp = SharedLedgerSpacing.Medium,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        color = AppSurface,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, AppSurfaceVariant),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(contentSpacing),
            content = content,
        )
    }
}

/**
 * 扁平分组（tier B）：无阴影、较小圆角与更紧凑的内边距，让信息性分组退到背景层，
 * 不再与主卡片争夺视觉层级。
 */
@Composable
fun ManagementGroup(
    modifier: Modifier = Modifier,
    contentSpacing: Dp = SharedLedgerSpacing.Medium,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        color = AppSurface,
        border = BorderStroke(SharedLedgerDimens.OutlineWidth, AppSurfaceVariant.copy(alpha = 0.6f)),
        shadowElevation = SharedLedgerElevation.Flat,
    ) {
        Column(
            modifier = Modifier.padding(SharedLedgerSpacing.Medium),
            verticalArrangement = Arrangement.spacedBy(contentSpacing),
            content = content,
        )
    }
}
