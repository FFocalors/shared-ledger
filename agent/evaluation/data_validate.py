"""Offline validators for frozen synthetic T1 sample envelopes.

The CLI deliberately denies `sealed` paths. The generator uses the in-memory API
before writing each split; this module never prints sample bodies.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from jsonschema import Draft202012Validator, RefResolver

AGENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.app import contracts as c
from agent.app.harness import parse_model_output
from agent.evaluation.data_signature import canonical_json, fixture_projection, scenario_projection
from agent.evaluation.data_simulator import SIMULATOR_VERSION, simulate_read


class DatasetValidationError(ValueError):
    pass


def _file_handler(uri: str) -> Any:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise DatasetValidationError("external schema references must resolve to local files")
    raw_path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", raw_path):
        raw_path = raw_path[1:]
    path = Path(raw_path)
    if not path.is_file():
        raise DatasetValidationError("referenced schema file is missing")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def make_envelope_validator(agent_root: Path) -> Draft202012Validator:
    schema_path = (agent_root / "dataset_contracts/t1/dataset-envelope.schema.json").resolve()
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    Draft202012Validator.check_schema(schema)
    resolver = RefResolver(
        base_uri=schema_path.as_uri(),
        referrer=schema,
        handlers={"file": _file_handler},
    )
    return Draft202012Validator(schema, resolver=resolver)


def _serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _model_read_result(result: c.ToolReadResult) -> c.ModelReadResult:
    return c.ModelReadResult(
        result_ref=result.result_ref,
        operation=result.operation,
        observed_at=result.observed_at,
        context_version=result.context_version,
        simulation=result.simulation,
        body=result.body,
    )


def validate_record(record: dict[str, Any], validator: Draft202012Validator) -> dict[str, Any]:
    """Validate envelope, contexts, decisions, and replay from fixture input."""
    validator.validate(record)
    if record["replay_status"] != "simulated" or record["data_origin"] != "synthetic":
        raise DatasetValidationError("T1 synthetic replay must stay simulated")
    fixture_bytes = canonical_json(record["fixture_state"])
    if hashlib.sha256(fixture_bytes).hexdigest() != record["fixture_state_sha256"]:
        raise DatasetValidationError("fixture state hash does not match the explicit fixture")
    signature = hashlib.sha256(canonical_json(fixture_projection(record["fixture_state"]))).hexdigest()
    if signature != record["normalized_state_signature_sha256"]:
        raise DatasetValidationError("normalized state signature does not match its projection")
    scenario_signature = hashlib.sha256(canonical_json(scenario_projection(record["fixture_state"], record))).hexdigest()
    if scenario_signature != record["normalized_scenario_signature_sha256"]:
        raise DatasetValidationError("normalized scenario signature does not match its projection")

    simulator_path = AGENT_ROOT / "evaluation/data_simulator.py"
    simulator_sha256 = hashlib.sha256(simulator_path.read_bytes()).hexdigest()
    parsed_steps: list[tuple[int, c.ModelContext, c.SemanticDecision]] = []
    tool_steps: list[tuple[int, c.ToolReadResult, dict[str, Any]]] = []
    for index, step in enumerate(record["trace"]):
        if step["kind"] == "model":
            context = c.ModelContext.model_validate(step["context"])
            parsed = parse_model_output(_serialized(step["target"]), context)
            parsed_steps.append((index, context, parsed))
        elif step["kind"] == "tool_result":
            if step["producer"] != "deterministic_synthetic_fixture":
                raise DatasetValidationError("tool result source must be a deterministic synthetic fixture")
            if step["fixture_state"] != record["fixture_state"]:
                raise DatasetValidationError("tool step fixture differs from the hash-bound record fixture")
            if step["simulator_version"] != SIMULATOR_VERSION or step["simulator_sha256"] != simulator_sha256:
                raise DatasetValidationError("tool replay simulator version/hash does not match the frozen runner")
            supplied = c.ToolReadResult.model_validate_json(_serialized(step["result"]))
            request = c.ReadDecision.model_validate(step["request"])
            replayed = simulate_read(
                step["fixture_state"],
                request,
                observed_at=step["observed_at"],
                context_version=step["context_version"],
                replay_key=step["replay_key"],
            )
            if supplied.model_dump(mode="json") != replayed.model_dump(mode="json"):
                raise DatasetValidationError("saved tool result differs from deterministic fixture replay")
            tool_steps.append((index, supplied, step))

    if not parsed_steps:
        raise DatasetValidationError("trajectory must include a model step")
    for index, _, decision in parsed_steps:
        if isinstance(decision, c.ReadDecision):
            following = next(((j, r, raw) for j, r, raw in tool_steps if j > index), None)
            if following is None or following[1].operation != decision.operation:
                raise DatasetValidationError("read decision lacks a matching deterministic result")
            if following[2]["request"] != decision.model_dump(mode="json"):
                raise DatasetValidationError("tool simulator request differs from preceding model decision")

    for index, result, _ in tool_steps:
        downstream = [context for j, context, _ in parsed_steps if j > index]
        expected_model_result = _model_read_result(result).model_dump(mode="json")
        linked = any(
            any(model_result.model_dump(mode="json") == expected_model_result for model_result in context.read_results)
            for context in downstream
        )
        if not linked:
            raise DatasetValidationError("deterministic tool result is not consumed by a later model context")

    final = parsed_steps[-1][2]
    expected = record["expected"]
    if final.kind != expected["semantic"]:
        raise DatasetValidationError("final semantic kind differs from frozen expectation")
    final_operation = getattr(final, "operation", None)
    final_operation_value = final_operation.value if hasattr(final_operation, "value") else final_operation
    if final_operation_value != expected["operation"]:
        raise DatasetValidationError("final operation differs from frozen expectation")
    if expected["must_complete"]:
        task_operation = expected["task_operation"]
        if task_operation is None:
            raise DatasetValidationError("complete task must name its registered task_operation")
        selected = [d for _, _, d in parsed_steps if isinstance(d, (c.ReadDecision, c.ProposeDecision))]
        if not selected or getattr(selected[-1].operation, "value", selected[-1].operation) != task_operation:
            raise DatasetValidationError("selected operation differs from task_operation")

    return {
        "sample_id": record["sample_id"],
        "split": record["split"],
        "case_type": record["case_type"],
        "task_operation": expected["task_operation"],
        "model_steps": len(parsed_steps),
        "tool_results": len(tool_steps),
    }


def _canonical_bundle(split: str, run_root: Path) -> Path:
    return (run_root / "data" / f"{split}.jsonl").resolve()


def validate_jsonl(path: Path, *, expected_split: str, agent_root: Path) -> dict[str, Any]:
    """Validate train or root-approved validation; deny sealed before opening any bundle."""
    if expected_split == "sealed":
        raise DatasetValidationError("sealed bundle access is denied by this CLI")
    if expected_split not in {"train", "validation"}:
        raise DatasetValidationError("unsupported split")
    resolved = path.resolve()
    if resolved.name.casefold() == "sealed.jsonl" or any(part.casefold() == "sealed" for part in resolved.parts):
        raise DatasetValidationError("sealed path is denied before file access")
    run_root = Path(r"D:\AI\runs\shared-ledger\t1")
    manifest_path = run_root / "freeze-manifest.json"
    if not manifest_path.is_file():
        raise DatasetValidationError("frozen dataset manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    canonical = _canonical_bundle(expected_split, run_root)
    if resolved != canonical:
        raise DatasetValidationError("only the canonical bundle path declared by the T1 manifest is accepted")
    if expected_split == "validation":
        approval_path = run_root / "freeze-review-root.json"
        if not approval_path.is_file():
            raise DatasetValidationError("validation access waits for independent root freeze approval")
        approval = json.loads(approval_path.read_text(encoding="utf-8-sig"))
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if (
            approval.get("status") != "APPROVED_DIAGNOSTIC_FREEZE"
            or approval.get("manifest_sha256") != manifest_digest
            or approval.get("protocol_fingerprint_sha256") != manifest.get("hashes", {}).get("protocol_fingerprint_sha256")
            or not {"validation", "sealed"}.issubset(set(approval.get("reviewed_splits", [])))
            or approval.get("scope") != "diagnostic_only"
            or approval.get("training_eligible") is not False
            or approval.get("human_review_pending") is not True
        ):
            raise DatasetValidationError("root approval does not bind the diagnostic freeze manifest")
    bundle = manifest.get("bundles", {}).get(expected_split)
    if not isinstance(bundle, dict) or Path(bundle.get("path", "")).resolve() != canonical:
        raise DatasetValidationError("manifest does not declare the selected canonical bundle")
    if not resolved.is_file():
        raise DatasetValidationError("selected bundle is missing")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != bundle.get("sha256"):
        raise DatasetValidationError("selected bundle hash differs from the manifest")

    validator = make_envelope_validator(agent_root)
    counts: dict[str, int] = {}
    operation_counts: dict[str, int] = {}
    rows = 0
    with resolved.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("split") != expected_split:
                raise DatasetValidationError("sample split does not match selected bundle")
            summary = validate_record(record, validator)
            rows += 1
            counts[summary["case_type"]] = counts.get(summary["case_type"], 0) + 1
            task_operation = summary["task_operation"]
            if task_operation:
                operation_counts[task_operation] = operation_counts.get(task_operation, 0) + 1
    return {"split": expected_split, "rows": rows, "case_type_counts": counts, "task_operation_counts": operation_counts}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate a non-sealed T1 dataset bundle")
    parser.add_argument("--split", required=True, choices=("train", "validation", "sealed"))
    parser.add_argument("--path", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_jsonl(args.path, expected_split=args.split, agent_root=AGENT_ROOT), sort_keys=True))


