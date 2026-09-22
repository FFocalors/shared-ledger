package com.ffocalors.sharedledger.data.financial

import android.content.Context
import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import com.ffocalors.sharedledger.data.common.ReadFailureKind
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.TransferDispute
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.math.BigDecimal
import java.util.concurrent.TimeoutException
import kotlinx.coroutines.CancellationException

internal class SupabaseFinancialRecordRepository(
    private val remote: FinancialRemoteDataSource,
    private val currentUserId: String = "",
    private val requestStore: FinancialRequestStore = InMemoryFinancialRequestStore(),
) : FinancialRecordRepository {
    override suspend fun create(record: FundRecord): FinancialWriteResult<FundRecord> =
        FinancialWriteResult.failure("资金记录必须通过服务端业务操作创建")

    override suspend fun list(activityId: String, type: FundRecordType?): FinancialReadResult<List<FundRecord>> =
        read { remote.listRecords(activityId, type) }

    override suspend fun listAll(activityId: String): FinancialReadResult<List<FundRecord>> =
        read { remote.listAllRecords(activityId) }

    override suspend fun get(activityId: String, transferId: String): FinancialReadResult<FundRecord> =
        read { remote.getRecord(activityId, transferId) }

    override suspend fun void(activityId: String, transferId: String, reason: String): FinancialWriteResult<FundRecord> =
        write {
            if (reason.isBlank()) throw FinancialOperationException("作废必须填写原因")
            val record = remote.getRecord(activityId, transferId)
            remote.void(record, reason)
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
        writeWithDurableRequest(
            operationKey = "prepayment:create",
            activityId = input.activityId,
            payload = input,
        ) { pending ->
            remote.createPrepayment(
                input.copy(requestId = pending.requestId, occurredAt = pending.persistedOccurredAt(input.occurredAt)),
            )
        }

    override suspend fun createPrepaymentReturn(input: PrepaymentInput): FinancialWriteResult<FundRecord> =
        writeWithDurableRequest(
            operationKey = "prepayment:return",
            activityId = input.activityId,
            payload = input,
        ) { pending ->
            remote.createPrepaymentReturn(
                input.copy(requestId = pending.requestId, occurredAt = pending.persistedOccurredAt(input.occurredAt)),
            )
        }

    override suspend fun previewFinalSettlement(activityId: String): FinancialReadResult<List<FinalSettlementSuggestion>> =
        read { remote.previewFinalSettlement(activityId) }

    override suspend fun previewFinalSettlement(
        activityId: String,
        mode: FinalSettlementMode,
    ): FinancialReadResult<List<FinalSettlementSuggestion>> =
        read { remote.previewFinalSettlement(activityId, mode) }

    override suspend fun previewPrepayment(input: PrepaymentInput): FinancialReadResult<PrepaymentPreview> =
        read { remote.previewPrepayment(input) }

    override suspend fun executeFinalSettlement(
        request: FinalSettlementSuggestion,
        occurredAt: String,
    ): FinancialWriteResult<FundRecord> = writeWithDurableRequest(
        operationKey = "final-settlement:execute:${request.mode.databaseValue}",
        activityId = request.activityId,
        payload = request to occurredAt,
    ) { pending ->
        remote.executeFinalSettlement(request.copy(requestId = pending.requestId), pending.persistedOccurredAt(occurredAt))
    }

    private suspend fun <P> writeWithDurableRequest(
        operationKey: String,
        activityId: String,
        payload: P,
        block: suspend (PendingFinancialRequest) -> FundRecord,
    ): FinancialWriteResult<FundRecord> {
        val payloadText = durablePayloadText(payload)
        val fingerprint = financialPayloadFingerprint(payloadText)
        val pending = runCatching {
            requestStore.read(currentUserId, activityId, operationKey)
                .asReversed()
                .firstOrNull { it.payloadFingerprint == fingerprint || it.matchesRetryPayload(payload) }
                ?: PendingFinancialRequest(
                    requestId = java.util.UUID.randomUUID().toString(),
                    activityId = activityId,
                    operationKey = operationKey,
                    payloadFingerprint = fingerprint,
                    payload = payloadText,
                    createdAtEpochMillis = System.currentTimeMillis(),
                ).also { requestStore.upsert(currentUserId, it) }
        }.getOrElse {
            return FinancialWriteResult.failure("无法保存资金操作重试凭据，请稍后重试")
        }
        return try {
            val result = write { block(pending) }
            if (result.isSuccess || result.isCommitted || !result.isUnknown) {
                runCatching { requestStore.remove(currentUserId, pending) }
            }
            if (result.isUnknown) result.copy(committedOperationId = pending.requestId) else result
        } catch (error: Throwable) {
            // write() currently maps all known failures to a result, but preserve the request on
            // an unexpected exception because the server may have committed it.
            throw error
        }
    }

    private fun durablePayloadText(value: Any?): String = when (value) {
        is PrepaymentInput -> listOf(
            value.activityId, value.ownerParticipantId, value.custodianParticipantId,
            value.amount.stripTrailingZeros().toPlainString(), value.currency.trim().uppercase(),
            value.occurredAt, value.onBehalfOfParticipantId.orEmpty(), value.sourceFinancialVersion?.toString().orEmpty(),
        ).joinToString("|")
        is Pair<*, *> -> "${durablePayloadText(value.first)}|${value.second}"
        is FinalSettlementSuggestion -> listOf(
            value.activityId, value.id, value.from.participantId, value.to.participantId,
            value.amount.stripTrailingZeros().toPlainString(), value.currency.trim().uppercase(),
            value.ordinaryAmount.stripTrailingZeros().toPlainString(), value.prepaymentReturnAmount.stripTrailingZeros().toPlainString(),
            value.sourceFinancialVersion.toString(), value.mode.databaseValue, value.planNo?.toString().orEmpty(),
            value.pathNo?.toString().orEmpty(), value.hopNo?.toString().orEmpty(), value.onBehalfOfParticipantId.orEmpty(),
        ).joinToString("|")
        else -> value.toString()
    }

    private fun PendingFinancialRequest.matchesRetryPayload(value: Any?): Boolean = when (value) {
        is PrepaymentInput -> {
            val parts = payload.split('|')
            parts.size >= 8 && parts[0] == value.activityId && parts[1] == value.ownerParticipantId &&
                parts[2] == value.custodianParticipantId && parts[3] == value.amount.stripTrailingZeros().toPlainString() &&
                parts[4] == value.currency.trim().uppercase() && parts[6] == value.onBehalfOfParticipantId.orEmpty() &&
                parts[7] == value.sourceFinancialVersion?.toString().orEmpty()
        }
        is Pair<*, *> -> payload.substringBeforeLast('|') == durablePayloadText(value.first)
        else -> false
    }

    private fun PendingFinancialRequest.persistedOccurredAt(fallback: String): String =
        payload.split('|').firstOrNull { it.contains('T') && it.contains(':') } ?: fallback

    private suspend fun <T> read(block: suspend () -> T): FinancialReadResult<T> = try {
        FinancialReadResult.Success(block())
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (error: Throwable) {
        FinancialReadResult.Failure(
            message = FinancialErrorMapper.toUserMessage(error),
            kind = FinancialErrorMapper.failureKind(error),
        )
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
    fun create(
        context: Context? = null,
        currentUserId: String = "",
    ): FinancialRecordRepository = SupabaseClientProvider.createOrNull()
        ?.let {
            SupabaseFinancialRecordRepository(
                remote = FinancialRemoteDataSource(it),
                currentUserId = currentUserId,
                requestStore = context?.let(::PreferencesFinancialRequestStore) ?: InMemoryFinancialRequestStore(),
            )
        }
        ?: UnavailableFinancialRecordRepository()
}

private class UnavailableFinancialRecordRepository : FinancialRecordRepository {
    private fun <T> unavailable(): FinancialReadResult<T> = FinancialReadResult.Failure("尚未配置 Supabase，无法加载资金数据")
    private fun <T> unavailableWrite(): FinancialWriteResult<T> = FinancialWriteResult.failure("尚未配置 Supabase，无法执行资金操作")
    override suspend fun create(record: FundRecord) = unavailableWrite<FundRecord>()
    override suspend fun list(activityId: String, type: FundRecordType?) = unavailable<List<FundRecord>>()
    override suspend fun get(activityId: String, transferId: String) = unavailable<FundRecord>()
    override suspend fun void(activityId: String, transferId: String, reason: String) = unavailableWrite<FundRecord>()
    override suspend fun addDispute(activityId: String, transferId: String, participantId: String, note: String) = unavailableWrite<TransferDispute>()
    override suspend fun resolveDispute(activityId: String, disputeId: String) = unavailableWrite<TransferDispute>()
    override suspend fun loadPrepaymentContext(activityId: String) = unavailable<FinancialContext>()
    override suspend fun currentParticipantId(activityId: String) = unavailable<String?>()
    override suspend fun createPrepayment(input: PrepaymentInput) = unavailableWrite<FundRecord>()
    override suspend fun createPrepaymentReturn(input: PrepaymentInput) = unavailableWrite<FundRecord>()
    override suspend fun previewFinalSettlement(activityId: String) = unavailable<List<FinalSettlementSuggestion>>()
    override suspend fun executeFinalSettlement(request: FinalSettlementSuggestion, occurredAt: String) = unavailableWrite<FundRecord>()
}

private val financialErrorCodePattern = Regex(
    """(?i)(?:sqlstate|errcode|"code"|\bcode)\s*[=: ]+"?([0-9A-Z]{5,8})(?![0-9A-Z])""",
)

private fun financialErrorCode(text: String): String? =
    financialErrorCodePattern.find(text)?.groupValues?.getOrNull(1)?.uppercase()

private fun isFinalSettlementContractError(text: String, code: String?): Boolean {
    val mentionsFinalSettlement = text.contains("final settlement", true) ||
        text.contains("final_settlement", true)
    return mentionsFinalSettlement && (
        code == "PGRST202" ||
            text.contains("schema cache", true) ||
            (text.contains("function", true) && text.contains("does not exist", true))
        )
}

private fun isFinalSettlementModeConstraint(text: String): Boolean =
    text.contains("settlement_mode", true) ||
        text.contains("final_settlement_paths_mode_valid", true) ||
        text.contains("invalid final settlement mode", true)

object FinancialErrorMapper {
    fun failureKind(error: Throwable): ReadFailureKind {
        val text = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }
        val code = financialErrorCode(text)
        return when (code) {
            "28000", "42501" -> ReadFailureKind.PermissionDenied
            "P0002", "PGRST116" -> ReadFailureKind.NotFound
            else -> if (isFinancialNetworkFailure(error)) ReadFailureKind.Transient else ReadFailureKind.Other
        }
    }

    fun toUserMessage(error: Throwable): String {
        if (error is FinancialOperationException) return error.userMessage
        val text = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }
        val code = financialErrorCode(text)
        if (isFinalSettlementContractError(text, code)) {
            return FINAL_SETTLEMENT_CONTRACT_UNAVAILABLE_MESSAGE
        }
        if (isFinalSettlementModeConstraint(text)) {
            return "当前服务端不支持所选结算模式，请更新服务端后重试。"
        }
        if (text.contains("final settlement", true) && text.contains("request_id", true) && text.contains("required", true)) {
            return "最终结算请求缺少服务端要求的 request_id，请更新客户端后重试。"
        }
        if (text.contains("financial_version", true) || text.contains("expected financial version", true)) {
            return "当前资金版本已变化，请刷新预存预览后重试。"
        }
        return when (code) {
            "28000" -> "登录状态已失效，请重新登录"
            "42501" -> when {
                text.contains("creator must be party or act on behalf", true) ||
                    text.contains("creator must be a transfer party or explicitly act on behalf", true) ->
                    "你不是这笔转账的一方；请选择未绑定参与人代记后重试"
                text.contains("creator may act only for unclaimed transfer party", true) ||
                    text.contains("creator may act only for an unclaimed participant", true) ->
                    "创建者只能为这笔转账中尚未绑定账号的参与人代记"
                text.contains("member must use claimed participant", true) ->
                    "仅这笔转账的付款方或收款方可以记录已转账"
                else -> "你没有权限执行此操作，或尚未绑定参与人"
            }
            "P0002" -> "活动或资金记录不存在"
            "22023", "22004" -> "资金操作参数不符合规则"
            "40001", "40P01" -> "当前资金方案已发生变化，请重新查看最新方案后重试。"
            "23514" -> when {
                text.contains("prepayment return exceeds", true) || text.contains("available balance", true) ->
                    "预存余额不足，无法执行这笔返还，请刷新后查看最新状态。"
                text.contains("settlement exceeds", true) || text.contains("bilateral debt", true) ->
                    "当前债务已被后续还款消耗，无法执行这笔资金操作，请刷新后查看最新状态。"
                text.contains("final settlement", true) && text.contains("path", true) ->
                    "最终结算路径已变化，无法执行，请重新查看方案并创建新的最终结算。"
                text.contains("final settlement", true) && (text.contains("plan", true) || text.contains("matches", true)) ->
                    "最终结算方案已变化，无法执行，请重新查看方案并创建新的最终结算。"
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

    /** Maps errors from the final-settlement RPC with operation-specific semantics. */
    internal fun toFinalSettlementUserMessage(error: Throwable): String {
        if (error is FinancialOperationException) return error.userMessage
        val text = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }
        val code = financialErrorCode(text)
        if (code == "PGRST202" || text.contains("schema cache", true) ||
            (text.contains("execute_final_settlement_v2", true) && text.contains("does not exist", true))
        ) {
            return FINAL_SETTLEMENT_CONTRACT_UNAVAILABLE_MESSAGE
        }
        if (isFinalSettlementModeConstraint(text)) {
            return "当前服务端不支持所选结算模式，请更新服务端后重试。"
        }
        if (text.contains("request_id", true) && text.contains("required", true)) {
            return "最终结算请求缺少服务端要求的 request_id，请更新客户端后重试。"
        }
        if (code == "40001" || code == "40P01" || text.contains("financial_version mismatch", true)) {
            return "当前结算方案已发生变化，请重新查看最新方案后重试。"
        }
        return toUserMessage(error)
    }
}
