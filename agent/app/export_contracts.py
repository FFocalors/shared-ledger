"""Deterministically export the P1-01 protocol contract snapshot.

Usage from repository root:
    python -m agent.app.export_contracts
    python -m agent.app.export_contracts --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import contracts as c
from .mock_fixtures import build_mock_fixtures, fixture_json_bytes


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "contracts" / f"v{c.API_VERSION}"
MANIFEST_NAME = "manifest.json"


def _json_bytes(document: Any) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _replace_refs(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                result[key] = item.replace("#/$defs/", "#/components/schemas/")
            elif key == "mapping" and isinstance(item, dict):
                result[key] = {
                    map_key: map_value.replace("#/$defs/", "#/components/schemas/")
                    if isinstance(map_value, str)
                    else _replace_refs(map_value)
                    for map_key, map_value in item.items()
                }
            else:
                result[key] = _replace_refs(item)
        return result
    if isinstance(value, list):
        return [_replace_refs(item) for item in value]
    return value


def _openapi() -> dict[str, Any]:
    components: dict[str, Any] = {}
    for model in c.schema_catalog():
        schema = model.model_json_schema(mode="validation")
        definitions = schema.pop("$defs", {})
        for name, item in definitions.items():
            candidate = _replace_refs(item)
            existing = components.get(name)
            if existing is not None and _json_bytes(existing) != _json_bytes(candidate):
                raise ValueError(f"conflicting OpenAPI component schema name: {name}")
            components[name] = candidate
        name = model.__name__
        root = _replace_refs(schema)
        existing = components.get(name)
        if existing is not None and _json_bytes(existing) != _json_bytes(root):
            raise ValueError(f"root schema conflicts with nested component name: {name}")
        components[name] = root

    def body(name: str) -> dict[str, Any]:
        return {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{name}"}}},
        }

    def response(name: str, description: str = "Validated JSON response") -> dict[str, Any]:
        return {
            "description": description,
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{name}"}}},
        }

    def operation(
        operation_id: str,
        *,
        request: str | None,
        success: str,
        path_params: list[str] | None = None,
        query_params: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        path_params = path_params or []
        responses: dict[str, Any] = {
            "400": response("ApiErrorResponse", "Invalid request"),
            "401": response("ApiErrorResponse", "Authorization required"),
            "403": response("ApiErrorResponse", "Authenticated owner lacks access"),
            "404": response("ApiErrorResponse", "Resource not found"),
            "409": response("ApiErrorResponse", "Revision or idempotency conflict"),
            "422": response("ApiErrorResponse", "Contract validation error"),
            "429": response("ApiErrorResponse", "Rate limited"),
            "503": response("ApiErrorResponse", "Dependency unavailable"),
        }
        if operation_id != "confirmProposal":
            success_status = "201" if operation_id == "createSession" else (
                "200" if request is None else "202"
            )
            responses[success_status] = response(success)
        else:
            responses["501"] = response(
                "ConfirmationUnavailableResponse",
                "Confirmation capability is deliberately disabled in P1-01",
            )
        item: dict[str, Any] = {
            "operationId": operation_id,
            "security": [{"BearerAuth": []}],
            "responses": responses,
        }
        if request:
            item["requestBody"] = body(request)
        if path_params:
            item["parameters"] = [
                {
                    "name": param,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                }
                for param in path_params
            ]
        if query_params:
            item.setdefault("parameters", []).extend(query_params)
        return item

    paths = {
        "/v1/sessions": {
            "get": operation(
                "listSessions",
                request=None,
                success="ListSessionsResponse",
                query_params=[
                    {"name": "cursor", "in": "query", "required": False, "schema": {"type": "string", "maxLength": 240}},
                    {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}},
                ],
            ),
            "post": operation("createSession", request="CreateSessionRequest", success="CreateSessionResponse"),
        },
        "/v1/sessions/{session_id}": {
            "get": operation("getSession", request=None, success="SessionDetailResponse", path_params=["session_id"]),
        },
        "/v1/sessions/{session_id}/turns": {
            "post": operation("submitTurn", request="SubmitTurnRequest", success="SubmitTurnAccepted", path_params=["session_id"]),
        },
        "/v1/turns/{turn_id}/events": {
            "get": operation(
                "pollTurnEvents",
                request=None,
                success="PollEventsResponse",
                path_params=["turn_id"],
                query_params=[
                    {"name": "after_seq", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 0, "default": 0}},
                    {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}},
                ],
            ),
        },
        "/v1/turns/{turn_id}/resume/clarification": {
            "post": operation("resumeClarification", request="ResumeClarificationRequest", success="TurnMutationAccepted", path_params=["turn_id"]),
        },
        "/v1/turns/{turn_id}/resume/auth": {
            "post": operation("resumeAuth", request="ResumeAuthRequest", success="TurnMutationAccepted", path_params=["turn_id"]),
        },
        "/v1/turns/{turn_id}/resume/proposal-adjust": {
            "post": operation("adjustProposal", request="ResumeProposalAdjustRequest", success="ProposalAdjustedAccepted", path_params=["turn_id"]),
        },
        "/v1/turns/{turn_id}/cancel": {
            "post": operation("cancelTurn", request="CancelTurnRequest", success="CancelTurnResponse", path_params=["turn_id"]),
        },
        "/v1/proposals/{proposal_id}/confirm": {
            "post": operation("confirmProposal", request="ConfirmProposalRequest", success="ConfirmationUnavailableResponse", path_params=["proposal_id"]),
        },
    }
    document = {
        "openapi": "3.1.0",
        "info": {
            "title": "Shared Ledger Agent Protocol",
            "version": c.API_VERSION,
            "description": (
                "Offline API contract snapshot. Authorization identity is server-derived. "
                "No service implementation or live security behavior is implied."
            ),
            "x-semantic-version": c.SEMANTIC_VERSION,
            "x-operations-version": c.OPERATIONS_VERSION,
            "x-trajectory-version": c.TRAJECTORY_VERSION,
        },
        "servers": [{"url": "https://api.invalid", "description": "Placeholder; no endpoint is deployed by this contract freeze."}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            },
            "schemas": components,
        },
    }
    _validate_openapi_references(document)
    return document


def _validate_openapi_references(document: dict[str, Any]) -> None:
    def resolve(pointer: str) -> Any:
        if not pointer.startswith("#/"):
            raise ValueError(f"OpenAPI reference must be an internal JSON Pointer: {pointer}")
        current: Any = document
        for encoded in pointer[2:].split("/"):
            token = encoded.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                raise ValueError(f"unresolved OpenAPI JSON Pointer: {pointer}")
        return current

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                resolve(reference)
            mapping = value.get("mapping")
            if isinstance(mapping, dict):
                for target in mapping.values():
                    if isinstance(target, str):
                        resolve(target)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)


def build_artifacts() -> dict[str, bytes]:
    artifacts: dict[str, bytes] = {}
    for model in c.schema_catalog():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        artifacts[f"schemas/{model.__name__}.schema.json"] = _json_bytes(schema)
    artifacts["openapi.json"] = _json_bytes(_openapi())
    artifacts["capability-registry.json"] = _json_bytes(
        [entry.model_dump(mode="json") for entry in c.CAPABILITY_REGISTRY]
    )
    artifacts["state-transitions.json"] = _json_bytes(c.STATE_TRANSITIONS)
    artifacts["validation-layers.json"] = _json_bytes(
        {
            "structural": {
                "schema_draft": "JSON Schema Draft 2020-12",
                "checks": [
                    "wire types, required fields, strict lexical patterns, lengths/ranges, enums, discriminators, and unknown-field rejection",
                    "JSON Schema alone does not enforce Decimal conservation, state-machine transition identity, current authorization, or transaction/CAS behavior",
                ],
            },
            "deterministic_cross_field": {
                "pydantic_source_validators": [
                    "money and allocation conservation, operation-to-intent matching, local semantic citation/type consistency, state snapshot invariants, nonce visibility by card state, typed preview snapshot/change equality, and request receipt ownership/response kinds",
                    "trajectory chronology and proposal/card/confirm fixture identity checks",
                ],
                "offline_harness_helpers": [
                    "current-context grounding and permission/scope checks",
                    "persisted Turn entity/evidence/read-result binding checks",
                    "financial lock checks, idempotency conflict checks, proposal revision preconditions, and deterministic execution identity derivation",
                ],
                "service_obligation": "P1-02 must invoke these helpers only after current Authorization verification and inside the specified persistence transaction; this source batch does not prove that integration.",
            },
            "trajectory": "Each mock trace is run through Draft 2020-12 structural validation and then the same Pydantic MockTrajectory type and deterministic cross-field validators used by the source contracts.",
            "runtime": "No running service, Authorization verifier, database, deployed Harness, RPC, real model, or API security acceptance is implemented or tested by this snapshot.",
        }
    )
    for name, fixture in sorted(build_mock_fixtures().items()):
        artifacts[f"mock_traces/{name}.json"] = fixture_json_bytes(fixture)
    return artifacts


def _source_fingerprints() -> dict[str, str]:
    paths = [
        ROOT / "app" / "contracts.py",
        ROOT / "app" / "export_contracts.py",
        ROOT / "app" / "mock_fixtures.py",
        ROOT / "requirements-contracts.txt",
        ROOT / "toolchain-contracts.json",
    ]
    fingerprints: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"manifest source fingerprint missing: {path}")
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        normalized = text.encode("utf-8")
        fingerprints[path.relative_to(ROOT).as_posix()] = hashlib.sha256(normalized).hexdigest()
    return fingerprints


def _manifest_for(artifacts: dict[str, bytes]) -> bytes:
    manifest = {
        "manifest_version": 1,
        "api_version": c.API_VERSION,
        "semantic_version": c.SEMANTIC_VERSION,
        "operations_version": c.OPERATIONS_VERSION,
        "trajectory_version": c.TRAJECTORY_VERSION,
        "hash_algorithm": "SHA-256",
        "normalization": {
            "generated_files": "UTF-8 JSON; sorted keys; two-space indentation; one final LF; hash exact emitted bytes",
            "source_files": "UTF-8 text; normalize CRLF and lone CR to LF; hash normalized bytes",
        },
        "source_fingerprints": _source_fingerprints(),
        "generated_files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(artifacts.items())},
        "self_hash": None,
    }
    return _json_bytes(manifest)


def write_snapshot() -> None:
    artifacts = build_artifacts()
    artifacts[MANIFEST_NAME] = _manifest_for(artifacts)
    for relative, data in sorted(artifacts.items()):
        destination = OUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def check_snapshot() -> list[str]:
    expected = build_artifacts()
    expected[MANIFEST_NAME] = _manifest_for(expected)
    failures: list[str] = []
    for relative, data in sorted(expected.items()):
        path = OUT / relative
        if not path.is_file():
            failures.append(f"missing: {relative}")
        elif path.read_bytes() != data:
            failures.append(f"drift: {relative}")
    if OUT.exists():
        expected_names = set(expected)
        for path in OUT.rglob("*"):
            if path.is_file():
                relative = path.relative_to(OUT).as_posix()
                if relative not in expected_names:
                    failures.append(f"unexpected: {relative}")
    manifest_path = OUT / MANIFEST_NAME
    if manifest_path.is_file():
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, digest in stored.get("generated_files", {}).items():
            path = OUT / relative
            if not path.is_file():
                failures.append(f"manifest missing target: {relative}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                failures.append(f"hash mismatch: {relative}")
        if stored.get("self_hash") is not None:
            failures.append("manifest self_hash must remain null to avoid a self-hash cycle")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="fail if generated snapshots or manifest drift")
    group.add_argument("--write", action="store_true", help="write deterministic snapshots (default)")
    args = parser.parse_args(argv)
    if args.check:
        failures = check_snapshot()
        if failures:
            print("contract snapshot drift:", file=sys.stderr)
            for failure in failures:
                print(f"- {failure}", file=sys.stderr)
            return 1
        print(f"contract snapshot matches manifest: {OUT}")
        return 0
    write_snapshot()
    print(f"wrote deterministic contract snapshot: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
