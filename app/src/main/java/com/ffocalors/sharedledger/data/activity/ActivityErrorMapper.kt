package com.ffocalors.sharedledger.data.activity

object ActivityErrorMapper {
    fun toUserMessage(error: Throwable): String {
        if (error is ActivityOperationException) return error.userMessage
        val raw = error.message.orEmpty()
        return when {
            raw.contains("42501") || raw.contains("permission", ignoreCase = true) ||
                raw.contains("member", ignoreCase = true) -> "你没有权限执行此操作，或已不是活动成员"
            raw.contains("P0002") || raw.contains("not found", ignoreCase = true) -> "活动不存在或已被删除"
            raw.contains("23505") || raw.contains("already", ignoreCase = true) ||
                raw.contains("claim", ignoreCase = true) -> "该参与人已被认领，或你已加入此活动"
            raw.contains("22023") || raw.contains("23514") || raw.contains("invalid", ignoreCase = true) -> "输入内容不符合活动规则"
            raw.contains("55000") || raw.contains("archived", ignoreCase = true) -> "活动已归档，当前操作不可用"
            raw.contains("timeout", ignoreCase = true) || raw.contains("network", ignoreCase = true) ||
                raw.contains("connect", ignoreCase = true) -> "网络连接失败，请检查网络后重试"
            else -> "操作失败，请稍后重试"
        }
    }
}
