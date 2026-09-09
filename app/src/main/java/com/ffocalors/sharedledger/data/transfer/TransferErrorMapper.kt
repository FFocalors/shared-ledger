package com.ffocalors.sharedledger.data.transfer

import java.io.IOException
import java.net.SocketException
import java.net.UnknownHostException
import java.util.Locale

object TransferErrorMapper {
    fun toUserMessage(error: Throwable): String {
        if (error is TransferOperationException) return error.userMessage
        val sqlState = findSqlState(error)
        return when (sqlState) {
            "28000" -> "登录状态已失效，请重新登录"
            "42501" -> "你没有权限执行此操作，或尚未绑定参与人"
            "P0002" -> "活动或参与人不存在"
            "22023" -> "转账金额或参与人信息不符合规则"
            "23514" -> "转账金额不能超过当前债务"
            "40001", "40P01" -> "数据刚刚发生变化，请刷新债务后重试"
            "55000" -> "当前活动状态不允许转账"
            else -> if (isTransferNetworkFailure(error)) {
                "网络连接失败，请检查网络后重试"
            } else {
                "转账失败，请稍后重试"
            }
        }
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

    internal fun isTransferNetworkFailure(error: Throwable): Boolean {
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

class TransferOperationException(val userMessage: String, cause: Throwable? = null) : RuntimeException(userMessage, cause)
