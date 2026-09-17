package com.ffocalors.sharedledger.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.ReceiptLong
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.DeleteForever
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.RequestQuote
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 图标语义统一映射：同一含义全 App 只用一个图标。
 * 新页面请从这里取图标，不要直接引用 Icons.*，避免同类含义图标混用。
 */
internal object SharedLedgerIcons {
    /** 资金记录 / 预存 */
    val FundRecords = Icons.Rounded.AccountBalanceWallet

    /** 结算 / 转账 */
    val Settlement = Icons.Rounded.SwapHoriz

    /** 收款 */
    val Receive = Icons.Rounded.RequestQuote

    /** 新增 / 记一笔 */
    val AddRecord = Icons.Rounded.Edit

    /** 子活动 / 账单的默认图标 */
    val DefaultRecord = Icons.AutoMirrored.Rounded.ReceiptLong

    /** 返回 */
    val Back = Icons.AutoMirrored.Rounded.ArrowBack

    /** 更多操作 */
    val More = Icons.Rounded.MoreVert

    /** 删除 */
    val Delete = Icons.Rounded.Delete

    /** 永久删除（销毁活动/账号等不可逆操作） */
    val DeleteForever = Icons.Rounded.DeleteForever
}
