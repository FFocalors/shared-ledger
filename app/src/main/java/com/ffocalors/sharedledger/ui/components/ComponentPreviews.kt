package com.ffocalors.sharedledger.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Payments
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import java.math.BigDecimal

private val PreviewParticipants = listOf(
    ParticipantUiModel("张三"),
    ParticipantUiModel("李四"),
    ParticipantUiModel("王五"),
    ParticipantUiModel("赵六"),
)

@Preview(name = "结算概览卡", showBackground = true, widthDp = 390)
@Composable
private fun SettlementSummaryCardPreview() = PreviewFrame {
    SettlementSummaryCard(
        title = "当前待结算",
        primaryAmount = BigDecimal("2480.0"),
        statistics = listOf(
            SettlementStatistic("总消费", "¥5,980.0"),
            SettlementStatistic("包含", "3 项活动"),
            SettlementStatistic("参与者", "6 人"),
        ),
    )
}

@Preview(name = "活动卡片", showBackground = true, widthDp = 390)
@Composable
private fun ActivityCardPreview() = PreviewFrame {
    ActivityCard(
        activity = ActivityCardUiModel(
            name = "日本旅行",
            kind = ActivityKind.Large,
            participantCount = 6,
            status = ActivityStatus.PendingSettlement,
            totalAmount = BigDecimal("1240.5"),
            updatedAt = "12:30",
            participants = PreviewParticipants,
        ),
        onClick = {},
    )
}

@Preview(name = "消费卡片", showBackground = true, widthDp = 390)
@Composable
private fun ExpenseCardPreview() = PreviewFrame {
    ExpenseCard(
        expense = ExpenseCardUiModel(
            name = "晚餐",
            amount = BigDecimal("560.0"),
            payerName = "张三",
            participantCount = 5,
            time = "今天 19:30",
            participants = PreviewParticipants,
        ),
    )
}

@Preview(name = "底部操作栏", showBackground = true, widthDp = 390)
@Composable
private fun BottomActionBarPreview() = PreviewFrame {
    SharedLedgerBottomActionBar(
        actions = listOf(
            BottomActionItem("转账", Icons.Rounded.SwapHoriz, {}),
            BottomActionItem("记一笔", Icons.Rounded.Add, {}),
            BottomActionItem("收款", Icons.Rounded.RequestQuote, {}),
        ),
    )
}

@Preview(name = "主按钮", showBackground = true, widthDp = 390)
@Composable
private fun PrimaryButtonPreview() = PreviewFrame {
    SharedLedgerPrimaryButton(
        text = "创建活动",
        onClick = {},
        icon = Icons.Rounded.Save,
    )
}

@Preview(name = "人员金额行", showBackground = true, widthDp = 390)
@Composable
private fun ParticipantAmountRowPreview() = PreviewFrame {
    ParticipantAmountRow(
        participant = ParticipantUiModel("张三"),
        amount = BigDecimal("200.0"),
        status = ParticipantAmountStatus.Pending,
    )
}

@Preview(name = "状态标签", showBackground = true, widthDp = 390)
@Composable
private fun StatusChipPreview() = PreviewFrame {
    Row(horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
        StatusChip(ActivityStatus.InProgress)
        StatusChip(ActivityStatus.PendingSettlement)
        StatusChip(ActivityStatus.Settled)
    }
}

@Preview(name = "风险提醒", showBackground = true, widthDp = 390)
@Composable
private fun WarningCardPreview() = PreviewFrame {
    WarningCard(
        title = "结算前请核对",
        text = "当前存在 1 条有争议的转账记录。",
    )
}

@Preview(name = "组件总览", showBackground = true, widthDp = 390, heightDp = 1500)
@Composable
private fun ComponentShowcasePreview() = PreviewFrame {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) {
        SharedLedgerTopBar(title = "SharedLedger", avatarName = "王五")
        SettlementSummaryCard(
            title = "当前待结算",
            primaryAmount = BigDecimal("320.0"),
            statistics = listOf(
                SettlementStatistic("总消费", "¥860.0"),
                SettlementStatistic("参与者", "5 人"),
            ),
        )
        SegmentedControl(
            options = listOf("AA 均摊", "手动分摊"),
            selectedIndex = 0,
            onSelected = {},
        )
        SharedLedgerTextField(
            value = "周末聚餐",
            onValueChange = {},
            modifier = Modifier.fillMaxWidth(),
            label = "活动名称",
            placeholder = "例如：毕业旅行",
        )
        ParticipantAmountRow(
            participant = ParticipantUiModel("李四"),
            amount = BigDecimal("120.0"),
            status = ParticipantAmountStatus.Paid,
        )
        ExpenseCard(
            expense = ExpenseCardUiModel(
                name = "打车",
                amount = BigDecimal("100.0"),
                payerName = "李四",
                participantCount = 3,
            ),
            icon = Icons.AutoMirrored.Rounded.ReceiptLong,
        )
        WarningCard(text = "金额尚未完全分配，请检查参与人金额。")
        SharedLedgerPrimaryButton(
            text = "保存",
            onClick = {},
            icon = Icons.Rounded.Save,
        )
        SharedLedgerSecondaryButton(
            text = "记录已支付",
            onClick = {},
            icon = Icons.Rounded.Payments,
        )
        SharedLedgerBottomActionBar(
            actions = listOf(
                BottomActionItem("转账", Icons.Rounded.SwapHoriz, {}),
                BottomActionItem("预存", Icons.Rounded.AccountBalanceWallet, {}),
                BottomActionItem("收款", Icons.Rounded.RequestQuote, {}),
            ),
        )
    }
}

@Composable
private fun PreviewFrame(content: @Composable () -> Unit) {
    SharedLedgerTheme {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.background)
                .padding(SharedLedgerSpacing.Large),
        ) {
            content()
        }
    }
}
