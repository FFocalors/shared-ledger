package com.ffocalors.sharedledger.data.agent

import java.math.RoundingMode
import java.util.Locale

/** Which scripted timeline a submitted text triggers. Pure, so it can be unit tested. */
enum class DemoScript { OFFLINE, ERROR, SLOW, DRAFT, CLARIFY, ANSWER, DEFAULT }

/** What the confirm endpoint does for a demo draft, chosen from the draft's own text. */
enum class DemoConfirmScenario { EXECUTE, RECOVERING, UNAVAILABLE }

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
            text.contains("欠") || text.contains("多少") || text.contains("总共") || text.contains("花了") ||
                text.contains("活动") ->
                DemoScript.ANSWER
            else -> DemoScript.DEFAULT
        }
    }

    /**
     * The answer text for the ANSWER script, in the exact line shapes the real Agent renders, so demo mode
     * exercises the same ledger parsing as a live service.
     */
    fun answerText(text: String): String = when {
        text.contains("没有") -> "当前查询范围内没有符合条件的记录。"
        text.contains("部分") ->
            "以下是本次已验证的部分活动记录；查询或投影未完成，列表可能不完整：\n" +
                "- 周末露营（large；进行中；基准币种 CNY）"
        text.contains("活动") ->
            "已验证的活动：\n- 周末露营（large；进行中；基准币种 CNY）\n- 10.8火锅（normal；已归档；基准币种 CNY）"
        text.contains("花了") || text.contains("总共") ->
            "根据当前可信记录：\n消费记录：烧烤 — 750.00 CNY\n付款 我：750.00 CNY\n" +
                "分摊 小林：250.00 CNY\n分摊 阿杰：250.00 CNY\n分摊 我：250.00 CNY"
        else ->
            "根据当前可信记录：\n债务记录：小林 → 我，150.00 CNY\n债务记录：阿杰 → 我，224.5000 CNY"
    }

    /** 「不可用」 exercises the frozen 501; 「核对」 exercises the RECOVERING/unknown path. */
    fun confirmScenario(text: String): DemoConfirmScenario = when {
        text.contains("不可用") -> DemoConfirmScenario.UNAVAILABLE
        text.contains("核对") -> DemoConfirmScenario.RECOVERING
        else -> DemoConfirmScenario.EXECUTE
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
