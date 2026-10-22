@file:OptIn(ExperimentalSerializationApi::class)

package com.ffocalors.sharedledger.data.agent

import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonContentPolymorphicSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNamingStrategy
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Agent HTTP contract v1.0.0 DTOs (snake_case on the wire, mapped by [JsonNamingStrategy.SnakeCase]).
 *
 * Money and decimals are always [String]; timestamps stay ISO-8601 strings so the data layer never
 * rounds or reinterprets them.
 */
const val AGENT_API_VERSION = "1.0.0"

val AgentJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
    namingStrategy = JsonNamingStrategy.SnakeCase
}

// ---------------------------------------------------------------------------------------------
// Lenient enums: an unknown value from a newer server decodes to UNKNOWN instead of failing the
// whole response.
// ---------------------------------------------------------------------------------------------

interface WireEnum {
    val wire: String
}

abstract class LenientEnumSerializer<E>(
    serialName: String,
    private val entries: List<E>,
    private val fallback: E,
) : KSerializer<E> where E : Enum<E>, E : WireEnum {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor(serialName, PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): E {
        val raw = decoder.decodeString()
        return entries.firstOrNull { it.wire == raw } ?: fallback
    }

    override fun serialize(encoder: Encoder, value: E) = encoder.encodeString(value.wire)
}

object AgentErrorCodeSerializer : LenientEnumSerializer<AgentErrorCode>(
    "AgentErrorCode", AgentErrorCode.entries, AgentErrorCode.UNKNOWN,
)

@Serializable(with = AgentErrorCodeSerializer::class)
enum class AgentErrorCode(override val wire: String) : WireEnum {
    UNAUTHENTICATED("unauthenticated"),
    FORBIDDEN("forbidden"),
    NOT_FOUND("not_found"),
    IDEMPOTENCY_CONFLICT("idempotency_conflict"),
    STATE_REVISION_CONFLICT("state_revision_conflict"),
    PROPOSAL_REVISION_CONFLICT("proposal_revision_conflict"),
    PROPOSAL_EXPIRED("proposal_expired"),
    EXECUTION_CAPABILITY_UNAVAILABLE("execution_capability_unavailable"),
    AGENT_DISABLED("agent_disabled"),
    RATE_LIMITED("rate_limited"),
    DEPENDENCY_UNAVAILABLE("dependency_unavailable"),
    INVALID_REQUEST("invalid_request"),
    UNKNOWN("unknown"),
}

object TurnStateSerializer : LenientEnumSerializer<TurnState>("TurnState", TurnState.entries, TurnState.UNKNOWN)

/** Also used for `resume_state`, whose schema enum is a subset of these values. */
@Serializable(with = TurnStateSerializer::class)
enum class TurnState(override val wire: String) : WireEnum {
    QUEUED("QUEUED"),
    RUNNING("RUNNING"),
    WAIT_INPUT("WAIT_INPUT"),
    WAIT_CONFIRM("WAIT_CONFIRM"),
    EXECUTING("EXECUTING"),
    RECOVERING("RECOVERING"),
    COMPLETED("COMPLETED"),
    CANCELLED("CANCELLED"),
    FAILED("FAILED"),
    UNKNOWN("UNKNOWN"),
    ;

    val isTerminal: Boolean get() = this == COMPLETED || this == CANCELLED || this == FAILED
}

object TurnStepSerializer : LenientEnumSerializer<TurnStep>("TurnStep", TurnStep.entries, TurnStep.UNKNOWN)

@Serializable(with = TurnStepSerializer::class)
enum class TurnStep(override val wire: String) : WireEnum {
    ACCEPTED("accepted"),
    BUILD_CONTEXT("build_context"),
    MODEL_DECISION("model_decision"),
    TOOL_READ("tool_read"),
    PREPARE_PROPOSAL("prepare_proposal"),
    AWAITING_USER("awaiting_user"),
    AUTH_REQUIRED("auth_required"),
    DISPATCH("dispatch"),
    RECONCILE("reconcile"),
    FINALIZE("finalize"),
    TERMINAL("terminal"),
    UNKNOWN("unknown"),
}

object WaitReasonSerializer : LenientEnumSerializer<WaitReason>("WaitReason", WaitReason.entries, WaitReason.UNKNOWN)

@Serializable(with = WaitReasonSerializer::class)
enum class WaitReason(override val wire: String) : WireEnum {
    MISSING_FIELDS("missing_fields"),
    AUTH_REQUIRED("auth_required"),
    CONFIRM_REQUIRED("confirm_required"),
    EXECUTION_RESULT_UNKNOWN("execution_result_unknown"),
    UNKNOWN("unknown"),
}

object ExecutionResolutionSerializer : LenientEnumSerializer<ExecutionResolution>(
    "ExecutionResolution", ExecutionResolution.entries, ExecutionResolution.UNKNOWN,
)

@Serializable(with = ExecutionResolutionSerializer::class)
enum class ExecutionResolution(override val wire: String) : WireEnum {
    SUCCEEDED("succeeded"),
    REJECTED("rejected"),
    CLOSED("closed"),

    /** Contract value "unknown" (execution outcome not known) and any future unrecognised value. */
    UNKNOWN("unknown"),
}

object ProposalOperationSerializer : LenientEnumSerializer<ProposalOperation>(
    "ProposalOperation", ProposalOperation.entries, ProposalOperation.UNKNOWN,
)

@Serializable(with = ProposalOperationSerializer::class)
enum class ProposalOperation(override val wire: String) : WireEnum {
    EXPENSE_CREATE("expense.create"),
    EXPENSE_UPDATE("expense.update"),
    EXPENSE_PRESENTATION_UPDATE("expense.presentation.update"),
    UNKNOWN("unknown"),
}

object ProposalStatusSerializer : LenientEnumSerializer<ProposalStatus>(
    "ProposalStatus", ProposalStatus.entries, ProposalStatus.UNKNOWN,
)

@Serializable(with = ProposalStatusSerializer::class)
enum class ProposalStatus(override val wire: String) : WireEnum {
    PENDING("pending"),
    SUPERSEDED("superseded"),
    CANCELLED("cancelled"),
    EXPIRED("expired"),
    CONFIRMED("confirmed"),
    REJECTED("rejected"),
    CLOSED("closed"),
    UNKNOWN("unknown"),
}

object ProposalModeSerializer : LenientEnumSerializer<ProposalMode>(
    "ProposalMode", ProposalMode.entries, ProposalMode.UNKNOWN,
)

@Serializable(with = ProposalModeSerializer::class)
enum class ProposalMode(override val wire: String) : WireEnum {
    BACKEND("backend"),
    SIMULATION("simulation"),
    UNKNOWN("unknown"),
}

object CancelResultSerializer : LenientEnumSerializer<CancelResult>(
    "CancelResult", CancelResult.entries, CancelResult.UNKNOWN,
)

@Serializable(with = CancelResultSerializer::class)
enum class CancelResult(override val wire: String) : WireEnum {
    CANCELLED("cancelled"),
    CANCEL_REQUESTED("cancel_requested"),
    RECONCILING("reconciling"),
    UNKNOWN("unknown"),
}

object MissingSlotSerializer : LenientEnumSerializer<MissingSlot>(
    "MissingSlot", MissingSlot.entries, MissingSlot.UNKNOWN,
)

@Serializable(with = MissingSlotSerializer::class)
enum class MissingSlot(override val wire: String) : WireEnum {
    ACTIVITY_REF("activity_ref"),
    LEDGER_UNIT_REF("ledger_unit_ref"),
    EXPENSE_REF("expense_ref"),
    ORIGINAL_AMOUNT("original_amount"),
    ORIGINAL_CURRENCY("original_currency"),
    PAYMENT_ALLOCATIONS("payment_allocations"),
    TITLE("title"),
    SPLIT("split"),
    SPLIT_PARTICIPANT_REFS("split_participant_refs"),
    NOTE("note"),
    ICON_KEY("icon_key"),
    UPDATE_FIELDS("update_fields"),
    UNKNOWN("unknown"),
}

object AmountFieldSerializer : LenientEnumSerializer<AmountField>(
    "AmountField", AmountField.entries, AmountField.UNKNOWN,
)

@Serializable(with = AmountFieldSerializer::class)
enum class AmountField(override val wire: String) : WireEnum {
    ORIGINAL_AMOUNT("original_amount"),
    BASE_AMOUNT("base_amount"),
    UNKNOWN("unknown"),
}

object FxSourceSerializer : LenientEnumSerializer<FxSource>("FxSource", FxSource.entries, FxSource.UNKNOWN)

@Serializable(with = FxSourceSerializer::class)
enum class FxSource(override val wire: String) : WireEnum {
    ECB_SNAPSHOT("ecb_snapshot"),
    SERVER_SNAPSHOT("server_snapshot"),
    IDENTITY("identity"),
    UNKNOWN("unknown"),
}

/** Request-only enum: strict, never decoded from the server. */
@Serializable
enum class UiPageType {
    @SerialName("home") HOME,
    @SerialName("activity_overview") ACTIVITY_OVERVIEW,
    @SerialName("expense_list") EXPENSE_LIST,
    @SerialName("expense_detail") EXPENSE_DETAIL,
    @SerialName("debt_list") DEBT_LIST,
    @SerialName("prepayment") PREPAYMENT,
    @SerialName("settlement") SETTLEMENT,
    @SerialName("settings") SETTINGS,
}

/** Request-only enum: strict, never decoded from the server. */
@Serializable
enum class UiEntityType {
    @SerialName("activity") ACTIVITY,
    @SerialName("ledger_unit") LEDGER_UNIT,
    @SerialName("expense") EXPENSE,
    @SerialName("participant") PARTICIPANT,
}

// ---------------------------------------------------------------------------------------------
// Requests. `versions`/`api_version` defaults are emitted because AgentJson.encodeDefaults = true;
// null optionals (ui_context, title, reason) are omitted, which equals the schema default of null.
// ---------------------------------------------------------------------------------------------

@Serializable
data class ClientProtocolVersions(
    val api: String = AGENT_API_VERSION,
    val operations: String = AGENT_API_VERSION,
    val semantic: String = AGENT_API_VERSION,
)

@Serializable
data class UiEntityHint(
    val entityId: String,
    val entityType: UiEntityType,
)

@Serializable
data class UiFilters(
    val fromDate: String? = null,
    val participantIds: List<String> = emptyList(),
    val toDate: String? = null,
)

@Serializable
data class UiContext(
    val capturedAt: String,
    val clientVersion: String,
    val pageType: UiPageType,
    val activityId: String? = null,
    val filters: UiFilters = UiFilters(),
    val ledgerUnitId: String? = null,
    val schemaVersion: Int = 1,
    val selectedEntity: UiEntityHint? = null,
)

@Serializable
data class CreateSessionRequest(
    val clientRequestId: String,
    val title: String? = null,
    val uiContext: UiContext? = null,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class SubmitTurnRequest(
    val clientRequestId: String,
    val text: String,
    val uiContext: UiContext? = null,
    val versions: ClientProtocolVersions = ClientProtocolVersions(),
)

@Serializable
data class CancelTurnRequest(
    val clientRequestId: String,
    val expectedStateRevision: Int,
    val reason: String? = null,
    val versions: ClientProtocolVersions = ClientProtocolVersions(),
)

@Serializable
data class ResumeAuthRequest(
    val clientRequestId: String,
    val expectedStateRevision: Int,
    val versions: ClientProtocolVersions = ClientProtocolVersions(),
)

@Serializable
data class ResumeClarificationRequest(
    val clientRequestId: String,
    val expectedStateRevision: Int,
    val text: String,
    val versions: ClientProtocolVersions = ClientProtocolVersions(),
)

@Serializable
data class ResumeProposalAdjustRequest(
    val clientRequestId: String,
    val expectedProposalRevision: Int,
    val expectedStateRevision: Int,
    val text: String,
    val versions: ClientProtocolVersions = ClientProtocolVersions(),
)

@Serializable
data class ConfirmProposalRequest(
    val clientRequestId: String,
    val commandDigest: String,
    val confirmationNonce: String,
    val expectedProposalRevision: Int,
    val versions: ClientProtocolVersions = ClientProtocolVersions(),
)

// ---------------------------------------------------------------------------------------------
// Responses
// ---------------------------------------------------------------------------------------------

@Serializable
data class ApiErrorResponse(
    val code: AgentErrorCode,
    val message: String,
    val retryable: Boolean = false,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class ConfirmationUnavailableResponse(
    val code: AgentErrorCode,
    val message: String,
    val businessWritePerformed: Boolean = false,
    val executionEnabled: Boolean = false,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class SessionSummary(
    val sessionId: String,
    val createdAt: String,
    val updatedAt: String,
    val activeTurnCount: Int,
    val title: String? = null,
)

@Serializable
data class ListSessionsResponse(
    val items: List<SessionSummary>,
    val nextCursor: String? = null,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class CreateSessionResponse(
    val session: SessionSummary,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class TurnSummary(
    val turnId: String,
    val state: TurnState,
    val stateRevision: Int,
    val createdAt: String,
    val updatedAt: String,
)

@Serializable
data class SessionDetailResponse(
    val session: SessionSummary,
    val turns: List<TurnSummary> = emptyList(),
    val proposalCards: List<ProposalCard> = emptyList(),
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class SubmitTurnAccepted(
    val turnId: String,
    val acceptedAt: String,
    val state: TurnState = TurnState.QUEUED,
    val stateRevision: Int = 1,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class TurnMutationAccepted(
    val turnId: String,
    val state: TurnState,
    val stateRevision: Int,
    val eventCursor: Int,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class ProposalAdjustedAccepted(
    val turnId: String,
    val proposalId: String,
    val proposalRevision: Int,
    val state: TurnState,
    val stateRevision: Int,
    val eventCursor: Int,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class TurnPublicStatus(
    val turnId: String,
    val sessionId: String,
    val state: TurnState,
    val stateRevision: Int,
    val step: TurnStep,
    val contextVersion: Int,
    val executionAssigned: Boolean,
    val executionResolution: ExecutionResolution? = null,
    val resumeState: TurnState? = null,
    val waitReason: WaitReason? = null,
)

@Serializable
data class CancelTurnResponse(
    val result: CancelResult,
    val turn: TurnPublicStatus,
    val apiVersion: String = AGENT_API_VERSION,
)

@Serializable
data class PollEventsResponse(
    val afterSeq: Int,
    val nextAfterSeq: Int,
    val hasMore: Boolean,
    val turn: TurnPublicStatus,
    val events: List<AgentEvent> = emptyList(),
    val proposalCards: List<ProposalCard> = emptyList(),
    val apiVersion: String = AGENT_API_VERSION,
)

// ---------------------------------------------------------------------------------------------
// Events (discriminator: `type`). Decode-only; unknown types become [UnknownEvent].
// ---------------------------------------------------------------------------------------------

@Serializable(with = AgentEventSerializer::class)
sealed interface AgentEvent {
    val seq: Int
    val type: String
}

object AgentEventSerializer : JsonContentPolymorphicSerializer<AgentEvent>(AgentEvent::class) {
    override fun selectDeserializer(element: JsonElement): DeserializationStrategy<AgentEvent> =
        when (element.discriminator("type")) {
            "status" -> StatusEvent.serializer()
            "message" -> MessageEvent.serializer()
            "clarification" -> ClarificationEvent.serializer()
            "proposal" -> ProposalEvent.serializer()
            "execution_result" -> ExecutionResultEvent.serializer()
            "error" -> ErrorEvent.serializer()
            else -> UnknownEvent.serializer()
        }
}

@Serializable
data class StatusEventPayload(
    val state: TurnState,
    val stateRevision: Int,
    val step: TurnStep,
    val resumeState: TurnState? = null,
    val waitReason: WaitReason? = null,
)

@Serializable
data class MessageEventPayload(
    val text: String,
    val citations: List<String> = emptyList(),
)

@Serializable
data class ClarificationEventPayload(
    val missingSlots: List<MissingSlot>,
    val prompt: String,
    val resumeState: TurnState,
)

@Serializable
data class ProposalEventPayload(
    val operation: ProposalOperation,
    val proposalId: String,
    val revision: Int,
)

@Serializable
data class ExecutionReference(
    val executionId: String,
    val proposalId: String,
    val proposalRevision: Int,
    val operationsVersion: String = AGENT_API_VERSION,
)

@Serializable
data class ExecutionResultPayload(
    val execution: ExecutionReference,
    val resolution: ExecutionResolution,
    val resultCode: String? = null,
    val resultSummary: String? = null,
)

@Serializable
data class ErrorEventPayload(
    val code: AgentErrorCode,
    val message: String,
    val retryable: Boolean,
)

@Serializable
data class StatusEvent(
    override val seq: Int,
    val occurredAt: String,
    val simulation: Boolean,
    val payload: StatusEventPayload,
) : AgentEvent {
    override val type: String get() = "status"
}

@Serializable
data class MessageEvent(
    override val seq: Int,
    val occurredAt: String,
    val simulation: Boolean,
    val payload: MessageEventPayload,
) : AgentEvent {
    override val type: String get() = "message"
}

@Serializable
data class ClarificationEvent(
    override val seq: Int,
    val occurredAt: String,
    val simulation: Boolean,
    val payload: ClarificationEventPayload,
) : AgentEvent {
    override val type: String get() = "clarification"
}

@Serializable
data class ProposalEvent(
    override val seq: Int,
    val occurredAt: String,
    val simulation: Boolean,
    val payload: ProposalEventPayload,
) : AgentEvent {
    override val type: String get() = "proposal"
}

@Serializable
data class ExecutionResultEvent(
    override val seq: Int,
    val occurredAt: String,
    val simulation: Boolean,
    val payload: ExecutionResultPayload,
) : AgentEvent {
    override val type: String get() = "execution_result"
}

@Serializable
data class ErrorEvent(
    override val seq: Int,
    val occurredAt: String,
    val simulation: Boolean,
    val payload: ErrorEventPayload,
) : AgentEvent {
    override val type: String get() = "error"
}

/** An event type this client does not know. Keeps [seq] so the poll cursor can still advance. */
@Serializable
data class UnknownEvent(
    override val seq: Int = 0,
    override val type: String = "",
    val occurredAt: String? = null,
    val simulation: Boolean? = null,
) : AgentEvent

// ---------------------------------------------------------------------------------------------
// Proposal cards (discriminator: `card_kind`). Decode-only; unknown kinds become [UnknownProposalCard].
// ---------------------------------------------------------------------------------------------

@Serializable(with = ProposalCardSerializer::class)
sealed interface ProposalCard {
    val cardKind: String
}

object ProposalCardSerializer : JsonContentPolymorphicSerializer<ProposalCard>(ProposalCard::class) {
    override fun selectDeserializer(element: JsonElement): DeserializationStrategy<ProposalCard> =
        when (element.discriminator("card_kind")) {
            "simulation_pending" -> SimulationProposalCard.serializer()
            "backend_pending" -> ConfirmableProposalCard.serializer()
            "inactive" -> InactiveProposalCard.serializer()
            else -> UnknownProposalCard.serializer()
        }
}

@Serializable
data class SimulationProposalCard(
    val proposalId: String,
    val revision: Int,
    val operation: ProposalOperation,
    val preview: ExpensePreview,
    val confirmationEnabled: Boolean = false,
    val simulation: Boolean = true,
) : ProposalCard {
    override val cardKind: String get() = "simulation_pending"
    val mode: ProposalMode get() = ProposalMode.SIMULATION
    val status: ProposalStatus get() = ProposalStatus.PENDING
}

@Serializable
data class ConfirmableProposalCard(
    val proposalId: String,
    val revision: Int,
    val operation: ProposalOperation,
    val preview: ExpensePreview,
    val commandDigest: String,
    val confirmationNonce: String,
    val expiresAt: String,
    val simulation: Boolean = false,
) : ProposalCard {
    override val cardKind: String get() = "backend_pending"
    val mode: ProposalMode get() = ProposalMode.BACKEND
    val status: ProposalStatus get() = ProposalStatus.PENDING
}

@Serializable
data class InactiveProposalCard(
    val proposalId: String,
    val revision: Int,
    val operation: ProposalOperation,
    val mode: ProposalMode,
    val status: ProposalStatus,
    val simulation: Boolean,
    val commandDigest: String? = null,
    val preview: ExpensePreview? = null,
) : ProposalCard {
    override val cardKind: String get() = "inactive"
}

@Serializable
data class UnknownProposalCard(
    override val cardKind: String = "",
    val proposalId: String? = null,
) : ProposalCard

// ---------------------------------------------------------------------------------------------
// Expense preview
// ---------------------------------------------------------------------------------------------

@Serializable
data class CanonicalPayment(
    val amount: String,
    val participantId: String,
)

@Serializable
data class FxSnapshot(
    val baseCurrency: String,
    val observedAt: String,
    val originalCurrency: String,
    val rate: String,
    val source: FxSource,
)

/** Discriminator: `mode` (equal | manual). */
@Serializable(with = CanonicalSplitSerializer::class)
sealed interface CanonicalSplit {
    val mode: String
}

object CanonicalSplitSerializer : JsonContentPolymorphicSerializer<CanonicalSplit>(CanonicalSplit::class) {
    override fun selectDeserializer(element: JsonElement): DeserializationStrategy<CanonicalSplit> =
        when (element.discriminator("mode")) {
            "equal" -> CanonicalEqualSplit.serializer()
            "manual" -> CanonicalManualSplit.serializer()
            else -> UnknownSplit.serializer()
        }
}

@Serializable
data class CanonicalEqualSplit(val participantIds: List<String>) : CanonicalSplit {
    override val mode: String get() = "equal"
}

@Serializable
data class CanonicalManualSplit(val allocations: List<CanonicalPayment>) : CanonicalSplit {
    override val mode: String get() = "manual"
}

@Serializable
data class UnknownSplit(override val mode: String = "") : CanonicalSplit

@Serializable
data class ExpenseSnapshot(
    val baseAmount: String,
    val expenseVersion: String,
    val financialLocked: Boolean,
    val ledgerUnitId: String,
    val originalAmount: String,
    val originalCurrency: String,
    val paymentAllocations: List<CanonicalPayment>,
    val split: CanonicalSplit,
    val title: String,
    val fxSnapshot: FxSnapshot? = null,
    val iconKey: String? = null,
    val note: String? = null,
    val occurredAt: String? = null,
)

@Serializable
data class ExpensePreview(
    val activityFinancialVersion: String,
    val after: ExpenseSnapshot,
    val changes: List<ExpenseChange>,
    val generatedAt: String,
    val simulation: Boolean,
    val summary: String,
    val before: ExpenseSnapshot? = null,
) {
    val kind: String get() = "expense"
}

/**
 * Discriminator: `field`. `original_amount` and `base_amount` both map to [ExpenseAmountChange]
 * (the discriminator value is kept in [ExpenseAmountChange.amountField]), so selection is by hand.
 */
@Serializable(with = ExpenseChangeSerializer::class)
sealed interface ExpenseChange {
    val field: String
}

object ExpenseChangeSerializer : JsonContentPolymorphicSerializer<ExpenseChange>(ExpenseChange::class) {
    override fun selectDeserializer(element: JsonElement): DeserializationStrategy<ExpenseChange> =
        when (element.discriminator("field")) {
            "title" -> ExpenseTitleChange.serializer()
            "original_amount", "base_amount" -> ExpenseAmountChange.serializer()
            "original_currency" -> ExpenseCurrencyChange.serializer()
            "ledger_unit_id" -> ExpenseLedgerUnitChange.serializer()
            "payment_allocations" -> ExpensePaymentsChange.serializer()
            "split" -> ExpenseSplitChange.serializer()
            "note" -> ExpenseNoteChange.serializer()
            "occurred_at" -> ExpenseOccurredAtChange.serializer()
            "icon_key" -> ExpenseIconChange.serializer()
            "fx_snapshot" -> ExpenseFxChange.serializer()
            else -> UnknownExpenseChange.serializer()
        }
}

@Serializable
data class ExpenseTitleChange(val after: String? = null, val before: String? = null) : ExpenseChange {
    override val field: String get() = "title"
}

@Serializable
data class ExpenseAmountChange(
    @SerialName("field") val amountField: AmountField,
    val after: String,
    val before: String? = null,
) : ExpenseChange {
    override val field: String get() = amountField.wire
}

@Serializable
data class ExpenseCurrencyChange(val after: String, val before: String? = null) : ExpenseChange {
    override val field: String get() = "original_currency"
}

@Serializable
data class ExpenseLedgerUnitChange(val after: String, val before: String? = null) : ExpenseChange {
    override val field: String get() = "ledger_unit_id"
}

@Serializable
data class ExpensePaymentsChange(
    val after: List<CanonicalPayment>,
    val before: List<CanonicalPayment>? = null,
) : ExpenseChange {
    override val field: String get() = "payment_allocations"
}

@Serializable
data class ExpenseSplitChange(val after: CanonicalSplit, val before: CanonicalSplit? = null) : ExpenseChange {
    override val field: String get() = "split"
}

@Serializable
data class ExpenseNoteChange(val after: String? = null, val before: String? = null) : ExpenseChange {
    override val field: String get() = "note"
}

@Serializable
data class ExpenseOccurredAtChange(val after: String? = null, val before: String? = null) : ExpenseChange {
    override val field: String get() = "occurred_at"
}

@Serializable
data class ExpenseIconChange(val after: String? = null, val before: String? = null) : ExpenseChange {
    override val field: String get() = "icon_key"
}

@Serializable
data class ExpenseFxChange(val after: FxSnapshot? = null, val before: FxSnapshot? = null) : ExpenseChange {
    override val field: String get() = "fx_snapshot"
}

@Serializable
data class UnknownExpenseChange(override val field: String = "") : ExpenseChange

private fun JsonElement.discriminator(key: String): String? =
    ((this as? JsonObject)?.get(key) as? JsonPrimitive)?.contentOrNull
