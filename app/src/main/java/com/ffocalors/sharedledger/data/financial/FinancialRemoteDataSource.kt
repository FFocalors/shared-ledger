package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import io.github.jan.supabase.postgrest.exception.PostgrestRestException
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import java.math.BigDecimal
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

internal class FinancialRemoteDataSource(private val client: SupabaseClient) {
    private suspend fun currentUserId(): String = client.auth.currentSessionOrNull()?.user?.id
        ?: throw FinancialOperationException("登录状态已失效，请重新登录")

    suspend fun listRecords(activityId: String, type: FundRecordType? = null): List<FundRecord> = coroutineScope {
        // There are only three fixed branches here. Each branch owns its dependent reads, so a
        // full timeline no longer waits for transfers before starting the two projections.
        val transferRecords = async {
            if (type == FundRecordType.AUTO_PREPAYMENT_USAGE || type == FundRecordType.REFUND) {
                emptyList()
            } else {
                val transfers = client.from("transfers").select {
                    filter {
                        eq("activity_id", activityId)
                        type?.let { eq("type", it.databaseValue) }
                    }
                }.decodeList<FinancialTransferRowDto>()
                enrich(activityId, transfers)
            }
        }
        val usageRecords = async {
            if (type == null || type == FundRecordType.AUTO_PREPAYMENT_USAGE) {
                enrichPrepaymentUsages(activityId)
            } else {
                emptyList()
            }
        }
        val refundRecords = async {
            if (type == null || type == FundRecordType.REFUND) {
                enrichRefunds(activityId)
            } else {
                emptyList()
            }
        }
        (transferRecords.await() + usageRecords.await() + refundRecords.await())
            .sortedByDescending { it.occurredAt }
    }

    /** Fetches one complete, sorted snapshot for a caller that will filter it locally/cache it. */
    suspend fun listAllRecords(activityId: String): List<FundRecord> = listRecords(activityId)

    suspend fun getRecord(activityId: String, transferId: String): FundRecord {
        val transfer = client.from("transfers").select {
            filter {
                eq("activity_id", activityId)
                eq("id", transferId)
            }
        }.decodeList<FinancialTransferRowDto>().firstOrNull()
            ?: throw FinancialOperationException("未找到资金记录")
        return enrich(activityId, listOf(transfer)).first()
    }

    suspend fun currentParticipantId(activityId: String): String? {
        val userId = currentUserId()
        return client.from("participant_claims").select {
            filter { eq("activity_id", activityId); eq("user_id", userId) }
        }.decodeList<FinancialClaimRowDto>().firstOrNull()?.participantId
    }

    suspend fun loadContext(activityId: String): FinancialContext = coroutineScope {
        val userId = currentUserId()
        val participantsRequest = async {
            client.from("participants").select {
                filter { eq("activity_id", activityId); eq("is_deleted", false) }
            }.decodeList<FinancialParticipantRowDto>().map { it.toParticipant() }
        }
        val currencyRequest = async {
            client.from("activities").select {
                filter { eq("id", activityId) }
            }.decodeSingle<FinancialActivityRowDto>()
        }
        val claimsRequest = async {
            client.from("participant_claims").select {
                filter { eq("activity_id", activityId) }
            }.decodeList<FinancialClaimRowDto>()
        }
        val participants = participantsRequest.await()
        val currency = currencyRequest.await()
        val claims = claimsRequest.await()
        val profiles = loadClaimedProfiles(claims)
        val participantsWithAvatars = participants.map { participant ->
            val claim = claims.firstOrNull { it.participantId == participant.participantId }
            participant.copy(
                claimedUserId = claim?.userId,
                avatarStyle = claim?.userId?.let { profiles[it]?.avatarStyle },
            )
        }
        val currentParticipantId = claims.firstOrNull { it.userId == userId }?.participantId
        val claimedParticipantIds = claims.map { it.participantId }.toSet()
        val canActOnBehalf = currency.createdBy == userId
        val accountsRequest = async {
            client.from("prepayment_accounts").select {
                filter { eq("activity_id", activityId) }
            }.decodeList<FinancialAccountRowDto>()
        }
        val usagesRequest = async {
            client.from("prepayment_usages").select {
                filter { eq("activity_id", activityId) }
            }.decodeList<FinancialPrepaymentUsageRowDto>()
        }
        val accounts = accountsRequest.await().mapNotNull { row ->
            val owner = participantsWithAvatars.firstOrNull { it.participantId == row.ownerParticipantId }
            val custodian = participantsWithAvatars.firstOrNull { it.participantId == row.custodianParticipantId }
            if (owner == null || custodian == null) null else PrepaymentAccount(
                accountId = row.id,
                owner = owner,
                custodian = custodian,
                balance = row.balance.toFinancialBigDecimal(),
                usedAmount = BigDecimal.ZERO,
                currency = (row.currencyCode ?: row.currency ?: currency.baseCurrency).trim().uppercase(),
                baseBalance = row.baseBalance?.toFinancialBigDecimal(),
            )
        }
        val usagesByAccount = usagesRequest.await().let(::aggregatePrepaymentUsageAmounts)
        val accountsWithUsage = accounts.map { account ->
            account.copy(usedAmount = usagesByAccount[account.accountId] ?: BigDecimal.ZERO)
        }
        val supportedCurrencies = if (currency.multiCurrencyEnabled) {
            loadSupportedCurrencies()
        } else emptyList()
        val normalizedBaseCurrency = currency.baseCurrency.trim().uppercase()
        FinancialContext(
            activityId = activityId,
            currency = normalizedBaseCurrency,
            participants = participantsWithAvatars,
            currentParticipantId = currentParticipantId,
            accounts = accountsWithUsage,
            canActOnBehalf = canActOnBehalf,
            unclaimedParticipants = participantsWithAvatars.filterNot { it.participantId in claimedParticipantIds },
            baseCurrency = normalizedBaseCurrency,
            multiCurrencyEnabled = currency.multiCurrencyEnabled,
            supportedCurrencies = (listOf(normalizedBaseCurrency) + supportedCurrencies + accountsWithUsage.map { it.currency })
                .map { it.trim().uppercase() }
                .filter { it.length == 3 }
                .distinct(),
            financialVersion = currency.financialVersion,
        )
    }

    suspend fun previewFinalSettlement(activityId: String): List<FinalSettlementSuggestion> =
        previewFinalSettlement(activityId, FinalSettlementMode.BASE_UNIFIED)

    suspend fun previewFinalSettlement(
        activityId: String,
        mode: FinalSettlementMode,
    ): List<FinalSettlementSuggestion> = coroutineScope {
        val rowsRequest = async {
            try {
                client.postgrest.rpc("preview_final_settlement_v2", buildJsonObject {
                    put("p_activity_id", activityId)
                    put("p_mode", mode.databaseValue)
                }).decodeList<FinancialPreviewRowDto>()
            } catch (error: Throwable) {
                if (mode != FinalSettlementMode.BASE_UNIFIED || !isMissingFinancialRpc(error)) throw error
                client.postgrest.rpc("preview_activity_settlement", buildJsonObject {
                    put("activity_id", activityId)
                }).decodeList<FinancialPreviewRowDto>()
            }
        }
        val participantNamesRequest = async {
            client.from("participants").select {
                filter { eq("activity_id", activityId); eq("is_deleted", false) }
            }.decodeList<FinancialParticipantRowDto>().let { rows -> enrichParticipants(activityId, rows) }
        }
        val rows = rowsRequest.await()
        val participantNames = participantNamesRequest.await()
        rows.mapNotNull { row ->
            val from = participantNames[row.fromParticipantId] ?: return@mapNotNull null
            val to = participantNames[row.toParticipantId] ?: return@mapNotNull null
            val amount = (row.settlementAmount ?: row.amount ?: row.originalAmount ?: row.baseAmount)
                .toFinancialBigDecimal()
            if (amount <= BigDecimal.ZERO) return@mapNotNull null
            val currency = (row.currencyCode ?: row.currency).trim().uppercase()
            FinalSettlementSuggestion(
                id = "${row.fromParticipantId}-${row.toParticipantId}-${currency}-${amount.toPlainString()}-${row.sourceFinancialVersion}-${row.planNo ?: ""}-${row.pathNo ?: ""}",
                activityId = row.activityId,
                from = from,
                to = to,
                amount = amount,
                ordinaryAmount = row.ordinaryAmount.toFinancialBigDecimal(),
                prepaymentReturnAmount = row.prepaymentReturnAmount.toFinancialBigDecimal(),
                currency = currency,
                sourceFinancialVersion = row.sourceFinancialVersion,
                isPrepaymentReturn = row.isPrepaymentReturn,
                mode = FinalSettlementMode.fromDatabaseValueOrNull(row.mode ?: row.settlementMode ?: row.finalMode) ?: mode,
                baseAmount = row.baseAmount?.toFinancialBigDecimal() ?: amount,
                originalAmount = row.originalAmount?.toFinancialBigDecimal() ?: amount,
                planNo = row.planNo,
                pathNo = row.pathNo,
                hopNo = row.hopNo,
                pathCurrency = row.pathCurrency?.trim()?.uppercase(),
            )
        }
    }

    suspend fun createPrepayment(input: PrepaymentInput): FundRecord {
        val response = executeWriteRpc(input.requestId) {
            createPrepaymentRpc(
                v2Name = "create_prepayment_v2",
                legacyName = "create_prepayment",
                input = input,
            )
        }
        return loadCommittedRecord(input.activityId, response.transferId.ifBlank { findTransferIdByRequest(input.activityId, input.requestId) })
    }

    suspend fun createPrepaymentReturn(input: PrepaymentInput): FundRecord {
        val response = executeWriteRpc(input.requestId) {
            createPrepaymentRpc(
                v2Name = "create_prepayment_return_v2",
                legacyName = "create_prepayment_return",
                input = input,
            )
        }
        return loadCommittedRecord(input.activityId, response.transferId.ifBlank { findTransferIdByRequest(input.activityId, input.requestId) })
    }

    suspend fun previewPrepayment(input: PrepaymentInput): PrepaymentPreview {
        val response = try {
            client.postgrest.rpc("preview_prepayment", buildJsonObject {
                put("activity_id", input.activityId)
                put("owner_participant_id", input.ownerParticipantId)
                put("custodian_participant_id", input.custodianParticipantId)
                put("amount", input.amount.toPlainString())
                put("currency", input.currency.trim().uppercase())
            }).decodeSingle<FinancialPrepaymentPreviewRpcDto>()
        } catch (error: Throwable) {
            // Some PostgREST deployments expose the SQL argument names with p_ prefixes.
            // This is a read-only compatibility retry; writes never use this ambiguity path.
            if (!isMissingFinancialRpc(error)) throw error
            client.postgrest.rpc("preview_prepayment", buildJsonObject {
                put("p_activity_id", input.activityId)
                put("p_owner_participant_id", input.ownerParticipantId)
                put("p_custodian_participant_id", input.custodianParticipantId)
                put("p_amount", input.amount.toPlainString())
                put("p_currency", input.currency.trim().uppercase())
            }).decodeSingle<FinancialPrepaymentPreviewRpcDto>()
        }
        return PrepaymentPreview(
            activityId = input.activityId,
            ownerParticipantId = input.ownerParticipantId,
            custodianParticipantId = input.custodianParticipantId,
            currency = (response.currencyCode ?: response.currency ?: input.currency).trim().uppercase(),
            requestedAmount = (response.amount ?: response.requestedAmount)?.toFinancialBigDecimal() ?: input.amount,
            settlementAmount = response.settlementAmount.toFinancialBigDecimal(),
            newPrepaymentBalance = (response.newBalance ?: response.newPrepaymentBalance).toFinancialBigDecimal(),
            financialVersion = response.financialVersion,
            requestId = response.requestId ?: input.requestId,
        )
    }

    private suspend fun createPrepaymentRpc(
        v2Name: String,
        legacyName: String,
        input: PrepaymentInput,
    ): FinancialPrepaymentRpcDto {
        val payload = buildJsonObject {
            put("activity_id", input.activityId)
            put("owner_participant_id", input.ownerParticipantId)
            put("custodian_participant_id", input.custodianParticipantId)
            put("amount", input.amount.toPlainString())
            put("currency", input.currency.trim().uppercase())
            put("occurred_at", input.occurredAt)
            input.onBehalfOfParticipantId?.let { put("on_behalf_of_participant_id", it) } ?: put("on_behalf_of_participant_id", JsonNull)
            input.requestId?.let { put("request_id", it) }
            input.sourceFinancialVersion?.let { put("expected_financial_version", it) }
        }
        return try {
            client.postgrest.rpc(v2Name, payload).decodeSingle<FinancialPrepaymentRpcDto>()
        } catch (error: Throwable) {
            // The old RPC only understands base-currency arguments. A foreign-currency request
            // must never be silently re-written as base currency.
            if (!isMissingFinancialRpc(error)) throw error
            val baseCurrency = activityBaseCurrency(input.activityId)
            if (input.currency.trim().uppercase() != baseCurrency) {
                throw FinancialOperationException("当前服务端尚未部署 ${input.currency.trim().uppercase()} 预存，请先更新服务端")
            }
            val legacyPayload = buildJsonObject {
                put("activity_id", input.activityId)
                put("owner_participant_id", input.ownerParticipantId)
                put("custodian_participant_id", input.custodianParticipantId)
                put("amount", input.amount.toPlainString())
                put("occurred_at", input.occurredAt)
                input.onBehalfOfParticipantId?.let { put("on_behalf_of_participant_id", it) } ?: put("on_behalf_of_participant_id", JsonNull)
            }
            client.postgrest.rpc(legacyName, legacyPayload).decodeSingle<FinancialPrepaymentRpcDto>()
        }
    }

    suspend fun void(record: FundRecord, reason: String): FundRecord {
        if (record.isReadOnly) throw FinancialOperationException("只读资金记录不能作废")
        val rpc = if (record.type == FundRecordType.SETTLEMENT) "void_settlement_transfer" else "void_prepayment_transfer"
        val response = executeWriteRpc(record.transferId) {
            client.postgrest.rpc(rpc, buildJsonObject {
                put("transfer_id", record.transferId)
                put("void_reason", reason.trim())
            }).decodeSingle<FinancialVoidRpcDto>()
        }
        return loadCommittedRecord(record.activityId, response.transferId)
    }

    suspend fun addDispute(activityId: String, transferId: String, participantId: String, note: String): TransferDisputeResult {
        val response = executeWriteRpc(transferId) {
            client.postgrest.rpc("add_transfer_dispute", buildJsonObject {
                put("transfer_id", transferId)
                put("participant_id", participantId)
                put("note", note.trim())
            }).decodeSingle<FinancialDisputeRpcDto>()
        }
        val record = loadCommittedRecord(activityId, transferId)
        val dispute = record.disputes.firstOrNull { it.disputeId == response.disputeId }
            ?: throw FinancialWriteCommittedException(
                operationId = response.disputeId,
                userMessage = "争议已提交，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交",
            )
        return TransferDisputeResult(dispute)
    }

    suspend fun resolveDispute(activityId: String, disputeId: String): TransferDisputeResult {
        executeWriteRpc(disputeId) {
            client.postgrest.rpc("remove_transfer_dispute", buildJsonObject {
                put("dispute_id", disputeId)
            }).decodeSingle<Boolean>()
        }
        val record = try {
            listRecords(activityId).firstOrNull { it.disputes.any { dispute -> dispute.disputeId == disputeId } }
        } catch (error: Throwable) {
            throw FinancialWriteCommittedException(
                operationId = disputeId,
                userMessage = "争议已更新，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交",
                cause = error,
            )
        } ?: throw FinancialWriteCommittedException(
            operationId = disputeId,
            userMessage = "争议已更新，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交",
        )
        return TransferDisputeResult(record.disputes.first { it.disputeId == disputeId })
    }

    suspend fun executeFinalSettlement(request: FinalSettlementSuggestion, occurredAt: String): FundRecord {
        val response = executeWriteRpc(request.requestId) {
            val payload = buildJsonObject {
                put("activity_id", request.activityId)
                put("from_participant_id", request.from.participantId)
                put("to_participant_id", request.to.participantId)
                put("amount", request.amount.toPlainString())
                put("currency", request.currency.trim().uppercase())
                put("occurred_at", occurredAt)
                put("mode", request.mode.databaseValue)
                put("expected_financial_version", request.sourceFinancialVersion)
                request.requestId?.let { put("request_id", it) }
                request.onBehalfOfParticipantId?.let { put("on_behalf_of_participant_id", it) } ?: put("on_behalf_of_participant_id", JsonNull)
            }
            try {
                client.postgrest.rpc("execute_final_settlement_v2", payload).decodeSingle<FinancialTransferRpcDto>()
            } catch (error: Throwable) {
                if (!isMissingFinancialRpc(error) || request.mode != FinalSettlementMode.BASE_UNIFIED) throw error
                val baseCurrency = activityBaseCurrency(request.activityId)
                if (request.currency.trim().uppercase() != baseCurrency) {
                    throw FinancialOperationException("旧版最终结算仅支持活动基础币种 $baseCurrency")
                }
                val legacyPayload = buildJsonObject {
                    put("activity_id", request.activityId)
                    put("from_participant_id", request.from.participantId)
                    put("to_participant_id", request.to.participantId)
                    put("amount", request.amount.toPlainString())
                    put("occurred_at", occurredAt)
                    request.onBehalfOfParticipantId?.let { put("on_behalf_of_participant_id", it) } ?: put("on_behalf_of_participant_id", JsonNull)
                }
                client.postgrest.rpc("execute_final_settlement_item", legacyPayload).decodeSingle()
            }
        }
        return loadCommittedRecord(request.activityId, response.transferId.ifBlank { findTransferIdByRequest(request.activityId, request.requestId) })
    }

    private suspend fun <T> executeWriteRpc(
        operationId: String? = null,
        block: suspend () -> T,
    ): T = try {
        block()
    } catch (error: Throwable) {
        if (isFinancialNetworkFailure(error)) {
            throw FinancialWriteUnknownException(
                operationId = operationId,
                userMessage = "资金操作结果未知，请先查看或刷新资金记录，勿重复提交",
                cause = error,
            )
        }
        throw error
    }

    private suspend fun loadCommittedRecord(activityId: String, transferId: String): FundRecord = try {
        getRecord(activityId, transferId)
    } catch (error: Throwable) {
        throw FinancialWriteCommittedException(
            operationId = transferId,
            userMessage = "资金操作已成功，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交",
            cause = error,
        )
    }

    private suspend fun enrich(activityId: String, transfers: List<FinancialTransferRowDto>): List<FundRecord> = coroutineScope {
        if (transfers.isEmpty()) return@coroutineScope emptyList()
        val transferIds = transfers.map { it.id }
        // These are four fixed, independent reads. Do not turn this into one async job per
        // transfer: PostgREST already supports the bounded `isIn` queries above.
        val participantsRequest = async {
            client.from("participants").select {
                filter { eq("activity_id", activityId); eq("is_deleted", false) }
            }.decodeList<FinancialParticipantRowDto>().let { rows -> enrichParticipants(activityId, rows) }
        }
        val componentsRequest = async {
            client.from("transfer_components").select {
                filter { eq("activity_id", activityId); isIn("transfer_id", transferIds) }
            }.decodeList<FinancialComponentRowDto>().groupBy { it.transferId }
        }
        val disputesRequest = async {
            client.from("transfer_disputes").select {
                filter { eq("activity_id", activityId); isIn("transfer_id", transferIds) }
            }.decodeList<FinancialDisputeRowDto>().groupBy { it.transferId }
        }
        val pathsRequest = async {
            client.from("final_settlement_paths").select {
                filter { eq("activity_id", activityId); isIn("transfer_id", transferIds) }
            }.decodeList<FinancialPathRowDto>().groupBy { it.transferId }
        }
        val participants = participantsRequest.await()
        val components = componentsRequest.await()
        val disputes = disputesRequest.await()
        val paths = pathsRequest.await()
        val userIds = buildSet {
            transfers.forEach { add(it.recordedBy); it.voidedBy?.let(::add) }
            disputes.values.flatten().forEach { add(it.disputedBy); it.resolvedBy?.let(::add) }
        }
        val profiles = if (userIds.isEmpty()) emptyMap() else client.from("profiles").select {
            filter { isIn("id", userIds.toList()) }
        }.decodeList<FinancialProfileRowDto>().associate { it.id to it.toRecorder() }
        transfers.map {
            mapFinancialRecord(it, participants, profiles, components[it.id].orEmpty(), disputes[it.id].orEmpty(), paths[it.id].orEmpty())
        }.sortedByDescending { it.occurredAt }
    }

    private suspend fun enrichPrepaymentUsages(activityId: String): List<FundRecord> = coroutineScope {
        // Keep the existing dependency/early-return boundary: an activity without accounts must
        // not trigger unrelated projection reads (or surface a new error from one of them).
        val accounts = client.from("prepayment_accounts").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialAccountRowDto>().associateBy { it.id }
        if (accounts.isEmpty()) return@coroutineScope emptyList()
        val usages = client.from("prepayment_usages").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialPrepaymentUsageRowDto>()
        if (usages.isEmpty()) return@coroutineScope emptyList()
        val debtIds = usages.mapNotNull { it.expenseDebtId }.distinct()
        if (debtIds.isEmpty()) return@coroutineScope emptyList()
        val debtsRequest = async {
            client.from("expense_debts").select {
                filter { isIn("id", debtIds) }
            }.decodeList<FinancialExpenseDebtRowDto>().associateBy { it.id }
        }
        val participantsRequest = async {
            client.from("participants").select {
                filter { eq("activity_id", activityId); eq("is_deleted", false) }
            }.decodeList<FinancialParticipantRowDto>().let { rows -> enrichParticipants(activityId, rows) }
        }
        val currencyRequest = async {
            client.from("activities").select {
                filter { eq("id", activityId) }
            }.decodeSingle<FinancialActivityRowDto>()
        }
        val debts = debtsRequest.await()
        val expenseIds = debts.values.map { it.expenseId }.distinct()
        if (expenseIds.isEmpty()) return@coroutineScope emptyList()
        val expensesRequest = async {
            client.from("expenses").select {
                filter { isIn("id", expenseIds) }
            }.decodeList<FinancialExpenseTimelineRowDto>().associateBy { it.id }
        }
        val expenses = expensesRequest.await()
        val participants = participantsRequest.await()
        val activity = currencyRequest.await()
        usages.mapNotNull { usage ->
            val account = accounts[usage.accountId] ?: return@mapNotNull null
            val debt = usage.expenseDebtId?.let(debts::get) ?: return@mapNotNull null
            val expense = expenses[debt.expenseId] ?: return@mapNotNull null
            mapPrepaymentUsageRecord(
                usage,
                account,
                debt,
                expense,
                participants,
                usage.currencyCode ?: account.currency?.ifBlank { activity.baseCurrency } ?: activity.baseCurrency,
            )
        }
    }

    private suspend fun enrichRefunds(activityId: String): List<FundRecord> = coroutineScope {
        val unitIds = client.from("ledger_units").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<com.ffocalors.sharedledger.data.expense.ExpenseLedgerUnitRowDto>().map { it.id }
        if (unitIds.isEmpty()) return@coroutineScope emptyList()
        val refunds = client.from("expenses").select {
            filter {
                isIn("ledger_unit_id", unitIds)
                lt("original_amount", 0)
            }
        }.decodeList<FinancialRefundExpenseRowDto>()
        if (refunds.isEmpty()) return@coroutineScope emptyList()
        val refundIds = refunds.map { it.id }
        val originalIds = refunds.mapNotNull { it.originalExpenseId }.distinct()
        val userIds = refunds.flatMap { listOfNotNull(it.createdBy, it.deletedBy) }.distinct()
        val paymentsRequest = async {
            client.from("payments").select {
                filter { isIn("expense_id", refundIds) }
            }.decodeList<FinancialExpensePartyRowDto>().groupBy { it.expenseId }
        }
        val originalTitlesRequest = async {
            if (originalIds.isEmpty()) emptyMap() else client.from("expenses").select {
                filter { isIn("id", originalIds) }
            }.decodeList<FinancialExpenseTimelineRowDto>().associate { it.id to it.title }
        }
        val participantsRequest = async {
            client.from("participants").select {
                filter { eq("activity_id", activityId) }
            }.decodeList<FinancialParticipantRowDto>().let { rows -> enrichParticipants(activityId, rows) }
        }
        val profilesRequest = async {
            if (userIds.isEmpty()) emptyMap() else client.from("profiles").select {
                filter { isIn("id", userIds) }
            }.decodeList<FinancialProfileRowDto>().associate { it.id to it.toRecorder() }
        }
        val payments = paymentsRequest.await()
        val originalTitles = originalTitlesRequest.await()
        val participants = participantsRequest.await()
        val profiles = profilesRequest.await()
        refunds.map { refund ->
            mapRefundRecord(
                activityId = activityId,
                expense = refund,
                payments = payments[refund.id].orEmpty(),
                participants = participants,
                profiles = profiles,
                originalExpenseTitle = refund.originalExpenseId?.let(originalTitles::get),
            )
        }
    }

    private suspend fun activityBaseCurrency(activityId: String): String =
        client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<FinancialActivityRowDto>().baseCurrency.trim().uppercase()

    private suspend fun findTransferIdByRequest(activityId: String, requestId: String?): String {
        if (requestId.isNullOrBlank()) throw FinancialOperationException("资金操作已提交，但服务端未返回记录编号，请刷新资金记录确认")
        return client.from("transfers").select {
            filter {
                eq("activity_id", activityId)
                eq("request_id", requestId)
            }
        }.decodeList<FinancialTransferRowDto>().firstOrNull()?.id
            ?: throw FinancialOperationException("资金操作已提交，但最新记录暂时无法刷新，请稍后刷新确认")
    }

    private suspend fun loadSupportedCurrencies(): List<String> = runCatching {
        client.postgrest.rpc("list_supported_exchange_currencies")
            .decodeList<FinancialSupportedCurrencyRowDto>()
            .map { it.currencyCode.trim().uppercase() }
            .filter { it.length == 3 }
    }.getOrDefault(emptyList())

    private suspend fun enrichParticipants(
        activityId: String,
        rows: List<FinancialParticipantRowDto>,
    ): Map<String, ParticipantInfo> {
        val claims = client.from("participant_claims").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialClaimRowDto>()
        val profiles = loadClaimedProfiles(claims)
        return rows.associate { row ->
            val claim = claims.firstOrNull { it.participantId == row.id }
            row.id to row.toParticipant().copy(
                claimedUserId = claim?.userId,
                avatarStyle = claim?.userId?.let { profiles[it]?.avatarStyle },
            )
        }
    }

    private suspend fun loadClaimedProfiles(
        claims: List<FinancialClaimRowDto>,
    ): Map<String, FinancialProfileRowDto> {
        val userIds = claims.mapNotNull { it.userId }.distinct()
        if (userIds.isEmpty()) return emptyMap()
        return client.from("profiles").select {
            filter { isIn("id", userIds) }
        }.decodeList<FinancialProfileRowDto>().associateBy { it.id }
    }
}

/** PostgREST uses PGRST202/404 when a new overloaded RPC is not in the schema cache yet. */
private fun isMissingFinancialRpc(error: Throwable): Boolean {
    var current: Throwable? = error
    while (current != null) {
        if (current is PostgrestRestException &&
            (current.code.equals("PGRST202", ignoreCase = true) || current.statusCode == 404)
        ) return true
        current = current.cause
    }
    return false
}

internal data class TransferDisputeResult(val dispute: com.ffocalors.sharedledger.domain.financial.TransferDispute)

internal class FinancialWriteCommittedException(
    val operationId: String,
    userMessage: String,
    cause: Throwable? = null,
) : FinancialOperationException(userMessage, cause)

internal class FinancialWriteUnknownException(
    val operationId: String?,
    userMessage: String,
    cause: Throwable? = null,
) : FinancialOperationException(userMessage, cause)

open class FinancialOperationException(val userMessage: String, cause: Throwable? = null) : RuntimeException(userMessage, cause)
