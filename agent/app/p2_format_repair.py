"""Closed, stdlib-only format repair instruction and message-shape policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

P2_REPAIR_INSTRUCTION_VERSION = "p2-format-repair-instruction-v1"
P2_REPAIR_INSTRUCTION_ID = "p2_format_repair_v1"
P2_REPAIR_INSTRUCTIONS = {
    "invalid_json_syntax": "仅修正输出格式：上一次输出未能解析为 JSON。请重新输出一个完整 JSON 对象，并严格遵循原 response schema；不要添加 Markdown 或解释。",
    "invalid_strict_decision_schema": "仅修正输出结构：上一次输出不符合原 response schema。请重新输出一个完整且严格符合原 response schema 的 JSON 对象；不要添加 Markdown 或解释。",
}
P2_REPAIR_ERROR_CODES = frozenset(P2_REPAIR_INSTRUCTIONS)


def _message_fields(message: Any) -> tuple[object, object] | None:
    if type(message) is dict:
        if set(message) != {"role", "content"}:
            return None
        role, content = message.get("role"), message.get("content")
    elif isinstance(message, Mapping):
        if set(message) != {"role", "content"}:
            return None
        role, content = message.get("role"), message.get("content")
    else:
        role, content = getattr(message, "role", None), getattr(message, "content", None)
    if type(role) is not str or type(content) is not str:
        return None
    return role, content


def is_allowed_p2_message_sequence(messages: object) -> bool:
    """Accept exactly the legacy system/user pair or one closed repair triplet."""
    if type(messages) not in (list, tuple):
        return False
    fields = [_message_fields(message) for message in messages]
    if any(item is None for item in fields):
        return False
    roles = [item[0] for item in fields if item is not None]
    if len(fields) == 2:
        return roles == ["system", "user"]
    if len(fields) == 3:
        return (
            roles == ["system", "system", "user"]
            and fields[1] is not None
            and fields[1][1] in P2_REPAIR_INSTRUCTIONS.values()
        )
    return False
