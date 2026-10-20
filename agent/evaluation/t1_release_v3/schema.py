"""Build the release-v3 candidate envelope schema.

The v3 envelope is the frozen v2 envelope with exactly three deliberate,
auditable differences:

1. ``release_version`` is ``t1-release-v3`` and the envelope carries the
   negotiated offline v1.1 version tuple plus the canonical profile name.
2. A model step's ``context`` is the frozen offline v1.1 ``ModelContext``
   (which adds typed ``query_observations``) instead of the vendor v1
   context, and its ``target`` is the frozen v1.1 semantic-decision union.
3. A tool-observation step additionally carries the typed query evidence
   observation and its read decision uses the v1.1 shape.

Everything else -- the fixture defs, the dataset-level required fields,
``operation_state``, ``scenario`` and the review/eligibility consts -- is
carried over byte-compatible, so the v3 candidate is the same dataset
described by a newer protocol.

The frozen v1.1 schemas are embedded verbatim (with ``$id``/``$schema``
removed and their internal ``#/$defs/`` pointers re-rooted), so the emitted
schema is self-contained and its own hash pins the protocol it describes.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from . import profile

AGENT_DIR = Path(__file__).resolve().parents[2]  # the agent/ package directory
V2_SCHEMA_PATH = (
    AGENT_DIR / "dataset_contracts" / "t1-release-v2" / "dataset-envelope.schema.json"
)
V3_SCHEMA_PATH = (
    AGENT_DIR / "dataset_contracts" / "t1-release-v3" / "dataset-envelope.schema.json"
)

_MODEL_CONTEXT_SLOT = "v11_model_context"
_SEMANTIC_DECISION_SLOT = "v11_semantic_decision"

# The five negotiated version fields and the exact tuple this profile pins.
VERSION_CONSTANTS = {
    "api": profile.V11_API_VERSION,
    "semantic": profile.V11_SEMANTIC_VERSION,
    "operations": profile.V11_OPERATIONS_VERSION,
    "trajectory": profile.V11_TRAJECTORY_VERSION,
    "execution_key": profile.V11_EXECUTION_KEY_VERSION,
}


# ``splits.base_amount`` / ``payments.base_amount`` are numeric(20,1) in the
# backend, so the wire form carries at most one decimal place.
BASE_AMOUNT_SCHEMA: dict[str, Any] = {
    "title": "Base currency amount (0.1 quantum)",
    "type": "string",
    "pattern": "^-?[0-9]+(?:\\.[0-9])?$",
}


# A no-match read is only acceptable when its typed query evidence binds all
# four RBR01 axes.  Every field below comes from the frozen v1.1 port; none is
# authored by the generator.
RBR01_EVIDENCE_SCHEMA: dict[str, Any] = {
    "title": "RBR01 typed no-match query evidence summary",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "query_ref", "operation", "backend_criteria", "post_filter", "normalized_criteria",
        "returned_count", "matched_count", "source_total", "page_complete", "has_more",
        "truncated", "range_contiguous", "stable_total_verified", "source_version_fenced",
        "unique_items_verified", "source", "source_version", "schema_version",
        "context_version", "zero_class",
    ],
    "properties": {
        "query_ref": {"type": "string", "pattern": "^query_[0-9]{1,2}$"},
        "operation": {"type": "string", "pattern": "^read\\."},
        "backend_criteria": {"type": "object"},
        "post_filter": {"type": "object"},
        "normalized_criteria": {"type": "string", "minLength": 2},
        "returned_count": {"type": "integer", "minimum": 0},
        "matched_count": {"const": 0},
        "source_total": {"type": "integer", "minimum": 0},
        "page_complete": {"const": True},
        "has_more": {"const": False},
        "truncated": {"const": False},
        "range_contiguous": {"const": True},
        "stable_total_verified": {"const": True},
        "source_version_fenced": {"const": True},
        "unique_items_verified": {"const": True},
        "source": {"const": "synthetic_simulation"},
        "source_version": {"type": "string", "minLength": 1},
        "schema_version": {"const": profile.V11_QUERY_EVIDENCE_SCHEMA_VERSION},
        "context_version": {"type": "integer", "minimum": 1},
        "zero_class": {"enum": ["backend_zero", "post_filter_zero"]},
    },
}


def _frozen_v11_schema(name: str) -> dict[str, Any]:
    """Load one frozen v1.1 exported schema and re-root it for embedding."""
    root = AGENT_DIR / profile.V11_SCHEMA_DIR_RELATIVE
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f"frozen v1.1 schema is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _reroot_refs(value: Any, slot: str) -> Any:
    """Rewrite ``#/$defs/X`` to ``#/$defs/<slot>/$defs/X`` throughout."""
    if isinstance(value, dict):
        return {
            key: (
                f"#/$defs/{slot}/$defs/{item[len('#/$defs/'):]}"
                if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/")
                else _reroot_refs(item, slot)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_reroot_refs(item, slot) for item in value]
    return value


def _embed(schema: dict[str, Any], slot: str) -> dict[str, Any]:
    embedded = copy.deepcopy(schema)
    # A nested $id would rebase the internal JSON pointers; drop both
    # annotations so the pointers resolve against the envelope root.
    embedded.pop("$id", None)
    embedded.pop("$schema", None)
    return _reroot_refs(embedded, slot)


def build_v3_envelope_schema() -> dict[str, Any]:
    v2 = json.loads(V2_SCHEMA_PATH.read_text(encoding="utf-8"))
    envelope = copy.deepcopy(v2)

    envelope["title"] = "Shared Ledger Agent T1 release v3 candidate envelope"
    envelope["$comment"] = (
        "Derived from the frozen t1-release-v2 envelope schema by an explicit, "
        "reviewable conversion to the frozen offline protocol v1.1.0. The v2 "
        "envelope and its receipts are not modified."
    )

    props = envelope["properties"]
    props["release_version"]["const"] = profile.RELEASE_VERSION
    props["protocol_profile"] = {
        "const": profile.V11_PROFILE,
        "title": "Protocol Profile",
        "type": "string",
    }
    props["versions"] = {
        "title": "Negotiated Versions",
        "type": "object",
        "additionalProperties": False,
        "required": list(VERSION_CONSTANTS),
        "properties": {
            field: {"const": value, "type": "string"}
            for field, value in VERSION_CONSTANTS.items()
        },
    }
    for field in ("protocol_profile", "versions"):
        if field not in envelope["required"]:
            envelope["required"].append(field)

    defs = envelope["$defs"]
    defs[_MODEL_CONTEXT_SLOT] = _embed(_frozen_v11_schema("model-context.schema.json"), _MODEL_CONTEXT_SLOT)
    defs[_SEMANTIC_DECISION_SLOT] = _embed(
        _frozen_v11_schema("semantic-decision.schema.json"), _SEMANTIC_DECISION_SLOT
    )
    defs["rbr01_query_evidence"] = RBR01_EVIDENCE_SCHEMA

    # A no-match read records the typed query evidence that closes RBR01.
    # Non-empty rows simply omit the field.
    for branch in envelope["properties"]["scenario"]["oneOf"]:
        branch["properties"]["query_evidence"] = {"$ref": "#/$defs/rbr01_query_evidence"}

    # A release-v3 row may carry the persisted base-currency column next to the
    # original-currency one.  They are different columns with different quanta
    # (0.1 vs 0.0001), so both are modelled; base_amount stays optional.
    state_expense = envelope["properties"]["operation_state"]["properties"]["expenses"]["items"]
    state_expense["properties"]["base_amount"] = BASE_AMOUNT_SCHEMA
    for bucket in ("payments", "splits"):
        state_expense["properties"][bucket]["items"]["properties"]["base_amount"] = (
            BASE_AMOUNT_SCHEMA
        )

    model_step = defs["model_step"]["properties"]
    model_step["context"] = {"$ref": f"#/$defs/{_MODEL_CONTEXT_SLOT}"}
    model_step["target"] = {"$ref": f"#/$defs/{_SEMANTIC_DECISION_SLOT}"}

    tool_step = defs["tool_result_step"]
    # A tool observation carries the typed query evidence when the row's
    # scenario declares it (the no-match read rows); the auxiliary read that
    # precedes a write proposal carries none, exactly as under the frozen v1.1
    # trajectory format.
    tool_step["properties"]["query"] = {
        "$ref": f"#/$defs/{_MODEL_CONTEXT_SLOT}/$defs/QueryEvidenceObservation"
    }
    tool_step["properties"]["request"] = {
        "$ref": f"#/$defs/{_SEMANTIC_DECISION_SLOT}/$defs/ReadDecision"
    }

    return envelope


def write_v3_envelope_schema(path: Path | None = None) -> Path:
    target = path or V3_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_v3_envelope_schema(), ensure_ascii=False, indent=2, sort_keys=True)
    target.write_text(payload + "\n", encoding="utf-8")
    return target


def load_v3_envelope_schema() -> dict[str, Any]:
    if not V3_SCHEMA_PATH.is_file():
        raise FileNotFoundError(
            f"release-v3 envelope schema is not generated yet: {V3_SCHEMA_PATH}"
        )
    return json.loads(V3_SCHEMA_PATH.read_text(encoding="utf-8"))
