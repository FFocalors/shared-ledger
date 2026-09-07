package com.ffocalors.sharedledger.data.financial

import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import com.ffocalors.sharedledger.domain.financial.FundRecord
import com.ffocalors.sharedledger.domain.financial.FundRecordType
import com.ffocalors.sharedledger.domain.financial.ParticipantInfo
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import java.math.BigDecimal
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal class FinancialRemoteDataSource(private val client: SupabaseClient) {
    private suspend fun currentUserId(): String = client.auth.currentSessionOrNull()?.user?.id
        ?: throw FinancialOperationException("登录状态已失效，请重新登录")

    suspend fun listRecords(activityId: String, type: FundRecordType? = null): List<FundRecord> {
        val transfers = if (type == FundRecordType.AUTO_PREPAYMENT_USAGE) {
            emptyList()
        } else {
            client.from("transfers").select {
                filter {
                    eq("activity_id", activityId)
                    type?.let { eq("type", it.databaseValue) }
                }
            }.decodeList<FinancialTransferRowDto>()
        }
        val transferRecords = enrich(activityId, transfers)
        val usageRecords = if (type == null || type == FundRecordType.AUTO_PREPAYMENT_USAGE) {
            enrichPrepaymentUsages(activityId)
        } else {
            emptyList()
        }
        return (transferRecords + usageRecords).sortedByDescending { it.occurredAt }
    }

    suspend fun getRecord(activityId: String, transferId: String): FundRecord =
        listRecords(activityId).firstOrNull { it.transferId == transferId }
            ?: throw FinancialOperationException("未找到资金记录")

    suspend fun currentParticipantId(activityId: String): String? {
        val userId = currentUserId()
        return client.from("participant_claims").select {
            filter { eq("activity_id", activityId); eq("user_id", userId) }
        }.decodeList<FinancialClaimRowDto>().firstOrNull()?.participantId
    }

    suspend fun loadContext(activityId: String): FinancialContext {
        val participants = client.from("participants").select {
            filter { eq("activity_id", activityId); eq("is_deleted", false) }
        }.decodeList<FinancialParticipantRowDto>().map { it.toParticipant() }
        val currency = client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<FinancialActivityRowDto>().baseCurrency.trim().uppercase()
        val accounts = client.from("prepayment_accounts").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialAccountRowDto>().mapNotNull { row ->
            val owner = participants.firstOrNull { it.participantId == row.ownerParticipantId }
            val custodian = participants.firstOrNull { it.participantId == row.custodianParticipantId }
            if (owner == null || custodian == null) null else PrepaymentAccount(
                accountId = row.id,
                owner = owner,
                custodian = custodian,
                balance = row.balance.toFinancialBigDecimal(),
                usedAmount = BigDecimal.ZERO,
            )
        }
        val usagesByAccount = client.from("prepayment_usages").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialPrepaymentUsageRowDto>()
            .let(::aggregatePrepaymentUsageAmounts)
        val accountsWithUsage = accounts.map { account ->
            account.copy(usedAmount = usagesByAccount[account.accountId] ?: BigDecimal.ZERO)
        }
        return FinancialContext(activityId, currency, participants, currentParticipantId(activityId), accountsWithUsage)
    }

    suspend fun previewFinalSettlement(activityId: String): List<FinalSettlementSuggestion> {
        val rows = client.postgrest.rpc("preview_activity_settlement", buildJsonObject {
            put("activity_id", activityId)
        }).decodeList<FinancialPreviewRowDto>()
        val participantNames = client.from("participants").select {
            filter { eq("activity_id", activityId); eq("is_deleted", false) }
        }.decodeList<FinancialParticipantRowDto>().associate { it.id to it.toParticipant() }
        return rows.mapNotNull { row ->
            val from = participantNames[row.fromParticipantId] ?: return@mapNotNull null
            val to = participantNames[row.toParticipantId] ?: return@mapNotNull null
            val amount = row.amount.toFinancialBigDecimal()
            if (amount <= BigDecimal.ZERO) return@mapNotNull null
            FinalSettlementSuggestion(
                id = "${row.fromParticipantId}-${row.toParticipantId}-${amount.toPlainString()}-${row.sourceFinancialVersion}",
                activityId = row.activityId,
                from = from,
                to = to,
                amount = amount,
                ordinaryAmount = row.ordinaryAmount.toFinancialBigDecimal(),
                prepaymentReturnAmount = row.prepaymentReturnAmount.toFinancialBigDecimal(),
                currency = row.currency.trim().uppercase(),
                sourceFinancialVersion = row.sourceFinancialVersion,
            )
        }
    }

    suspend fun createPrepayment(input: PrepaymentInput): FundRecord {
        val response = client.postgrest.rpc("create_prepayment", buildJsonObject {
            put("activity_id", input.activityId)
            put("owner_participant_id", input.ownerParticipantId)
            put("custodian_participant_id", input.custodianParticipantId)
            put("amount", input.amount.toPlainString())
            put("occurred_at", input.occurredAt)
            put("on_behalf_of_participant_id", JsonNull)
        }).decodeSingle<FinancialPrepaymentRpcDto>()
        return getRecord(input.activityId, response.transferId)
    }

    suspend fun createPrepaymentReturn(input: PrepaymentInput): FundRecord {
        val response = client.postgrest.rpc("create_prepayment_return", buildJsonObject {
            put("activity_id", input.activityId)
            put("owner_participant_id", input.ownerParticipantId)
            put("custodian_participant_id", input.custodianParticipantId)
            put("amount", input.amount.toPlainString())
            put("occurred_at", input.occurredAt)
            put("on_behalf_of_participant_id", JsonNull)
        }).decodeSingle<FinancialTransferRpcDto>()
        return getRecord(input.activityId, response.transferId)
    }

    suspend fun void(record: FundRecord, reason: String): FundRecord {
        if (record.isReadOnly) throw FinancialOperationException("预存自动抵扣记录仅供查看，不能作废")
        val rpc = if (record.type == FundRecordType.SETTLEMENT) "void_settlement_transfer" else "void_prepayment_transfer"
        client.postgrest.rpc(rpc, buildJsonObject {
            put("transfer_id", record.transferId)
            put("void_reason", reason.trim())
        }).decodeSingle<FinancialVoidRpcDto>()
        return getRecord(record.activityId, record.transferId)
    }

    suspend fun addDispute(activityId: String, transferId: String, participantId: String, note: String): TransferDisputeResult {
        val response = client.postgrest.rpc("add_transfer_dispute", buildJsonObject {
            put("transfer_id", transferId)
            put("participant_id", participantId)
            put("note", note.trim())
        }).decodeSingle<FinancialDisputeRpcDto>()
        val record = getRecord(activityId, transferId)
        val dispute = record.disputes.firstOrNull { it.disputeId == response.disputeId }
            ?: throw FinancialOperationException("争议提交成功，但刷新记录失败")
        return TransferDisputeResult(dispute)
    }

    suspend fun resolveDispute(activityId: String, disputeId: String): TransferDisputeResult {
        client.postgrest.rpc("remove_transfer_dispute", buildJsonObject {
            put("dispute_id", disputeId)
        }).decodeSingle<Boolean>()
        val record = listRecords(activityId).firstOrNull { it.disputes.any { dispute -> dispute.disputeId == disputeId } }
            ?: throw FinancialOperationException("争议已更新，但刷新记录失败")
        return TransferDisputeResult(record.disputes.first { it.disputeId == disputeId })
    }

    suspend fun executeFinalSettlement(request: FinalSettlementSuggestion, occurredAt: String): FundRecord {
        val response = client.postgrest.rpc("execute_final_settlement_item", buildJsonObject {
            put("activity_id", request.activityId)
            put("from_participant_id", request.from.participantId)
            put("to_participant_id", request.to.participantId)
            put("amount", request.amount.toPlainString())
            put("occurred_at", occurredAt)
            put("on_behalf_of_participant_id", JsonNull)
        }).decodeSingle<FinancialTransferRpcDto>()
        return getRecord(request.activityId, response.transferId)
    }

    private suspend fun enrich(activityId: String, transfers: List<FinancialTransferRowDto>): List<FundRecord> {
        if (transfers.isEmpty()) return emptyList()
        val participants = client.from("participants").select {
            filter { eq("activity_id", activityId); eq("is_deleted", false) }
        }.decodeList<FinancialParticipantRowDto>().associate { it.id to it.toParticipant() }
        val transferIds = transfers.map { it.id }
        val components = client.from("transfer_components").select {
            filter { eq("activity_id", activityId); isIn("transfer_id", transferIds) }
        }.decodeList<FinancialComponentRowDto>().groupBy { it.transferId }
        val disputes = client.from("transfer_disputes").select {
            filter { eq("activity_id", activityId); isIn("transfer_id", transferIds) }
        }.decodeList<FinancialDisputeRowDto>().groupBy { it.transferId }
        val paths = client.from("final_settlement_paths").select {
            filter { eq("activity_id", activityId); isIn("transfer_id", transferIds) }
        }.decodeList<FinancialPathRowDto>().groupBy { it.transferId }
        val userIds = buildSet {
            transfers.forEach { add(it.recordedBy); it.voidedBy?.let(::add) }
            disputes.values.flatten().forEach { add(it.disputedBy); it.resolvedBy?.let(::add) }
        }
        val profiles = if (userIds.isEmpty()) emptyMap() else client.from("profiles").select {
            filter { isIn("id", userIds.toList()) }
        }.decodeList<FinancialProfileRowDto>().associate { it.id to it.toRecorder() }
        return transfers.map {
            mapFinancialRecord(it, participants, profiles, components[it.id].orEmpty(), disputes[it.id].orEmpty(), paths[it.id].orEmpty())
        }.sortedByDescending { it.occurredAt }
    }

    private suspend fun enrichPrepaymentUsages(activityId: String): List<FundRecord> {
        val accounts = client.from("prepayment_accounts").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialAccountRowDto>().associateBy { it.id }
        if (accounts.isEmpty()) return emptyList()
        val usages = client.from("prepayment_usages").select {
            filter { eq("activity_id", activityId) }
        }.decodeList<FinancialPrepaymentUsageRowDto>()
        if (usages.isEmpty()) return emptyList()
        val debtIds = usages.mapNotNull { it.expenseDebtId }.distinct()
        if (debtIds.isEmpty()) return emptyList()
        val debts = client.from("expense_debts").select {
            filter { isIn("id", debtIds) }
        }.decodeList<FinancialExpenseDebtRowDto>().associateBy { it.id }
        val expenseIds = debts.values.map { it.expenseId }.distinct()
        if (expenseIds.isEmpty()) return emptyList()
        val expenses = client.from("expenses").select {
            filter { isIn("id", expenseIds) }
        }.decodeList<FinancialExpenseTimelineRowDto>().associateBy { it.id }
        val participants = client.from("participants").select {
            filter { eq("activity_id", activityId); eq("is_deleted", false) }
        }.decodeList<FinancialParticipantRowDto>().associate { it.id to it.toParticipant() }
        val currency = client.from("activities").select {
            filter { eq("id", activityId) }
        }.decodeSingle<FinancialActivityRowDto>().baseCurrency.trim().uppercase()
        return usages.mapNotNull { usage ->
            val account = accounts[usage.accountId] ?: return@mapNotNull null
            val debt = usage.expenseDebtId?.let(debts::get) ?: return@mapNotNull null
            val expense = expenses[debt.expenseId] ?: return@mapNotNull null
            mapPrepaymentUsageRecord(usage, account, debt, expense, participants, currency)
        }
    }
}

internal data class TransferDisputeResult(val dispute: com.ffocalors.sharedledger.domain.financial.TransferDispute)

class FinancialOperationException(val userMessage: String, cause: Throwable? = null) : RuntimeException(userMessage, cause)
