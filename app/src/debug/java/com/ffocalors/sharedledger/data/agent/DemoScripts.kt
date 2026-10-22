package com.ffocalors.sharedledger.data.agent

import java.math.RoundingMode
import java.util.Locale

/** Which scripted timeline a submitted text triggers. Pure, so it can be unit tested. */
enum class DemoScript { OFFLINE, ERROR, SLOW, DRAFT, CLARIFY, ANSWER, DEFAULT }

object DemoScripts {
    private val amountRegex = Regex("""\d+(?:\.\d+)?(?!\d|\.\d|\s*个?人)""")
    private val countRegex = Regex("""(\d+|[两二三四五六七八九十])\s*个?人""")
    private val fillers = listOf("记一笔", "记一下", "帮我", "昨天", "前天", "今天", "刚才", "我", "记", "付", "了")

    fun choose(text: String): DemoScript {
        val hasNumber = text.any { it.isDigit() }
        val hasBook = text.contains("记") || text.contains("付")
        return when {
            text.contains("断网") -> DemoScript.OFFLINE
            text.contains("出错") -> DemoScript.ERROR
            text.contains("慢") -> DemoScript.SLOW
            hasNumber && (hasBook || text.contains("平分") || text.contains("AA", ignoreCase = true)) ->
                DemoScript.DRAFT
            hasBook -> DemoScript.CLARIFY
            text.contains("欠") || text.contains("多少") || text.contains("总共") || text.contains("花了") ->
                DemoScript.ANSWER
            else -> DemoScript.DEFAULT
        }
    }

    /** First number in the text (ignoring head counts like "4个人"), formatted to 2 decimals. */
    fun parseAmount(text: String): String? =
        amountRegex.find(text)?.value?.toBigDecimalOrNull()?.setScale(2, RoundingMode.HALF_UP)
            ?.let { String.format(Locale.ROOT, "%.2f", it) }

    /** Number of people sharing; defaults to 2. */
    fun parseParticipantCount(text: String): Int {
        val raw = countRegex.find(text)?.groupValues?.get(1) ?: return 2
        val n = raw.toIntOrNull() ?: "?两二三四五六七八九十".indexOf(raw).let { if (it == 1) 2 else it }
        return if (n in 1..50) n else 2
    }

    /** Up to 6 characters right before the amount, minus filler words; fallback 「这笔支出」. */
    fun guessTitle(text: String): String {
        val end = amountRegex.find(text)?.range?.first ?: text.length
        var prefix = text.substring(0, end).filter { it.isLetter() }
        fillers.forEach { prefix = prefix.replace(it, "") }
        return prefix.takeLast(6).ifBlank { "这笔支出" }
    }
}
