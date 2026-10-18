"""Default dependency graph for the service skeleton."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from urllib.parse import urlsplit

from .backend import MockBackendAdapter, MockScopeAuthorizer, UnimplementedBackendAdapter
from .gateway import UnimplementedGateway
from .model_provider import DisabledModelProvider
from .auth import SupabaseAuthVerifier
from .contracts import ProposalRecord, ResumeProposalAdjustRequest, TurnId, UserId
from .ports import (
    AgentControl, AgentControlSnapshot, AgentStore, AuthVerifier, BackendAdapter,
    CapabilityUnavailable, Gateway, ModelProvider, Principal, ProposalAdjustmentPreparer,
    Runtime, ScopeAuthorizer, ScopeUnavailable,
)
from .runtime import MockRuntime, UnimplementedRuntime
from .settings import Settings
from .p2_backend import P2BackendAdapter, P2BackendConfig
from .p2_journal import P2ErrorProofJournal
from .p2_model_provider import LMStudioOpenAIConfig, LMStudioOpenAIProvider
from .p2_local_endpoint import parse_local_p2_endpoint
from .p2_token_budget import (
    LMStudioSDKTokenBudgetChecker, P2ModelArtifactBinding, P2TokenBudgetPolicy,
)
from .p2_runtime import P2Runtime
from .store import SQLiteAgentStore
from .harness import MockModelProvider
from .p2_read_contracts import P2_CANDIDATE_PROFILE_ID
from .p2_read_contracts_v3 import P2_V3_CANDIDATE_PROFILE_ID
from .p2_read_backend import P2ReadBackendAdapter


class _CandidateProfileStore:
    """Assign one server-selected candidate to new submits; delegate all Store IO."""

    def __init__(self, store: SQLiteAgentStore, profile_id: str) -> None:
        self._store = store
        self._profile_id = profile_id

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def submit_turn(self, *args, candidate_profile_id: str | None = None, **kwargs):
        if candidate_profile_id not in (None, self._profile_id):
            raise ValueError("candidate profile is selected by server configuration")
        return self._store.submit_turn(
            *args, candidate_profile_id=self._profile_id, **kwargs,
        )


@dataclass(frozen=True)
class AppComponents:
    store: AgentStore
    provider: ModelProvider
    backend: BackendAdapter
    runtime: Runtime
    gateway: Gateway
    auth_verifier: AuthVerifier | None = None
    scope_authorizer: ScopeAuthorizer | None = None
    agent_control: AgentControl | None = None
    proposal_adjustment_preparer: ProposalAdjustmentPreparer | None = None


@dataclass(frozen=True)
class _ConfiguredAgentControl:
    """Static server config; operators must advance and retain the revision."""

    enabled: bool
    disable_revision: int

    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(
            enabled=self.enabled,
            disable_revision=self.disable_revision,
            source="server_config",
        )


class _FailClosedScopeAuthorizer:
    """P2 business permission adapter is not installed; never infer access from UI data."""

    def authorize(self, principal: Principal, activity_ids: frozenset[uuid.UUID], *, action: str) -> None:
        if activity_ids:
            raise ScopeUnavailable("authoritative activity scope checks are unavailable")


class _UnavailableProposalAdjustmentPreparer:
    def prepare(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        proposal: ProposalRecord,
        request: ResumeProposalAdjustRequest,
    ) -> ProposalRecord:
        raise CapabilityUnavailable("trusted proposal adjustment preparation is not available")


def build_components(settings: Settings) -> AppComponents:
    """Construct objects only; resource acquisition happens in lifespan."""
    v3_store_args = {}
    if settings.p2_v3_candidate_enabled:
        v3_store_args = {
            "p2_v3_execution_manifest_path": settings.p2_v3_execution_manifest_path,
            "p2_v3_execution_manifest_sha256": settings.p2_v3_execution_manifest_sha256,
            "p2_v3_execution_repository_root": settings.p2_v3_execution_repository_root,
            "p2_v3_execution_external_component_roots": settings.p2_v3_execution_external_component_roots,
        }
    store = SQLiteAgentStore(settings.storage_path, admission_enabled=True, **v3_store_args)
    if settings.p2_v3_candidate_enabled:
        _verify_v3_provider_wire_pin(settings, store)
    submit_store = (
        _CandidateProfileStore(store, P2_V3_CANDIDATE_PROFILE_ID)
        if settings.p2_v3_candidate_enabled else store
    )
    verifier = SupabaseAuthVerifier.from_settings(settings)
    control = _ConfiguredAgentControl(settings.agent_enabled, settings.disable_revision)
    if settings.provider_mode == "mock":
        provider = MockModelProvider()
        backend = MockBackendAdapter()
        scope = MockScopeAuthorizer()
        runtime = MockRuntime(
            store, provider, backend, verifier, scope, control,
            task_concurrency=settings.runtime_task_concurrency,
            model_timeout_seconds=settings.mock_model_timeout_seconds,
            shutdown_timeout_seconds=settings.runtime_shutdown_timeout_seconds,
        )
    elif settings.provider_mode == "p2":
        assert settings.supabase_auth_base_url is not None
        assert settings.supabase_api_key is not None
        parsed = urlsplit(settings.supabase_auth_base_url)
        project_url = parsed._replace(path="", query="", fragment="").geturl().rstrip("/")
        token_budget_checker = None
        if settings.p2_token_budget_enabled:
            # This binds to a frozen artifact already selected by the operator.
            # It never loads a model; the checker only measures requests against
            # the currently loaded exact model and fails closed on any mismatch.
            assert settings.p2_model_artifact_path is not None
            assert settings.p2_lmstudio_model_path is not None
            assert settings.p2_model_artifact_sha256 is not None
            assert settings.p2_model_artifact_size_bytes is not None
            assert settings.p2_token_counter_python is not None
            api_host = parse_local_p2_endpoint(settings.p2_lmstudio_endpoint_url).origin
            binding = P2ModelArtifactBinding(
                model_key=settings.p2_lmstudio_model_key,
                artifact_path=settings.p2_model_artifact_path,
                lmstudio_model_path=settings.p2_lmstudio_model_path,
                lmstudio_api_host=api_host,
                artifact_sha256=settings.p2_model_artifact_sha256,
                artifact_size_bytes=settings.p2_model_artifact_size_bytes,
                expected_context_tokens=settings.p2_model_context_tokens,
            )
            policy = P2TokenBudgetPolicy(
                actual_context_tokens=settings.p2_model_context_tokens,
                max_input_tokens=settings.p2_max_input_tokens,
                max_output_tokens=settings.p2_max_output_tokens,
                schema_safety_margin_tokens=settings.p2_schema_safety_margin_tokens,
                sdk_call_timeout_seconds=settings.p2_token_counter_deadline_seconds,
                artifact_hash_timeout_seconds=settings.p2_token_counter_deadline_seconds,
            )
            token_budget_checker = LMStudioSDKTokenBudgetChecker(
                binding, policy, python_executable=settings.p2_token_counter_python,
                child_timeout_seconds=settings.p2_token_counter_deadline_seconds,
            )
        provider = LMStudioOpenAIProvider(LMStudioOpenAIConfig(
            model_key=settings.p2_lmstudio_model_key,
            enabled=settings.p2_lmstudio_enabled,
            endpoint_url=settings.p2_lmstudio_endpoint_url,
            request_timeout_seconds=settings.p2_model_timeout_seconds,
            max_output_tokens=settings.p2_max_output_tokens,
            max_prompt_bytes=settings.p2_max_prompt_bytes,
            max_request_bytes=settings.p2_max_request_bytes,
            max_response_bytes=settings.p2_max_response_bytes,
            max_content_bytes=settings.p2_max_content_bytes,
            api_token=settings.p2_lmstudio_api_token.get_secret_value()
            if settings.p2_lmstudio_api_token is not None else None,
        ), token_budget_checker=token_budget_checker)
        backend_config = P2BackendConfig(
            project_url=project_url,
            publishable_key=settings.supabase_api_key.get_secret_value(),
        )
        backend = P2BackendAdapter(backend_config)
        v3_backend_config = None
        if settings.p2_v3_candidate_enabled:
            # V3's immutable candidate fixes physical source pages at 16 rows,
            # four pages per table, 64 rows per query. Keep the canonical P2
            # adapter's existing page configuration untouched.
            v3_backend_config = P2BackendConfig(
                project_url=project_url,
                publishable_key=settings.supabase_api_key.get_secret_value(),
                page_size=16,
                max_pages=4,
                max_rows_per_query=64,
                max_requests_per_read=48,
                max_total_response_bytes=4_194_304,
                max_total_seconds=20.0,
                max_facts=16,
            )
        scope = _FailClosedScopeAuthorizer()
        journal_path = settings.p2_journal_path or settings.storage_path.with_suffix(".p2journal.sqlite3")
        journal = P2ErrorProofJournal(journal_path, max_entries=settings.p2_turn_grant_max_entries * 4)
        v3_provider = None
        v3_prompt_config = None
        if settings.p2_v3_candidate_enabled:
            from .p2_read_prompt_v3 import P2V3PromptBuildConfig

            v3_prompt_config = P2V3PromptBuildConfig(
                model_id=settings.p2_lmstudio_model_key,
                endpoint_url=settings.p2_lmstudio_endpoint_url,
                max_output_tokens=settings.p2_max_output_tokens,
            )
            if settings.p2_v3_native_candidate_enabled:
                from .p2_read_native_provider_v3 import P2V3NativeCandidateReadProvider

                v3_provider = P2V3NativeCandidateReadProvider(provider, config=v3_prompt_config)
            else:
                from .p2_read_provider_v3 import P2V3ReadProvider

                v3_provider = P2V3ReadProvider(provider, config=v3_prompt_config)
        runtime = P2Runtime(
            store, provider, backend, verifier, control, journal,
            lease_seconds=settings.p2_turn_grant_lease_seconds,
            # Let token counting and the provider's bounded HTTP timeout surface
            # before Runtime cancels its worker at the outer deadline.
            model_timeout_seconds=(
                settings.p2_model_timeout_seconds
                + settings.p2_token_counter_deadline_seconds
                + (10.0 if settings.p2_v3_native_candidate_enabled else 1.0)
            ),
            shutdown_timeout_seconds=settings.runtime_shutdown_timeout_seconds,
            max_model_calls=settings.p2_max_model_calls,
            max_read_calls=settings.p2_max_read_calls,
            max_repair_calls=settings.p2_max_repair_calls,
            max_turn_grants=settings.p2_turn_grant_max_entries,
            v3_provider=v3_provider,
            v3_prompt_config=v3_prompt_config,
            v3_backend_config=v3_backend_config,
            enabled_candidate_profile_ids=(
                (P2_CANDIDATE_PROFILE_ID, P2_V3_CANDIDATE_PROFILE_ID)
                if settings.p2_v3_candidate_enabled else None
            ),
        )
    else:
        provider = DisabledModelProvider()
        backend = UnimplementedBackendAdapter()
        scope = _FailClosedScopeAuthorizer()
        runtime = UnimplementedRuntime()
    return AppComponents(
        store=submit_store,
        provider=provider,
        backend=backend,
        runtime=runtime,
        gateway=UnimplementedGateway(),
        auth_verifier=verifier,
        scope_authorizer=scope,
        agent_control=control,
        proposal_adjustment_preparer=_UnavailableProposalAdjustmentPreparer(),
    )


def _verify_v3_provider_wire_pin(settings: Settings, store: Any) -> None:
    """Require the independently verified manifest to pin the exact selected wire/config."""
    from .p2_v3_execution_cohort import is_verified_execution_cohort
    from .p2_local_endpoint import parse_local_p2_endpoint

    cohort = getattr(store, "_p2_v3_execution_cohort", None)
    if not is_verified_execution_cohort(cohort):
        raise ValueError("P2 v3 provider selection requires a verified execution-cohort pin")
    selected_wire = "native_candidate" if settings.p2_v3_native_candidate_enabled else "compatibility"
    if (
        cohort.provider_wire != selected_wire
        or cohort.model_key != settings.p2_lmstudio_model_key
        or cohort.endpoint_origin != parse_local_p2_endpoint(settings.p2_lmstudio_endpoint_url).origin
        or cohort.http_timeout_seconds != float(settings.p2_model_timeout_seconds)
        or cohort.max_output_tokens != settings.p2_max_output_tokens
    ):
        raise ValueError("P2 v3 provider wire/model/origin/timeout/output differs from the execution manifest pin")
