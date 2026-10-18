"""Machine-readable v1.1 protocol scope over the immutable v1 capability registry."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from . import v1_contracts as v1
from .contracts import canonical_hash


ProtocolOperation = Literal[
    "read.activities",
    "read.expenses",
    "read.debts",
    "expense.create",
    "expense.update",
    "expense.presentation.update",
]


class OperationCoverage(v1.ContractModel):
    operation: ProtocolOperation
    category: Literal["read", "proposal"]
    executable: Literal[False] = False
    external_write_enabled: Literal[False] = False
    required_capability: Literal["CAP01", "CAP07", "CAP08"]


class CapabilityCoverage(v1.ContractModel):
    capability_id: str = Field(pattern=r"^CAP(?:0[1-9]|1[0-7])$")
    inherited_availability: str
    targeted_by_protocol: Literal[True] = True
    operations: list[str] = Field(max_length=6)
    execution_enabled: Literal[False] = False


class ProtocolRegistry(v1.ContractModel):
    api_version: Literal["1.0.0"]
    semantic_version: Literal["1.1.0"]
    operations_version: Literal["1.1.0"]
    trajectory_version: Literal["1.1.0"]
    execution_key_version: Literal["1"]
    operations: list[OperationCoverage] = Field(min_length=6, max_length=6)
    capabilities: list[CapabilityCoverage] = Field(min_length=17, max_length=17)


class DatasetApplicabilityEntry(v1.ContractModel):
    dataset_id: Literal[
        "legacy-v0.1.2-six-classes",
        "legacy-v0.1-scope",
        "diagnostic-111",
        "legacy-t1-393-v1",
        "legacy-t1-release-v2",
        "t1-v1.1-synthetic-contract-examples",
    ]
    disposition: Literal["conversion_candidate", "diagnostic_only", "synthetic_fixture"]
    direct_training_eligible: Literal[False] = False
    explicit_conversion_required: bool
    new_source_freeze_required: bool
    replay_and_human_review_required: bool
    new_split_required: bool


class DatasetApplicabilityPolicy(v1.ContractModel):
    protocol_version: Literal["1.1.0"]
    default_training_eligible: Literal[False] = False
    relabeling_allowed: Literal[False] = False
    entries: list[DatasetApplicabilityEntry] = Field(min_length=6, max_length=6)


def build_protocol_registry() -> ProtocolRegistry:
    v1.validate_capability_registry(v1.CAPABILITY_REGISTRY)
    operations = [
        OperationCoverage(operation="read.activities", category="read", required_capability="CAP01"),
        OperationCoverage(operation="read.expenses", category="read", required_capability="CAP01"),
        OperationCoverage(operation="read.debts", category="read", required_capability="CAP01"),
        OperationCoverage(operation="expense.create", category="proposal", required_capability="CAP07"),
        OperationCoverage(operation="expense.update", category="proposal", required_capability="CAP08"),
        OperationCoverage(operation="expense.presentation.update", category="proposal", required_capability="CAP08"),
    ]
    capabilities = [
        CapabilityCoverage(
            capability_id=item.capability_id,
            inherited_availability=item.availability.value,
            operations=list(item.operations),
        )
        for item in v1.CAPABILITY_REGISTRY
    ]
    registry = ProtocolRegistry(
        api_version="1.0.0",
        semantic_version="1.1.0",
        operations_version="1.1.0",
        trajectory_version="1.1.0",
        execution_key_version="1",
        operations=operations,
        capabilities=capabilities,
    )
    validate_protocol_registry(registry)
    return registry


def validate_protocol_registry(registry: ProtocolRegistry) -> None:
    expected_operations = [
        ("read.activities", "read", "CAP01"),
        ("read.expenses", "read", "CAP01"),
        ("read.debts", "read", "CAP01"),
        ("expense.create", "proposal", "CAP07"),
        ("expense.update", "proposal", "CAP08"),
        ("expense.presentation.update", "proposal", "CAP08"),
    ]
    actual_operations = [
        (item.operation, item.category, item.required_capability)
        for item in registry.operations
    ]
    if actual_operations != expected_operations:
        raise ValueError("the six operation/category/capability mappings are immutable in this profile")
    if any(item.executable or item.external_write_enabled for item in registry.operations):
        raise ValueError("this offline profile has no executable operations or external writes")
    capability_ids = [item.capability_id for item in registry.capabilities]
    if capability_ids != [f"CAP{i:02d}" for i in range(1, 18)]:
        raise ValueError("all unchanged CAP01-CAP17 entries must be represented in stable order")
    inherited = {item.capability_id: item for item in v1.CAPABILITY_REGISTRY}
    for capability in registry.capabilities:
        source = inherited[capability.capability_id]
        if capability.inherited_availability != source.availability.value:
            raise ValueError("CAP availability must exactly inherit the immutable v1 registry")
        if capability.operations != source.operations:
            raise ValueError("CAP operation coverage must exactly inherit the immutable v1 registry")
    if any(item.execution_enabled for item in registry.capabilities):
        raise ValueError("capability coverage cannot activate execution")


def protocol_registry_digest() -> str:
    return canonical_hash(build_protocol_registry())


def build_dataset_applicability_policy() -> DatasetApplicabilityPolicy:
    policy = DatasetApplicabilityPolicy(
        protocol_version="1.1.0",
        entries=[
            DatasetApplicabilityEntry(
                dataset_id="legacy-v0.1.2-six-classes", disposition="conversion_candidate",
                explicit_conversion_required=True, new_source_freeze_required=True,
                replay_and_human_review_required=True, new_split_required=True,
            ),
            DatasetApplicabilityEntry(
                dataset_id="legacy-v0.1-scope", disposition="conversion_candidate",
                explicit_conversion_required=True, new_source_freeze_required=True,
                replay_and_human_review_required=True, new_split_required=True,
            ),
            DatasetApplicabilityEntry(
                dataset_id="diagnostic-111", disposition="diagnostic_only",
                explicit_conversion_required=True, new_source_freeze_required=True,
                replay_and_human_review_required=True, new_split_required=True,
            ),
            DatasetApplicabilityEntry(
                dataset_id="legacy-t1-393-v1", disposition="conversion_candidate",
                explicit_conversion_required=True, new_source_freeze_required=True,
                replay_and_human_review_required=True, new_split_required=True,
            ),
            DatasetApplicabilityEntry(
                dataset_id="legacy-t1-release-v2", disposition="conversion_candidate",
                explicit_conversion_required=True, new_source_freeze_required=True,
                replay_and_human_review_required=True, new_split_required=True,
            ),
            DatasetApplicabilityEntry(
                dataset_id="t1-v1.1-synthetic-contract-examples", disposition="synthetic_fixture",
                explicit_conversion_required=False, new_source_freeze_required=False,
                replay_and_human_review_required=False, new_split_required=False,
            ),
        ],
    )
    validate_dataset_applicability_policy(policy)
    return policy


def validate_dataset_applicability_policy(policy: DatasetApplicabilityPolicy) -> None:
    # Reparse even an existing Pydantic instance: deep/nested mutations must not
    # bypass the validator merely because model_validate(instance) is a no-op.
    payload = policy.model_dump(mode="python") if isinstance(policy, DatasetApplicabilityPolicy) else policy
    policy = DatasetApplicabilityPolicy.model_validate(payload)
    expected = [
        "legacy-v0.1.2-six-classes",
        "legacy-v0.1-scope",
        "diagnostic-111",
        "legacy-t1-393-v1",
        "legacy-t1-release-v2",
        "t1-v1.1-synthetic-contract-examples",
    ]
    if [item.dataset_id for item in policy.entries] != expected:
        raise ValueError("dataset applicability inventory and ordering are fixed for this freeze candidate")
    for entry in policy.entries[:-1]:
        expected_disposition = "diagnostic_only" if entry.dataset_id == "diagnostic-111" else "conversion_candidate"
        if (
            entry.disposition != expected_disposition
            or not entry.explicit_conversion_required
            or not entry.new_source_freeze_required
            or not entry.replay_and_human_review_required
            or not entry.new_split_required
            or entry.direct_training_eligible
        ):
            raise ValueError("legacy datasets require the fixed disposition, explicit conversion, new freeze, replay/review and new split")
    fixture = policy.entries[-1]
    if (
        fixture.disposition != "synthetic_fixture"
        or fixture.direct_training_eligible
        or fixture.explicit_conversion_required
        or fixture.new_source_freeze_required
        or fixture.replay_and_human_review_required
        or fixture.new_split_required
    ):
        raise ValueError("synthetic contract examples are fixtures, never model-training metrics or data")
