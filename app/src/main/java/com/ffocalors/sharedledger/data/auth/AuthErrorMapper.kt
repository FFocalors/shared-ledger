package com.ffocalors.sharedledger.data.auth

import java.io.IOException
import kotlinx.coroutines.CancellationException

object AuthErrorMapper {
    const val PASSWORD_RESET_SENT_MESSAGE = "如果该邮箱已注册，重置邮件已发送，请查收"

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
            message.contains("session") || message.contains("refresh token") ||
                (message.contains("jwt") && message.contains("expir")) ->
                "登录状态已失效，请重新登录"
            message.contains("password") && message.contains("short") -> "密码长度不足"
            else -> "请求失败，请稍后重试"
        }
    }

    fun toPasswordResetMessage(error: Throwable): String {
        if (error is CancellationException) throw error
        val message = error.message.orEmpty().lowercase()
        return when {
            error is IOException || message.contains("timeout") || message.contains("network") ||
                message.contains("host") || message.contains("connection") ->
                "网络连接失败，请检查网络后重试"
            // Unknown-user and malformed-address responses must not reveal account existence.
            message.contains("not found") || message.contains("user") ||
                message.contains("email") || message.contains("invalid") ->
                PASSWORD_RESET_SENT_MESSAGE
            else -> "请求失败，请稍后重试"
        }
    }

    fun toPasswordUpdateMessage(error: Throwable): String {
        if (error is CancellationException) throw error
        val message = error.message.orEmpty().lowercase()
        return when {
            error is IOException || message.contains("timeout") || message.contains("network") ||
                message.contains("host") || message.contains("connection") ->
                "网络连接失败，请检查网络后重试"
            message.contains("same password") || message.contains("different from the old") ||
                message.contains("new password should be different") ->
                "新密码不能与当前密码相同"
            message.contains("weak password") ||
                (message.contains("password") && (
                    message.contains("short") || message.contains("length") ||
                        message.contains("at least") || message.contains("character")
                    )) ->
                "密码强度不足，请使用至少 8 个字符并增加字符组合"
            message.contains("reauth") || message.contains("nonce") ||
                message.contains("recently signed in") ->
                "当前登录时间过久，请退出后重新登录再修改密码"
            message.contains("session") || message.contains("refresh token") ||
                (message.contains("jwt") && message.contains("expir")) ->
                "登录状态已失效，请重新登录"
            else -> "密码修改失败，请稍后重试"
        }
    }
}
