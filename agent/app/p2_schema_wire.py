"""Versioned, explicit P2-only JSON Schema wire projection.

The canonical schema remains owned by :mod:`app.contracts`.  This helper
returns a deep-copied provider-wire value and removes only ``title`` members
that belong to recognized JSON Schema nodes.  It is not a model-behavior or
provider-acceptance guarantee.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal, TypeAlias


P2_WIRE_CONFIG_VERSION = "p2-wire-config-v2"
P2_SCHEMA_RENDERER_VERSION = "p2-json-schema-title-strip-v1"
P2_SCHEMA_ENVELOPE_KIND = "p2_typed_envelope"
P2_SCHEMA_PROVIDER_VERSION = "p2-lmstudio-openai-v2-schema-renderer-v1"
P2_SCHEMA_PROMPT_VERSION = "shared-ledger-p2-routing-r3-schema-title-v1"

JsonSchema: TypeAlias = dict[str, object] | bool


@dataclass(frozen=True)
class P2SchemaWireSelection:
    """Explicit opt-in to the reviewed P2 typed-envelope wire renderer."""

    wire_config_version: Literal["p2-wire-config-v2"] = P2_WIRE_CONFIG_VERSION
    envelope_kind: Literal["p2_typed_envelope"] = P2_SCHEMA_ENVELOPE_KIND
    renderer_version: Literal["p2-json-schema-title-strip-v1"] = P2_SCHEMA_RENDERER_VERSION


_SCHEMA_MAP_KEYWORDS = (
    "$defs",
    "definitions",
    "properties",
    "patternProperties",
    "dependentSchemas",
)
_SCHEMA_ARRAY_KEYWORDS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SCHEMA_SINGLE_KEYWORDS = (
    "additionalItems",
    "additionalProperties",
    "unevaluatedItems",
    "unevaluatedProperties",
    "contains",
    "propertyNames",
    "contentSchema",
    "not",
    "if",
    "then",
    "else",
)


def validate_p2_schema_wire_selection(
    selection: object,
    *,
    provider_version: str,
    prompt_version: str,
) -> P2SchemaWireSelection:
    """Fail closed unless every selected candidate version is the reviewed tuple."""

    if not isinstance(selection, P2SchemaWireSelection):
        raise ValueError("schema_wire_selection must be a P2SchemaWireSelection")
    if (
        selection.wire_config_version != P2_WIRE_CONFIG_VERSION
        or selection.envelope_kind != P2_SCHEMA_ENVELOPE_KIND
        or selection.renderer_version != P2_SCHEMA_RENDERER_VERSION
        or provider_version != P2_SCHEMA_PROVIDER_VERSION
        or prompt_version != P2_SCHEMA_PROMPT_VERSION
    ):
        raise ValueError("selected P2 schema wire version tuple is unsupported")
    return selection


def _visit_schema_node(node: object) -> None:
    if isinstance(node, bool):
        return
    if not isinstance(node, dict):
        raise TypeError("schema nodes must be JSON objects or booleans")

    # Only this object's annotation is removed. Map keys such as a property
    # literally named "title" and non-schema wrapper members are preserved.
    node.pop("title", None)

    for keyword in _SCHEMA_MAP_KEYWORDS:
        if keyword not in node:
            continue
        children = node[keyword]
        if not isinstance(children, dict):
            raise TypeError(f"{keyword} must be an object of schemas")
        for child in children.values():
            _visit_schema_node(child)

    # Draft 7 also permits tuple-form `items`.
    if "items" in node:
        items = node["items"]
        if isinstance(items, list):
            for child in items:
                _visit_schema_node(child)
        else:
            _visit_schema_node(items)

    for keyword in _SCHEMA_ARRAY_KEYWORDS:
        if keyword not in node:
            continue
        children = node[keyword]
        if not isinstance(children, list):
            raise TypeError(f"{keyword} must be an array of schemas")
        for child in children:
            _visit_schema_node(child)

    for keyword in _SCHEMA_SINGLE_KEYWORDS:
        if keyword in node:
            _visit_schema_node(node[keyword])

    # Draft 7 `dependencies` can contain either schemas or property-name lists.
    if "dependencies" in node:
        dependencies = node["dependencies"]
        if not isinstance(dependencies, dict):
            raise TypeError("dependencies must be an object")
        for child in dependencies.values():
            if isinstance(child, (dict, bool)):
                _visit_schema_node(child)


def render_p2_wire_schema(
    canonical_schema: JsonSchema,
    selection: P2SchemaWireSelection,
    *,
    provider_version: str,
    prompt_version: str,
) -> JsonSchema:
    """Return a copied schema with recognized schema-node title annotations removed."""

    validate_p2_schema_wire_selection(
        selection,
        provider_version=provider_version,
        prompt_version=prompt_version,
    )
    if not isinstance(canonical_schema, (dict, bool)):
        raise TypeError("canonical schema must be an object or boolean")
    projected = copy.deepcopy(canonical_schema)
    _visit_schema_node(projected)
    return projected
