package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.TransferDispute
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.math.BigDecimal
import java.util.concurrent.TimeoutException

internal class SupabaseFinancialRecordRepository(
    private val remote: FinancialRemoteDataSource,
) : FinancialRecordRepository {
    override suspend fun create(record: FundRecord): FinancialWriteResult<FundRecord> =
        FinancialWriteResult.failure("资金记录必须通过服务端业务操作创建")

    override suspend fun list(activityId: String, type: FundRecordType?): FinancialReadResult<List<FundRecord>> =
        read { remote.listRecords(activityId, type) }

    override suspend fun get(activityId: String, transferId: String): FinancialReadResult<FundRecord> =
        read { remote.getRecord(activityId, transferId) }

    override suspend fun void(activityId: String, transferId: String, reason: String): FinancialWriteResult<FundRecord> =
        write {
            if (reason.isBlank()) throw FinancialOperationException("作废必须填写原因")
            val record = remote.getRecord(activityId, transferId)
            remote.void(record, reason)
        }

    override suspend fun restore(activityId: String, transferId: String, reason: String): FinancialWriteResult<FundRecord> =
        write {
            if (reason.isBlank()) throw FinancialOperationException("恢复必须填写原因")
            val record = remote.getRecord(activityId, transferId)
            remote.restore(record, reason)
        }

    override suspend fun addDispute(
        activityId: String,
        transferId: String,
        participantId: String,
        note: String,
    ): FinancialWriteResult<TransferDispute> = write {
        if (note.isBlank()) throw FinancialOperationException("争议必须填写说明")
        remote.addDispute(activityId, transferId, participantId, note).dispute
    }

    override suspend fun resolveDispute(activityId: String, disputeId: String): FinancialWriteResult<TransferDispute> =
        write { remote.resolveDispute(activityId, disputeId).dispute }

    override suspend fun loadPrepaymentContext(activityId: String): FinancialReadResult<FinancialContext> =
        read { remote.loadContext(activityId) }

    override suspend fun currentParticipantId(activityId: String): FinancialReadResult<String?> =
        read { remote.currentParticipantId(activityId) }

    override suspend fun createPrepayment(input: PrepaymentInput): FinancialWriteResult<FundRecord> =
        write { remote.createPrepayment(input) }

    override suspend fun createPrepaymentReturn(input: PrepaymentInput): FinancialWriteResult<FundRecord> =
        write { remote.createPrepaymentReturn(input) }

    override suspend fun previewFinalSettlement(activityId: String): FinancialReadResult<List<FinalSettlementSuggestion>> =
        read { remote.previewFinalSettlement(activityId) }

    override suspend fun executeFinalSettlement(
        request: FinalSettlementSuggestion,
        occurredAt: String,
    ): FinancialWriteResult<FundRecord> = write { remote.executeFinalSettlement(request, occurredAt) }

    private suspend fun <T> read(block: suspend () -> T): FinancialReadResult<T> = try {
        FinancialReadResult.Success(block())
    } catch (error: Throwable) {
        FinancialReadResult.Failure(FinancialErrorMapper.toUserMessage(error))
    }

    private suspend fun <T> write(block: suspend () -> T): FinancialWriteResult<T> = try {
        FinancialWriteResult.success(block())
    } catch (error: Throwable) {
        mapFinancialWriteError(error)
    }
}

internal fun <T> mapFinancialWriteError(error: Throwable): FinancialWriteResult<T> = when (error) {
    is FinancialWriteCommittedException -> FinancialWriteResult.committedRefreshFailure(
        operationId = error.operationId,
        message = error.userMessage,
    )
    is FinancialWriteUnknownException -> FinancialWriteResult.unknown(
        operationId = error.operationId,
        message = error.userMessage,
    )
    else -> FinancialWriteResult.failure(FinancialErrorMapper.toUserMessage(error))
}

internal fun isFinancialNetworkFailure(error: Throwable): Boolean = generateSequence(error) { it.cause }
    .any { cause ->
        cause is IOException ||
            cause is ConnectException ||
            cause is SocketTimeoutException ||
            cause is UnknownHostException ||
            cause is TimeoutException ||
            cause.message.orEmpty().containsAny(
                "timeout",
                "timed out",
                "connection reset",
                "connection refused",
                "connection failed",
                "network is unreachable",
                "unable to resolve host",
                "unknown host",
            )
    }

private fun String.containsAny(vararg values: String): Boolean = values.any { contains(it, ignoreCase = true) }

object FinancialRecordRepositoryFactory {
    fun create(): FinancialRecordRepository = SupabaseClientProvider.createOrNull()
        ?.let { SupabaseFinancialRecordRepository(FinancialRemoteDataSource(it)) }
        ?: UnavailableFinancialRecordRepository()
}

private class UnavailableFinancialRecordRepository : FinancialRecordRepository {
    private fun <T> unavailable(): FinancialReadResult<T> = FinancialReadResult.Failure("尚未配置 Supabase，无法加载资金数据")
    private fun <T> unavailableWrite(): FinancialWriteResult<T> = FinancialWriteResult.failure("尚未配置 Supabase，无法执行资金操作")
    override suspend fun create(record: FundRecord) = unavailableWrite<FundRecord>()
    override suspend fun list(activityId: String, type: FundRecordType?) = unavailable<List<FundRecord>>()
    override suspend fun get(activityId: String, transferId: String) = unavailable<FundRecord>()
    override suspend fun void(activityId: String, transferId: String, reason: String) = unavailableWrite<FundRecord>()
    override suspend fun restore(activityId: String, transferId: String, reason: String) = unavailableWrite<FundRecord>()
    override suspend fun addDispute(activityId: String, transferId: String, participantId: String, note: String) = unavailableWrite<TransferDispute>()
    override suspend fun resolveDispute(activityId: String, disputeId: String) = unavailableWrite<TransferDispute>()
    override suspend fun loadPrepaymentContext(activityId: String) = unavailable<FinancialContext>()
    override suspend fun currentParticipantId(activityId: String) = unavailable<String?>()
    override suspend fun createPrepayment(input: PrepaymentInput) = unavailableWrite<FundRecord>()
    override suspend fun createPrepaymentReturn(input: PrepaymentInput) = unavailableWrite<FundRecord>()
    override suspend fun previewFinalSettlement(activityId: String) = unavailable<List<FinalSettlementSuggestion>>()
    override suspend fun executeFinalSettlement(request: FinalSettlementSuggestion, occurredAt: String) = unavailableWrite<FundRecord>()
}

object FinancialErrorMapper {
    fun toUserMessage(error: Throwable): String {
        if (error is FinancialOperationException) return error.userMessage
        val text = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }
        val code = Regex("(?i)(?:sqlstate|errcode|\\\"code\\\"|\\bcode)\\s*[=: ]+\\\"?([0-9A-Z]{5})").find(text)?.groupValues?.getOrNull(1)?.uppercase()
        return when (code) {
            "28000" -> "登录状态已失效，请重新登录"
            "42501" -> "你没有权限执行此操作，或尚未绑定参与人"
            "P0002" -> "活动或资金记录不存在"
            "22023", "22004" -> "资金操作参数不符合规则"
            "40001", "40P01" -> "当前资金方案已发生变化，请重新查看最新方案后重试。"
            "23514" -> when {
                text.contains("prepayment return exceeds", true) || text.contains("available balance", true) ->
                    "预存余额不足，无法恢复这笔返还记录，请刷新后查看最新状态。"
                text.contains("settlement exceeds", true) || text.contains("bilateral debt", true) ->
                    "当前债务已被后续还款消耗，无法恢复这笔记录，请刷新后查看最新状态。"
                text.contains("final settlement", true) && text.contains("path", true) ->
                    "最终结算路径已变化，无法恢复，请重新查看方案并创建新的最终结算。"
                text.contains("final settlement", true) && (text.contains("plan", true) || text.contains("matches", true)) ->
                    "最终结算方案已变化，无法恢复，请重新查看方案并创建新的最终结算。"
                text.contains("stale", true) || text.contains("plan", true) || text.contains("version", true) ->
                    "当前结算方案已发生变化，请重新查看最新方案。"
                else -> "金额或资金状态不符合规则"
            }
            "55000" -> "当前活动状态不允许修改资金记录"
            else -> if (text.contains("timeout", true) || text.contains("connect", true) || text.contains("network", true) || error is java.io.IOException) {
                "网络连接失败，请检查网络后重试"
            } else "资金操作失败，请稍后重试"
        }
    }
}
