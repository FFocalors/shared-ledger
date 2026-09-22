package com.ffocalors.sharedledger.data.financial

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.KSerializer
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

@Serializable
internal data class FinancialTransferRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("from_participant_id") val fromParticipantId: String,
    @SerialName("to_participant_id") val toParticipantId: String,
    val type: String,
    val amount: JsonElement? = null,
    val currency: String = "",
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("occurred_at") val occurredAt: String,
    @SerialName("recorded_by") val recordedBy: String,
    @SerialName("on_behalf_of_participant_id") val onBehalfOfParticipantId: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("is_voided") val isVoided: Boolean = false,
    @SerialName("voided_at") val voidedAt: String? = null,
    @SerialName("voided_by") val voidedBy: String? = null,
    @SerialName("void_reason") val voidReason: String? = null,
)

@Serializable
internal data class FinancialParticipantRowDto(
    val id: String,
    val name: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
)

@Serializable
internal data class FinancialProfileRowDto(
    val id: String,
    @SerialName("display_name") val displayName: String? = null,
    @SerialName("avatar_style") val avatarStyle: String? = null,
)

@Serializable
internal data class FinancialComponentRowDto(
    val id: String,
    @SerialName("transfer_id") val transferId: String,
    @SerialName("component_type") val componentType: String,
    val amount: JsonElement? = null,
)

@Serializable
internal data class FinancialDisputeRowDto(
    val id: String,
    @SerialName("transfer_id") val transferId: String,
    @SerialName("participant_id") val participantId: String,
    @SerialName("disputed_by") val disputedBy: String,
    val note: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("resolved_at") val resolvedAt: String? = null,
    @SerialName("resolved_by") val resolvedBy: String? = null,
)

@Serializable
internal data class FinancialPathRowDto(
    val id: String,
    @SerialName("transfer_id") val transferId: String,
    @SerialName("path_no") @Serializable(with = FlexibleIntSerializer::class) val pathNo: Int,
    @SerialName("hop_no") @Serializable(with = FlexibleIntSerializer::class) val hopNo: Int,
    @SerialName("from_participant_id") val fromParticipantId: String,
    @SerialName("to_participant_id") val toParticipantId: String,
    val amount: JsonElement? = null,
    @SerialName("component_type") val componentType: String,
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("path_currency") val pathCurrency: String? = null,
    val mode: String? = null,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
    @SerialName("original_amount") val originalAmount: JsonElement? = null,
)

@Serializable
internal data class FinancialAccountRowDto(
    val id: String,
    @SerialName("activity_id") val activityId: String,
    @SerialName("owner_participant_id") val ownerParticipantId: String,
    @SerialName("custodian_participant_id") val custodianParticipantId: String,
    val balance: JsonElement? = null,
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("currency") val currency: String? = null,
    @SerialName("base_balance") val baseBalance: JsonElement? = null,
)

@Serializable
internal data class FinancialPrepaymentUsageRowDto(
    val id: String,
    @SerialName("account_id") val accountId: String,
    val amount: JsonElement? = null,
    @SerialName("expense_debt_id") val expenseDebtId: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("currency") val currency: String? = null,
    @SerialName("prepayment_currency") val prepaymentCurrency: String? = null,
    @SerialName("prepayment_amount") val prepaymentAmount: JsonElement? = null,
    @SerialName("debt_currency") val debtCurrency: String? = null,
    @SerialName("debt_amount") val debtAmount: JsonElement? = null,
    @SerialName("original_amount") val originalAmount: JsonElement? = null,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
    @SerialName("bill_fx_rate") val billFxRate: JsonElement? = null,
    @SerialName("bill_occurred_at") val billOccurredAt: String? = null,
)

@Serializable
internal data class FinancialExpenseDebtRowDto(
    val id: String,
    @SerialName("expense_id") val expenseId: String,
)

@Serializable
internal data class FinancialExpenseTimelineRowDto(
    val id: String,
    val title: String,
    @SerialName("occurred_at") val occurredAt: String,
)

@Serializable
internal data class FinancialRefundExpenseRowDto(
    val id: String,
    @SerialName("ledger_unit_id") val ledgerUnitId: String,
    val title: String,
    @SerialName("original_amount") val originalAmount: JsonElement? = null,
    @SerialName("original_currency") val originalCurrency: String,
    @SerialName("original_expense_id") val originalExpenseId: String? = null,
    @SerialName("occurred_at") val occurredAt: String,
    @SerialName("created_by") val createdBy: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("is_deleted") val isDeleted: Boolean = false,
    @SerialName("deleted_at") val deletedAt: String? = null,
    @SerialName("deleted_by") val deletedBy: String? = null,
)

@Serializable
internal data class FinancialExpensePartyRowDto(
    @SerialName("expense_id") val expenseId: String,
    @SerialName("participant_id") val participantId: String,
    val amount: JsonElement? = null,
)

@Serializable
internal data class FinancialActivityRowDto(
    @SerialName("base_currency") val baseCurrency: String,
    @SerialName("created_by") val createdBy: String? = null,
    @SerialName("multi_currency_enabled") val multiCurrencyEnabled: Boolean = false,
    @SerialName("financial_version") @Serializable(with = FlexibleLongSerializer::class) val financialVersion: Long = 0L,
)

@Serializable
internal data class FinancialClaimRowDto(
    @SerialName("participant_id") val participantId: String,
    @SerialName("user_id") val userId: String? = null,
)

@Serializable
internal data class FinancialVoidRpcDto(
    @SerialName("transfer_id") val transferId: String,
    val voided: Boolean,
    @SerialName("financial_version") @Serializable(with = FlexibleLongSerializer::class) val financialVersion: Long = 0L,
)

@Serializable
internal data class FinancialDisputeRpcDto(
    @SerialName("dispute_id") val disputeId: String,
    val created: Boolean,
)

@Serializable
internal data class FinancialTransferRpcDto(
    @SerialName("transfer_id") val transferId: String = "",
    val amount: JsonElement? = null,
    val currency: String = "",
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("financial_version") @Serializable(with = FlexibleLongSerializer::class) val financialVersion: Long = 0L,
    @SerialName("request_id") val requestId: String? = null,
    @SerialName("settlement_amount") val settlementAmount: JsonElement? = null,
    @SerialName("new_prepayment_balance") val newPrepaymentBalance: JsonElement? = null,
    val mode: String? = null,
)

@Serializable
internal data class FinancialPrepaymentRpcDto(
    @SerialName("transfer_id") val transferId: String = "",
    @SerialName("settlement_amount") val settlementAmount: JsonElement? = null,
    @SerialName("prepayment_amount") val prepaymentAmount: JsonElement? = null,
    val currency: String = "",
    @SerialName("financial_version") @Serializable(with = FlexibleLongSerializer::class) val financialVersion: Long = 0L,
    @SerialName("request_id") val requestId: String? = null,
    @SerialName("new_prepayment_balance") val newPrepaymentBalance: JsonElement? = null,
    @SerialName("new_balance") val newBalance: JsonElement? = null,
    @SerialName("remaining_balance") val remainingBalance: JsonElement? = null,
    @SerialName("currency_code") val currencyCode: String? = null,
)

@Serializable
internal data class FinancialPrepaymentPreviewRpcDto(
    @SerialName("activity_id") val activityId: String? = null,
    @SerialName("amount") val amount: JsonElement? = null,
    @SerialName("requested_amount") val requestedAmount: JsonElement? = null,
    @SerialName("settlement_amount") val settlementAmount: JsonElement? = null,
    @SerialName("prepayment_amount") val prepaymentAmount: JsonElement? = null,
    @SerialName("new_prepayment_balance") val newPrepaymentBalance: JsonElement? = null,
    @SerialName("new_balance") val newBalance: JsonElement? = null,
    val currency: String? = null,
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("financial_version") @Serializable(with = FlexibleLongSerializer::class) val financialVersion: Long = 0L,
    @SerialName("request_id") val requestId: String? = null,
)

@Serializable
internal data class FinancialSupportedCurrencyRowDto(
    @SerialName("currency_code") val currencyCode: String,
    @SerialName("display_name") val displayName: String? = null,
)

@Serializable
internal data class FinancialPreviewRowDto(
    @SerialName("activity_id") val activityId: String,
    @SerialName("from_participant_id") val fromParticipantId: String,
    @SerialName("to_participant_id") val toParticipantId: String,
    val amount: JsonElement? = null,
    @SerialName("ordinary_amount") val ordinaryAmount: JsonElement? = null,
    @SerialName("prepayment_return_amount") val prepaymentReturnAmount: JsonElement? = null,
    val currency: String,
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("source_financial_version") @Serializable(with = FlexibleNullableLongSerializer::class) val sourceFinancialVersion: Long? = null,
    @SerialName("is_prepayment_return") val isPrepaymentReturn: Boolean = false,
    @SerialName("base_amount") val baseAmount: JsonElement? = null,
    @SerialName("original_amount") val originalAmount: JsonElement? = null,
    @SerialName("settlement_amount") val settlementAmount: JsonElement? = null,
    @SerialName("final_mode") val finalMode: String? = null,
    @SerialName("settlement_mode") val settlementMode: String? = null,
    val mode: String? = null,
    @SerialName("path_currency") val pathCurrency: String? = null,
    @SerialName("plan_no") @Serializable(with = FlexibleNullableIntSerializer::class) val planNo: Int? = null,
    @SerialName("path_no") @Serializable(with = FlexibleNullableIntSerializer::class) val pathNo: Int? = null,
    @SerialName("hop_no") @Serializable(with = FlexibleNullableIntSerializer::class) val hopNo: Int? = null,
)

/** PostgREST can expose bigint as a JSON number, quoted number, or null. */
internal object FlexibleLongSerializer : KSerializer<Long> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("FlexibleLong", PrimitiveKind.LONG)

    override fun deserialize(decoder: Decoder): Long {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement()
            ?: return decoder.decodeLong()
        return when (element) {
            JsonNull -> 0L
            is JsonPrimitive -> element.content.toLongOrNull() ?: element.content.toDoubleOrNull()?.toLong() ?: 0L
            else -> 0L
        }
    }

    override fun serialize(encoder: Encoder, value: Long) = encoder.encodeLong(value)
}

/** Final-settlement previews must preserve a missing or invalid version as null. */
internal object FlexibleNullableLongSerializer : KSerializer<Long?> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("FlexibleNullableLong", PrimitiveKind.LONG)

    override fun deserialize(decoder: Decoder): Long? {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement()
            ?: return decoder.decodeLong()
        return when (element) {
            JsonNull -> null
            is JsonPrimitive -> element.content.toLongOrNull() ?: runCatching {
                java.math.BigDecimal(element.content).toBigIntegerExact().longValueExact()
            }.getOrNull()
            else -> null
        }
    }

    override fun serialize(encoder: Encoder, value: Long?) {
        if (value == null) encoder.encodeNull() else encoder.encodeLong(value)
    }
}

internal object FlexibleIntSerializer : KSerializer<Int> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("FlexibleInt", PrimitiveKind.INT)

    override fun deserialize(decoder: Decoder): Int {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement()
            ?: return decoder.decodeInt()
        return when (element) {
            JsonNull -> 0
            is JsonPrimitive -> element.content.toIntOrNull() ?: element.content.toDoubleOrNull()?.toInt() ?: 0
            else -> 0
        }
    }

    override fun serialize(encoder: Encoder, value: Int) = encoder.encodeInt(value)
}

internal object FlexibleNullableIntSerializer : KSerializer<Int?> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("FlexibleNullableInt", PrimitiveKind.INT)

    override fun deserialize(decoder: Decoder): Int? {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement()
            ?: return decoder.decodeInt()
        return when (element) {
            JsonNull -> null
            is JsonPrimitive -> element.content.toIntOrNull() ?: element.content.toDoubleOrNull()?.toInt()
            else -> null
        }
    }

    override fun serialize(encoder: Encoder, value: Int?) {
        if (value == null) encoder.encodeNull() else encoder.encodeInt(value)
    }
}
