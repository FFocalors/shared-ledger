package com.ffocalors.sharedledger.data.expense

import com.ffocalors.sharedledger.data.common.ReadFailureKind
import java.io.IOException
import java.net.SocketException
import java.net.UnknownHostException
import java.util.Locale

object ExpenseErrorMapper {
    fun failureKind(error: Throwable): ReadFailureKind {
        if (error is ExpenseOperationException) return error.failureKind
        return when (findSqlState(error)) {
            "42501", "28000" -> ReadFailureKind.PermissionDenied
            "P0002", "PGRST116" -> ReadFailureKind.NotFound
            else -> if (isExpenseNetworkFailure(error)) ReadFailureKind.Transient else ReadFailureKind.Other
        }
    }

    fun toUserMessage(error: Throwable): String {
        if (error is ExpenseOperationException) return error.userMessage
        if (error.messageChainContains("settled") || error.messageChainContains("settlement")) {
            return "账单已发生结算，不能修改或删除其财务字段"
        }
        val sqlState = findSqlState(error)
        return when (sqlState) {
            "28000" -> "登录状态已失效，请重新登录"
            "42501" -> "你没有权限执行此操作，或已不是活动成员"
            "P0002" -> "账单不存在或已被删除"
            "22023", "23514" -> "输入内容不符合账单规则"
            "23505", "23503" -> "账单与参与人信息发生冲突，请刷新后重试"
            "55000" -> "当前活动状态不允许此操作"
            "40001" -> "数据刚刚发生变化，请刷新后重试"
            "54000" -> "附件数量已达到上限"
            else -> if (isExpenseNetworkFailure(error)) {
                "网络连接失败，请检查网络后重试"
            } else {
                "操作失败，请稍后重试"
            }
        }
    }

    private fun Throwable.messageChainContains(value: String): Boolean {
        var current: Throwable? = this
        while (current != null) {
            if (current.message.orEmpty().contains(value, ignoreCase = true)) return true
            current = current.cause
        }
        return false
    }

    private fun findSqlState(error: Throwable): String? {
        val pattern = Regex("(?i)(?:sqlstate|errcode|\\\"code\\\"|\\bcode)\\s*[=: ]+\\\"?([0-9A-Z]{5})")
        var current: Throwable? = error
        while (current != null) {
            pattern.find(current.message.orEmpty())?.groupValues?.getOrNull(1)?.let {
                return it.uppercase(Locale.US)
            }
            current = current.cause
        }
        return null
    }

    internal fun isExpenseNetworkFailure(error: Throwable): Boolean {
        var current: Throwable? = error
        while (current != null) {
            if (current is IOException || current is SocketException || current is UnknownHostException) return true
            val className = current::class.java.name
            if (className.startsWith("io.ktor.") &&
                (className.endsWith("ConnectTimeoutException") || className.endsWith("HttpRequestTimeoutException"))
            ) return true
            current = current.cause
        }
        return false
    }
}
