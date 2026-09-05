package com.ffocalors.sharedledger.data.auth

import java.io.IOException
import kotlinx.coroutines.CancellationException

object AuthErrorMapper {
    fun toUserMessage(error: Throwable): String {
        if (error is CancellationException) throw error
        val message = error.message.orEmpty().lowercase()
        return when {
            message.contains("already registered") || message.contains("user already exists") ->
                "该邮箱已注册，请直接登录"
            message.contains("invalid login") || message.contains("invalid credentials") ||
                message.contains("email or password") -> "邮箱或密码错误"
            message.contains("email not confirmed") || message.contains("not confirmed") ->
                "邮箱尚未验证，请先完成邮箱验证"
            error is IOException || message.contains("timeout") || message.contains("network") ||
                message.contains("host") || message.contains("connection") -> "网络连接失败，请检查网络后重试"
            message.contains("session") || message.contains("refresh token") ->
                "登录状态已失效，请重新登录"
            message.contains("password") && message.contains("short") -> "密码长度不足"
            else -> "请求失败，请稍后重试"
        }
    }
}
