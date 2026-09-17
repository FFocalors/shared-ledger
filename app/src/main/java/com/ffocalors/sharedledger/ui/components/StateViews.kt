package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.Inbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles

@Composable
fun LoadingState(
    modifier: Modifier = Modifier,
    message: String = "正在加载…",
    isRefreshing: Boolean = false,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = SharedLedgerSpacing.XLarge),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(
                if (isRefreshing) SharedLedgerDimens.IconMedium else SharedLedgerDimens.IconLarge,
            ),
            strokeWidth = 2.dp,
        )
        Text(
            text = if (isRefreshing) "正在刷新…" else message,
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun EmptyState(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector = Icons.Rounded.Inbox,
    description: String? = null,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                horizontal = SharedLedgerDimens.PageHorizontalPadding,
                vertical = SharedLedgerSpacing.XLarge,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Surface(
            modifier = Modifier.size(SharedLedgerDimens.IconContainerLarge),
            shape = SharedLedgerRadius.Full,
            color = MaterialTheme.colorScheme.surfaceVariant,
            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            )
        }
        Text(
            text = title,
            style = SharedLedgerTextStyles.CardTitle,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        description?.let {
            Text(
                text = it,
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        if (actionLabel != null && onAction != null) {
            SharedLedgerButton(
                text = actionLabel,
                onClick = onAction,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Composable
fun ErrorState(
    message: String,
    modifier: Modifier = Modifier,
    onRetry: (() -> Unit)? = null,
    retryLabel: String = "重试",
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                horizontal = SharedLedgerDimens.PageHorizontalPadding,
                vertical = SharedLedgerSpacing.XLarge,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Surface(
            modifier = Modifier.size(SharedLedgerDimens.IconContainerLarge),
            shape = SharedLedgerRadius.Full,
            color = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer,
        ) {
            Icon(
                imageVector = Icons.Rounded.ErrorOutline,
                contentDescription = null,
                modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            )
        }
        Text(
            text = message,
            style = SharedLedgerTextStyles.BodySecondary,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        onRetry?.let {
            SharedLedgerButton(
                text = retryLabel,
                onClick = it,
                tone = SharedLedgerButtonTone.SoftPrimary,
            )
        }
    }
}

@Composable
fun ErrorBanner(
    message: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Large,
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Rounded.ErrorOutline,
                contentDescription = null,
                modifier = Modifier.size(SharedLedgerDimens.IconSmall),
            )
            Text(
                text = message,
                style = SharedLedgerTextStyles.BodySecondary,
            )
        }
    }
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    trailing: (@Composable RowScope.() -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            modifier = Modifier.weight(1f),
            style = SharedLedgerTextStyles.SectionTitle,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        trailing?.invoke(this)
    }
}
