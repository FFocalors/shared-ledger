"""Canonical JSON and hashing, byte-compatible with the v2 release tooling.

The drivers must not import the v2 tooling package: it pins a different frozen
baseline and refuses to run once the v1.1 package is loaded.  These two helpers
reproduce ``t1_release.signatures.canonical_json`` and ``sha256`` exactly, so
row signatures stay comparable across the two generations.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value)
    return hashlib.sha256(payload).hexdigest()
