#!/usr/bin/env python3
"""Export the frozen canonical v0.1 dataset to a LLaMA-Factory SFT layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.1"
OUT = ROOT / "docs/ai/training_setup/v0.1"
SPLITS = ("train", "validation", "test", "hard_test")
GROUP_MARKER = "<|shared_ledger_turn_block_v1|>"
SYSTEM_INSTRUCTION = (
    "你是 Android 共享账本应用中的助手。根据下方运行时上下文、对话历史和当前用户消息作答，"
    "遵守应用边界，并严格按要求输出 JSON。"
)
PRIVATE_KEYS = {
    "sample_id", "scenario_id", "scenario_family_id", "split_group_id", "dataset_version",
    "request_id", "turn_id", "conversation_id", "screen_instance_id", "created_at", "sent_at",
    "generated_at", "fetched_at", "baseline_commit", "source_reference", "validation_evidence",
    "lifecycle", "trust", "teacher", "generator", "training_eligible", "example_only",
}
META_PATTERN = re.compile(
    r"(?i)(sample_id|scenario_id|scenario_family_id|split_group_id|gold_seed|teacher_generated|"
    r"canonical_training|gold_sample|teacher_dataset|training_eligible)"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def clean_runtime(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: clean_runtime(v, k) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [clean_runtime(v) for v in value]
    return value


def runtime_context(sample: dict[str, Any]) -> dict[str, Any]:
    inp = sample["input"]
    client = inp.get("client_context", {})
    ui = inp.get("ui_context", {})
    user = inp.get("user_context", {})
    page = inp.get("page_state", {})
    conv = inp.get("conversation_context", {})
    server = inp.get("server_context", {})
    context = {
        "platform": client.get("platform"),
        "app_version": client.get("app_version"),
        "locale": client.get("locale"),
        "timezone": client.get("timezone"),
        "ui": {
            "route": ui.get("route"),
            "page_type": ui.get("page_type"),
            "activity_id": ui.get("activity_id"),
            "ledger_unit_id": ui.get("ledger_unit_id"),
            "selected_entity": ui.get("selected_entity"),
            "form_mode": ui.get("form_mode"),
            "focused_field": ui.get("focused_field"),
        },
        "user": {"claimed_participant_id": user.get("claimed_participant_id"), "role_hint": user.get("role_hint")},
        "page_state": {
            "load_state": page.get("load_state"),
            "financial_version_hint": page.get("financial_version_hint"),
            "entity_version_hint": page.get("entity_version_hint"),
            "filters": page.get("filters"),
            "visible_entities": page.get("visible_entities"),
            "draft": page.get("draft"),
            "write_state": page.get("write_state"),
        },
        "recent_actions": inp.get("recent_actions", []),
        "conversation_state": {
            "confirmed_bindings": conv.get("confirmed_bindings", []),
            "pending_clarification": conv.get("pending_clarification"),
        },
        "runtime_policy": {
            "enabled_tools": server.get("enabled_tools", []),
            "verified_result_ids": server.get("verified_result_ids", []),
            "confirmation_policy": server.get("confirmation_policy"),
            "tool_results": server.get("tool_results", []),
        },
    }
    return clean_runtime(context)


def source_turns(sample: dict[str, Any]) -> list[dict[str, str]]:
    history = sample["surface_form"].get("conversation", [])
    turns = [{"role": m["role"], "content": m["content"]} for m in history]
    turns.append({"role": "user", "content": sample["surface_form"]["user_message"]})
    return turns


def encode_turn_run(turns: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """Collapse adjacent equal roles into a reversible, explicitly delimited JSON block."""
    if len(turns) == 1 and not turns[0]["content"].startswith(GROUP_MARKER):
        return turns[0]["content"], [{"role": turns[0]["role"], "count": 1, "block": False}]
    payload = GROUP_MARKER + compact(turns)
    return payload, [{"role": turns[0]["role"], "count": len(turns), "block": True}]


def pack_messages(turns: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    messages: list[dict[str, str]] = []
    trace: list[dict[str, Any]] = []
    i = 0
    while i < len(turns):
        j = i + 1
        while j < len(turns) and turns[j]["role"] == turns[i]["role"]:
            j += 1
        run = turns[i:j]
        content, run_trace = encode_turn_run(run)
        messages.append({"role": turns[i]["role"], "content": content})
        trace.append({"packed_message_index": len(messages) - 1, "source_turn_start": i, "source_turn_end_exclusive": j,
                      "source_roles": [turn["role"] for turn in run], "reversible_block": run_trace[0]["block"]})
        i = j
    return messages, trace


def unpack_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for message in messages:
        content = message["content"]
        if content.startswith(GROUP_MARKER):
            block = json.loads(content[len(GROUP_MARKER):])
            if not isinstance(block, list) or not block or any(t.get("role") != message["role"] for t in block):
                raise ValueError("invalid reversible turn block")
            turns.extend({"role": t["role"], "content": t["content"]} for t in block)
        else:
            turns.append({"role": message["role"], "content": content})
    return turns


def export_record(sample: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    turns = source_turns(sample)
    messages, turn_trace = pack_messages(turns)
    recovered = unpack_messages(messages)
    if recovered != turns:
        raise ValueError(f"lossy history serialization: {sample['sample_id']}")
    expected = sample["expected"]["model_output"]
    target = compact(expected)
    if json.loads(target) != expected:
        raise ValueError(f"target JSON drift: {sample['sample_id']}")
    context = runtime_context(sample)
    system = SYSTEM_INSTRUCTION + "\n\n運行時上下文（JSON）：" + compact(context)
    model_visible = system + "\n" + "\n".join(m["content"] for m in messages) + target
    if META_PATTERN.search(model_visible):
        raise ValueError(f"metadata leakage: {sample['sample_id']}")
    record = {"system": system, "conversations": messages + [{"role": "assistant", "content": target}]}
    trace = {
        "sample_id": sample["sample_id"], "scenario_id": sample["scenario_id"],
        "scenario_family_id": sample["scenario_family_id"], "split_group_id": sample["split_group_id"],
        "split": sample["split"], "output_type": sample["expected"]["output_type"],
        "canonical_expected_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        "packed_turns": turn_trace, "source_turn_count": len(turns),
        "packed_message_count": len(messages), "history_roundtrip_verified": recovered == turns,
    }
    return record, trace


def export() -> dict[str, Any]:
    samples_path = CANONICAL / "samples.json"
    scenario_path = CANONICAL / "scenarios.json"
    split_path = CANONICAL / "split_assignment.json"
    manifest_path = CANONICAL / "dataset_manifest.json"
    samples = read_json(samples_path)
    scenarios = read_json(scenario_path)
    fin002_scenarios = {
        item["scenario_id"] for item in scenarios
        if item.get("source", {}).get("source_id") == "FIN-002"
    }
    fin002_families = {item["scenario_family_id"] for item in scenarios if item["scenario_id"] in fin002_scenarios}
    if any(item["scenario_family_id"] in fin002_families for item in samples):
        raise ValueError("FIN-002 must not contribute training samples")
    by_split = {name: [] for name in SPLITS}
    traces = []
    source_count = 0
    for sample in samples:
        split = sample.get("split")
        if split == "unassigned":
            continue
        if split not in by_split:
            raise ValueError(f"unexpected assigned split {split!r}")
        record, trace = export_record(sample)
        by_split[split].append(record)
        traces.append(trace)
        source_count += 1
    OUT.mkdir(parents=True, exist_ok=True)
    data_dir = OUT / "llamafactory"
    data_dir.mkdir(parents=True, exist_ok=True)
    registrations = {}
    for split, rows in by_split.items():
        filename = f"{split}.json"
        (data_dir / filename).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        registrations[f"sharedledger_{split}"] = {
            "file_name": filename,
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "system": "system"},
            "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user", "assistant_tag": "assistant"},
        }
    (data_dir / "dataset_info.json").write_text(json.dumps(registrations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "traceability.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_manifest = read_json(manifest_path)
    manifest = {
        "training_setup_version": "0.1", "canonical_dataset_version": "0.1",
        "source": {"path": "docs/ai/dataset/canonical_training/v0.1", "manifest_sha256": sha256(manifest_path),
                   "samples_sha256": sha256(samples_path), "scenarios_sha256": sha256(scenario_path),
                   "split_assignment_sha256": sha256(split_path)},
        "export": {"format": "LLaMA-Factory ShareGPT JSON", "record_count": source_count,
                   "split_counts": {k: len(v) for k, v in by_split.items()}, "excluded_unassigned_count": len(samples) - source_count,
                   "excluded_fin002_count": sum(1 for x in samples if x["scenario_family_id"] == "family_fin_002"),
                   "output_types": {k: sum(1 for x in samples if x["split"] != "unassigned" and x["expected"]["output_type"] == k)
                                    for k in sorted({x["expected"]["output_type"] for x in samples})}},
        "serialization": {"template": "qwen3_5_nothink", "system_context": "allowlisted runtime context only",
                          "history_group_marker": GROUP_MARKER, "history_roundtrip_verified": all(t["history_roundtrip_verified"] for t in traces),
                          "assistant_target": "compact JSON serialization of expected.model_output; parsed equality checked",
                          "loss_mask": {"train_on_prompt": False, "mask_history": True}},
        "llamafactory_source_version": "0.9.6.dev0", "frozen_canonical_manifest_status": source_manifest["status"],
    }
    for path in sorted([*data_dir.glob("*.json"), OUT / "traceability.json"]):
        manifest.setdefault("artifacts", {})[str(path.relative_to(OUT)).replace("\\", "/")] = sha256(path)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.check_only:
        manifest = export()
        print(json.dumps(manifest["export"], ensure_ascii=False, indent=2))
    else:
        raise SystemExit("--check-only is implemented by validate_setup.py")


if __name__ == "__main__":
    main()
