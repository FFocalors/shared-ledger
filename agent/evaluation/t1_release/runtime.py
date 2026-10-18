"""Pre-P2 v1 runtime loader pinned to the external, hash-checked source snapshot."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any


SNAPSHOT_ROOT = Path(r"D:\AI\runs\shared-ledger\t1-release-v2-20261011\baseline-snapshot")
SNAPSHOT_AGENT = SNAPSHOT_ROOT / "agent"
SNAPSHOT_MANIFEST_SHA256 = "711adfbd40a66d9c7b0aa1f32850e72e4f13fac08b370f051d4ae3791136989c"


class BaselineError(RuntimeError):
    pass


_MODULE_CACHE = None
_VALIDATOR_CACHE = None
_SNAPSHOT_STAT_CACHE: dict[str, tuple[int, int]] = {}
V2_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "dataset_contracts" / "t1-release-v2" / "dataset-envelope.schema.json"

def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot() -> dict[str, Any]:
    manifest_path = SNAPSHOT_ROOT / "snapshot-manifest.json"
    if not manifest_path.is_file() or _hash(manifest_path) != SNAPSHOT_MANIFEST_SHA256:
        raise BaselineError("read-only v1 baseline snapshot manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, dict) or len(entries) != 72:
        raise BaselineError("baseline manifest must bind all 72 frozen source and contract files")
    global _SNAPSHOT_STAT_CACHE
    current_stats: dict[str, tuple[int, int]] = {}
    for relative, item in entries.items():
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise BaselineError("snapshot manifest contains an unsafe relative path")
        path = SNAPSHOT_AGENT / Path(relative)
        if not item or not path.is_file():
            raise BaselineError(f"snapshot source file failed hash check: {relative}")
        stat = path.stat()
        current_stats[relative] = (stat.st_size, stat.st_mtime_ns)
    if current_stats != _SNAPSHOT_STAT_CACHE:
        for relative, item in entries.items():
            path = SNAPSHOT_AGENT / Path(relative)
            if _hash(path) != item["snapshot_sha256"]:
                raise BaselineError(f"snapshot source file failed hash check: {relative}")
        _SNAPSHOT_STAT_CACHE = current_stats
    local_agent = Path(__file__).resolve().parents[2]
    trusted_roots = (SNAPSHOT_ROOT.resolve(), SNAPSHOT_AGENT.resolve())
    for name, module in tuple(sys.modules.items()):
        if name.startswith("agent.app") or name == "evaluation" or name.startswith("evaluation."):
            origin = getattr(module, "__file__", None)
            if origin:
                resolved = Path(origin).resolve()
                if not any(resolved.is_relative_to(root) for root in trusted_roots):
                    raise BaselineError(f"untrusted preloaded module blocks pinned baseline import: {name}")
    evaluation_package = sys.modules.get("evaluation")
    if evaluation_package is not None:
        origin = getattr(evaluation_package, "__file__", None)
        if origin and not Path(origin).resolve().is_relative_to(SNAPSHOT_AGENT.resolve()):
            raise BaselineError("untrusted preloaded evaluation package blocks pinned baseline import")
        if hasattr(evaluation_package, "__path__"):
            pinned_evaluation = str((SNAPSHOT_AGENT / "evaluation").resolve())
            # Namespace packages have no code origin, but retaining a checkout
            # path would let later submodule imports resolve mutable local files.
            evaluation_package.__path__ = [pinned_evaluation]
    # The local release package may already have created the namespace package
    # `agent`. Put the verified snapshot package ahead of its local path so its
    # app/contracts and harness are imported from the frozen baseline.
    root_package = sys.modules.get("agent")
    if root_package is not None:
        origin = getattr(root_package, "__file__", None)
        if origin and not Path(origin).resolve().is_relative_to(SNAPSHOT_AGENT.resolve()):
            raise BaselineError("untrusted preloaded agent package blocks pinned baseline import")
    if root_package is not None and hasattr(root_package, "__path__"):
        pinned_agent = str(SNAPSHOT_AGENT.resolve())
        root_package.__path__ = [pinned_agent]
    for entry in (str(SNAPSHOT_AGENT), str(SNAPSHOT_ROOT)):
        if entry in sys.path:
            sys.path.remove(entry)
    sys.path.insert(0, str(SNAPSHOT_ROOT))
    sys.path.insert(0, str(SNAPSHOT_AGENT))
    return manifest


def baseline_modules():
    global _MODULE_CACHE
    manifest = verify_snapshot()
    if _MODULE_CACHE is not None:
        expected = {
            "agent.app.contracts": (SNAPSHOT_AGENT / "app/contracts.py").resolve(),
            "agent.app.harness": (SNAPSHOT_AGENT / "app/harness.py").resolve(),
            "evaluation.data_signature": (SNAPSHOT_AGENT / "evaluation/data_signature.py").resolve(),
            "evaluation.data_simulator": (SNAPSHOT_AGENT / "evaluation/data_simulator.py").resolve(),
            "evaluation.data_validate": (SNAPSHOT_AGENT / "evaluation/data_validate.py").resolve(),
        }
        for name, wanted in expected.items():
            module = sys.modules.get(name)
            if module is None or Path(module.__file__).resolve() != wanted:
                raise BaselineError(f"cached baseline module changed after verification: {name}")
            relative = wanted.relative_to(SNAPSHOT_AGENT.resolve()).as_posix()
            if _hash(wanted) != manifest["files"][relative]["snapshot_sha256"]:
                raise BaselineError(f"cached baseline module hash changed after verification: {name}")
        return _MODULE_CACHE
    importlib.invalidate_caches()
    contracts = importlib.import_module("agent.app.contracts")
    harness = importlib.import_module("agent.app.harness")
    data_signature = importlib.import_module("evaluation.data_signature")
    data_simulator = importlib.import_module("evaluation.data_simulator")
    data_validate = importlib.import_module("evaluation.data_validate")
    expected = {
        "agent.app.contracts": "app/contracts.py",
        "agent.app.harness": "app/harness.py",
        "evaluation.data_signature": "evaluation/data_signature.py",
        "evaluation.data_simulator": "evaluation/data_simulator.py",
        "evaluation.data_validate": "evaluation/data_validate.py",
    }
    modules = {
        "agent.app.contracts": contracts,
        "agent.app.harness": harness,
        "evaluation.data_signature": data_signature,
        "evaluation.data_simulator": data_simulator,
        "evaluation.data_validate": data_validate,
    }
    for name, relative in expected.items():
        module = modules[name]
        origin = Path(module.__file__).resolve()
        wanted = (SNAPSHOT_AGENT / relative).resolve()
        entry = manifest["files"][relative]
        if origin != wanted or _hash(origin) != entry["snapshot_sha256"]:
            raise BaselineError(f"imported module is not the hash-pinned snapshot: {name}")
    _MODULE_CACHE = (contracts, harness.parse_model_output, data_signature, data_simulator, data_validate)
    return _MODULE_CACHE


def make_v2_validator():
    global _VALIDATOR_CACHE
    _, _, _, _, _ = baseline_modules()
    if _VALIDATOR_CACHE is not None:
        return _VALIDATOR_CACHE
    from jsonschema import Draft202012Validator, RefResolver
    if not V2_SCHEMA_PATH.is_file():
        raise BaselineError(f"strict release v2 schema is missing: {V2_SCHEMA_PATH}")
    schema_path = V2_SCHEMA_PATH.resolve()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    _, _, _, _, data_validate = baseline_modules()
    original_schema = SNAPSHOT_AGENT / "dataset_contracts/t1/dataset-envelope.schema.json"
    resolver = RefResolver(base_uri=original_schema.as_uri(), referrer=schema,
                           handlers={"file": data_validate._file_handler})
    _VALIDATOR_CACHE = Draft202012Validator(schema, resolver=resolver)
    return _VALIDATOR_CACHE

