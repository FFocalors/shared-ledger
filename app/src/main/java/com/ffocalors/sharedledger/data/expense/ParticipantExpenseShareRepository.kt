package com.ffocalors.sharedledger.data.expense

import com.ffocalors.sharedledger.data.activity.ParticipantClaimRowDto
import com.ffocalors.sharedledger.data.supabase.SupabaseClientProvider
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import java.math.BigDecimal

/**
 * The expense amount a signed-in user owns through their claimed participant.
 * A null total is reserved for the unbound state; zero is a real bound result.
 */
data class ParticipantExpenseShareSnapshot(
    val isBound: Boolean,
    val activityTotalBaseAmount: BigDecimal?,
    val ledgerUnitTotals: Map<String, BigDecimal>,
    val expenseTotals: Map<String, BigDecimal>,
) {
    companion object {
        fun unbound() = ParticipantExpenseShareSnapshot(
            isBound = false,
            activityTotalBaseAmount = null,
            ledgerUnitTotals = emptyMap(),
            expenseTotals = emptyMap(),
        )
    }
}

interface ParticipantExpenseShareRepository {
    suspend fun getForActivity(activityId: String, currentUserId: String): Result<ParticipantExpenseShareSnapshot>
    suspend fun getForLedgerUnit(
        activityId: String,
        ledgerUnitId: String,
        currentUserId: String,
    ): Result<ParticipantExpenseShareSnapshot>
}

class SupabaseParticipantExpenseShareRepository(
    private val client: SupabaseClient,
) : ParticipantExpenseShareRepository {
    override suspend fun getForActivity(
        activityId: String,
        currentUserId: String,
    ): Result<ParticipantExpenseShareSnapshot> = runCatching {
        load(activityId, null, currentUserId)
    }.mapFailure()

    override suspend fun getForLedgerUnit(
        activityId: String,
        ledgerUnitId: String,
        currentUserId: String,
    ): Result<ParticipantExpenseShareSnapshot> = runCatching {
        load(activityId, ledgerUnitId, currentUserId)
    }.mapFailure()

    private suspend fun load(
        activityId: String,
        ledgerUnitId: String?,
        currentUserId: String,
    ): ParticipantExpenseShareSnapshot {
        val claimedParticipantId = client.from("participant_claims").select {
            filter {
                eq("activity_id", activityId)
                eq("user_id", currentUserId)
            }
        }.decodeList<ParticipantClaimRowDto>().firstOrNull()?.participantId
            ?: return ParticipantExpenseShareSnapshot.unbound()

        val units = client.from("ledger_units").select {
            filter {
                eq("activity_id", activityId)
                eq("is_deleted", false)
                ledgerUnitId?.let { eq("id", it) }
            }
        }.decodeList<ExpenseLedgerUnitRowDto>()
        val unitIds = units.map { it.id }
        if (unitIds.isEmpty()) {
            return ParticipantExpenseShareSnapshot(
                isBound = true,
                activityTotalBaseAmount = BigDecimal.ZERO,
                ledgerUnitTotals = emptyMap(),
                expenseTotals = emptyMap(),
            )
        }

        // The rows are filtered by the signed-in user's claimed participant.
        // RLS still governs both the expense and split reads.
        val expenses = client.from("expenses").select {
            filter {
                isIn("ledger_unit_id", unitIds)
            }
        }.decodeList<ExpenseShareExpenseRowDto>()
        val expenseIds = expenses.map { it.id }
        val splitRows = if (expenseIds.isEmpty()) {
            emptyList()
        } else {
            client.from("splits").select {
                filter {
                    isIn("expense_id", expenseIds)
                    eq("participant_id", claimedParticipantId)
                }
            }.decodeList<ExpenseShareSplitRowDto>()
        }
        return ParticipantExpenseShareAggregator.aggregate(
            participantId = claimedParticipantId,
            expenses = expenses.map { ParticipantExpenseFact(it.id, it.ledgerUnitId, it.isDeleted) },
            splits = splitRows.map {
                ParticipantSplitFact(
                    expenseId = it.expenseId,
                    participantId = it.participantId,
                    baseAmount = ExpenseDtoMappers.decimalOrNull(it.baseAmount)
                        ?: error("split.base_amount is missing"),
                )
            },
        )
    }

    private fun <T> Result<T>.mapFailure(): Result<T> = fold(
        onSuccess = { Result.success(it) },
        onFailure = { Result.failure(ExpenseOperationException(ExpenseErrorMapper.toUserMessage(it), it)) },
    )
}

object ParticipantExpenseShareAggregator {
    fun aggregate(
        participantId: String,
        expenses: List<ParticipantExpenseFact>,
        splits: List<ParticipantSplitFact>,
    ): ParticipantExpenseShareSnapshot {
        val expenseIds = expenses.map { it.id }.toSet()
        val expenseTotals = splits
            .asSequence()
            .filter { it.participantId == participantId && it.expenseId in expenseIds }
            .groupingBy { it.expenseId }
            .fold(BigDecimal.ZERO) { total, split -> total + split.baseAmount }
        val completeExpenseTotals = expenses.associate { it.id to (expenseTotals[it.id] ?: BigDecimal.ZERO) }
        val activeExpenses = expenses.filterNot { it.isDeleted }
        val ledgerUnitTotals = activeExpenses
            .groupBy { it.ledgerUnitId }
            .mapValues { (_, unitExpenses) ->
                unitExpenses.fold(BigDecimal.ZERO) { total, expense -> total + (completeExpenseTotals[expense.id] ?: BigDecimal.ZERO) }
            }
        return ParticipantExpenseShareSnapshot(
            isBound = true,
            activityTotalBaseAmount = activeExpenses.fold(BigDecimal.ZERO) { total, expense ->
                total + (completeExpenseTotals[expense.id] ?: BigDecimal.ZERO)
            },
            ledgerUnitTotals = ledgerUnitTotals,
            expenseTotals = completeExpenseTotals,
        )
    }
}

data class ParticipantExpenseFact(
    val id: String,
    val ledgerUnitId: String,
    val isDeleted: Boolean = false,
)

data class ParticipantSplitFact(
    val expenseId: String,
    val participantId: String,
    val baseAmount: BigDecimal,
)

@Serializable
private data class ExpenseShareExpenseRowDto(
    val id: String,
    @SerialName("ledger_unit_id") val ledgerUnitId: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
private data class ExpenseShareSplitRowDto(
    @SerialName("expense_id") val expenseId: String,
    @SerialName("participant_id") val participantId: String,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
)

object ParticipantExpenseShareRepositoryFactory {
    fun create(): ParticipantExpenseShareRepository = runCatching {
        SupabaseClientProvider.createOrNull()
            ?.let(::SupabaseParticipantExpenseShareRepository)
            ?: UnavailableParticipantExpenseShareRepository()
    }.getOrElse { UnavailableParticipantExpenseShareRepository() }
}

class UnavailableParticipantExpenseShareRepository(
    private val message: String = "尚未配置 Supabase，无法加载我的应承担金额",
) : ParticipantExpenseShareRepository {
    private fun unavailable(): Result<ParticipantExpenseShareSnapshot> =
        Result.failure(ExpenseOperationException(message))

    override suspend fun getForActivity(activityId: String, currentUserId: String) = unavailable()

    override suspend fun getForLedgerUnit(activityId: String, ledgerUnitId: String, currentUserId: String) = unavailable()
}
