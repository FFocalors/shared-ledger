"""Pinned module and schema loader for the release-v3 conversion.

Mirrors ``evaluation.t1_release.runtime`` but resolves every generation
module -- the v1 baseline contracts/simulator *and* the frozen offline v1.1
protocol package -- from the v3 snapshot, so a v3 run cannot be silently
influenced by a dirty working tree.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from . import profile, snapshot

SNAPSHOT_ROOT = profile.SNAPSHOT_ROOT
SNAPSHOT_AGENT = SNAPSHOT_ROOT / "agent"

_BASELINE_MODULES = {
    "agent.app.contracts": "app/contracts.py",
    "agent.app.harness": "app/harness.py",
    "evaluation.data_signature": "evaluation/data_signature.py",
    "evaluation.data_simulator": "evaluation/data_simulator.py",
}
_V11_MODULE = "evaluation.t1_protocol_v1_1"
_SELF_PACKAGE = "agent.evaluation.t1_release_v3"

_MODULE_CACHE: tuple[Any, ...] | None = None
_VALIDATOR_CACHE = None


class RuntimeV3Error(RuntimeError):
    pass


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot() -> dict[str, Any]:
    try:
        return snapshot.verify_snapshot(SNAPSHOT_ROOT)
    except snapshot.SnapshotError as exc:  # pragma: no cover - defensive
        raise RuntimeV3Error(str(exc)) from exc


def _pin_package_paths() -> None:
    """Force every generation import to resolve inside a frozen snapshot.

    Both the v2 and the v3 snapshot hold byte-identical copies of the v1
    baseline set; the release-v3 snapshot additionally holds the frozen v1.1
    protocol package.  A preloaded module is therefore accepted when its
    bytes are the ones the v3 snapshot pins, no matter which of the two
    verified snapshots it was imported from.  The v1.1 package exists only in
    the v3 snapshot, so its origin is checked directly.
    """
    trusted_roots = (
        SNAPSHOT_ROOT.resolve(),
        SNAPSHOT_AGENT.resolve(),
        profile.V2_SNAPSHOT_ROOT.resolve(),
        (profile.V2_SNAPSHOT_ROOT / "agent").resolve(),
    )
    for name, module in tuple(sys.modules.items()):
        if name.startswith(_SELF_PACKAGE):
            continue
        if name.startswith("agent.app") or name == "evaluation" or name.startswith("evaluation."):
            origin = getattr(module, "__file__", None)
            if origin and not any(Path(origin).resolve().is_relative_to(root) for root in trusted_roots):
                raise RuntimeV3Error(f"untrusted preloaded module blocks pinned v3 import: {name}")
    evaluation_package = sys.modules.get("evaluation")
    if evaluation_package is not None and hasattr(evaluation_package, "__path__"):
        evaluation_package.__path__ = [str((SNAPSHOT_AGENT / "evaluation").resolve())]
    root_package = sys.modules.get("agent")
    if root_package is not None and hasattr(root_package, "__path__"):
        root_package.__path__ = [str(SNAPSHOT_AGENT.resolve())]
    for entry in (str(SNAPSHOT_AGENT), str(SNAPSHOT_ROOT)):
        if entry in sys.path:
            sys.path.remove(entry)
    sys.path.insert(0, str(SNAPSHOT_ROOT))
    sys.path.insert(0, str(SNAPSHOT_AGENT))


def _prove(name: str, relative: str, manifest: dict[str, Any]) -> Path:
    """A module is pinned when its bytes are the ones the v3 snapshot records.

    Path equality is not required: the v2 snapshot carries byte-identical
    copies of the v1 baseline set, so either verified origin is legitimate.
    """
    module = sys.modules.get(name)
    if module is None or not getattr(module, "__file__", None):
        raise RuntimeV3Error(f"pinned v3 module is not imported: {name}")
    origin = Path(module.__file__).resolve()
    if not origin.is_file():
        raise RuntimeV3Error(f"pinned v3 module has no readable origin: {name}")
    if _hash(origin) != manifest["files"][relative]["snapshot_sha256"]:
        raise RuntimeV3Error(f"pinned v3 snapshot module content differs from the freeze: {name}")
    return origin


def baseline_modules() -> tuple[Any, ...]:
    """Return (v1 contracts, v1.1 protocol package, signature, simulator)."""
    global _MODULE_CACHE
    manifest = verify_snapshot()
    if _MODULE_CACHE is not None:
        for name, relative in _BASELINE_MODULES.items():
            _prove(name, relative, manifest)
        _prove(_V11_MODULE, f"{profile.V11_PACKAGE_RELATIVE.as_posix()}/__init__.py", manifest)
        return _MODULE_CACHE

    _pin_package_paths()
    importlib.invalidate_caches()
    contracts = importlib.import_module("agent.app.contracts")
    importlib.import_module("agent.app.harness")
    v11 = importlib.import_module(_V11_MODULE)
    signature = importlib.import_module("evaluation.data_signature")
    simulator = importlib.import_module("evaluation.data_simulator")
    for name, relative in _BASELINE_MODULES.items():
        _prove(name, relative, manifest)
    _prove(_V11_MODULE, f"{profile.V11_PACKAGE_RELATIVE.as_posix()}/__init__.py", manifest)
    if v11.SEMANTIC_VERSION != profile.V11_SEMANTIC_VERSION:  # pragma: no cover - defensive
        raise RuntimeV3Error("pinned v1.1 package does not carry the expected semantic version")
    _MODULE_CACHE = (contracts, v11, signature, simulator)
    return _MODULE_CACHE


def make_v3_validator():
    """A Draft 2020-12 validator over the release-v3 envelope schema.

    The envelope embeds the frozen v1.1 protocol schemas, but it still refers
    to the unchanged vendor v1 schemas for the replayed tool result, so the
    resolver is rooted inside the v3 snapshot exactly as the v2 validator is.
    """
    global _VALIDATOR_CACHE
    if _VALIDATOR_CACHE is not None:
        return _VALIDATOR_CACHE
    from jsonschema import Draft202012Validator, RefResolver

    from .schema import V3_SCHEMA_PATH

    if not V3_SCHEMA_PATH.is_file():
        raise RuntimeV3Error(f"release-v3 envelope schema is missing: {V3_SCHEMA_PATH}")
    verify_snapshot()
    schema = json.loads(V3_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    snapshot_schema = (
        SNAPSHOT_AGENT / "dataset_contracts" / "t1-release-v3" / "dataset-envelope.schema.json"
    )
    data_validate = importlib.import_module("evaluation.data_validate")
    resolver = RefResolver(
        base_uri=snapshot_schema.as_uri(),
        referrer=schema,
        handlers={"file": data_validate._file_handler},
    )
    _VALIDATOR_CACHE = Draft202012Validator(schema, resolver=resolver)
    return _VALIDATOR_CACHE
