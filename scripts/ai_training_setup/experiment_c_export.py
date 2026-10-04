#!/usr/bin/env python3
"""Build the isolated v0.2 Experiment C setup from frozen canonical v0.1."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_dataset as base  # noqa: E402

OUT = ROOT / "docs/ai/training_setup/v0.2_experiment_c_only"
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.1"
OLD_SETUP = ROOT / "docs/ai/training_setup/v0.1"
GUIDE = """你是 Android 共享账本助手。只依据本轮消息、对话及模型可见的运行时上下文/工具结果；事实缺失、冲突或指代不唯一时先输出 clarification，不猜实体、金额、时间、结果或用户确认。明确由用户提供的操作参数可用于方案；余额、债务、额度、汇率、分摊/结算结果等账务事实只引用可见且已验证的服务端结果，不自行计算，也不宣称写入成功。实体仅取自明确消息、可见上下文/已确认绑定或已验证结果。
仅对当前范围已开放且允许的查询/实体解析，按 enabled_tools 与意图工具映射输出一个读 tool_call；不得调用未开放能力、任意工具、SQL 或后端接口。写意图只有在能力已开放、所需事实充分时才先输出 proposal；缺少/冲突信息时澄清，DEFERRED 能力使用 unsupported 或引导至原生流程。L1/L2 proposal 只有经可信 UI 明确点击确认且 Gateway 复核后，编排层才可转为写 tool_call；聊天中的“确认”不是授权，proposal/tool_call 不代表 RPC 已成功。D4 的 update_expense/update_refund 仅可给出 execution_policy.execution_allowed=false、reason=d4_atomic_update_not_supported 的 proposal，永不转为写 tool_call。未裁定的 OPEN_DECISION 按冻结规则澄清，不自行补定。
每轮只输出一个符合约定 JSON contract 的对象，不输出 Markdown 或额外文字。只使用六种既有 type：answer、proposal、tool_call、clarification、unsupported、error；按该 type 的封闭分支填写全部必需字段与正确类型，禁止额外字段。proposal 必须含完整 operation、preview/diff、confirmation 和 execution_policy；tool_call 必须匹配允许的 intent/tool/arguments。候选与 evidence ID 仅引用可见且有依据的来源；不得编造事实。"""

OLD_SYSTEM = base.SYSTEM_INSTRUCTION


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    base.CANONICAL = CANONICAL
    base.OUT = OUT
    base.SYSTEM_INSTRUCTION = GUIDE
    manifest = base.export()
    manifest["training_setup_version"] = "0.2-experiment-c-only"
    manifest["experiment"] = "C_compact_contract_guide"
    manifest["variable"] = "model-visible system Contract guide only"
    manifest["frozen_baseline_setup"] = "docs/ai/training_setup/v0.1"
    manifest["source"]["old_setup_manifest_sha256"] = sha(OLD_SETUP / "manifest.json")
    manifest["source"]["contract_sha256"] = sha(ROOT / "docs/ai/AI_MODEL_CONTRACT.md")
    manifest["source"]["scope_freeze_sha256"] = sha(ROOT / "docs/ai/AI_SCOPE_FREEZE_V0.1.md")
    manifest["source"]["output_schema_sha256"] = sha(ROOT / "docs/ai/schema/model_output.schema.json")
    manifest["system_guide"] = {
        "old": OLD_SYSTEM,
        "new": GUIDE,
        "tokenizer": "D:/AI/models/Qwen3.5-4B local tokenizer; measured by validation script",
    }
    write_json(OUT / "manifest.json", manifest)
    (OUT / "system_guide.txt").write_text(GUIDE + "\n", encoding="utf-8")

    old_config = (OLD_SETUP / "qlora.yaml").read_text(encoding="utf-8")
    config = old_config.replace(
        "D:/project/Android/shared-ledger/docs/ai/training_setup/v0.1/llamafactory",
        "D:/project/Android/shared-ledger/docs/ai/training_setup/v0.2_experiment_c_only/llamafactory",
    ).replace(
        "D:/AI/runs/shared-ledger/qwen3.5-4b-qlora-v0.1",
        "D:/AI/runs/shared-ledger/qwen3.5-4b-qlora-v0.2-experiment-c-only",
    )
    (OUT / "qlora.yaml").write_text(config, encoding="utf-8")
    (OUT / "smoke.yaml").write_text((OLD_SETUP / "smoke.yaml").read_text(encoding="utf-8").replace(
        "D:/project/Android/shared-ledger/docs/ai/training_setup/v0.1/llamafactory",
        "D:/project/Android/shared-ledger/docs/ai/training_setup/v0.2_experiment_c_only/llamafactory",
    ).replace(
        "D:/AI/runs/shared-ledger/training-smoke-v0.1",
        "D:/AI/runs/shared-ledger/training-smoke-v0.2-experiment-c-only",
    ), encoding="utf-8")
    manifest["artifacts"] = {
        str(p.relative_to(OUT)).replace("\\", "/"): sha(p)
        for p in sorted([*(OUT / "llamafactory").glob("*.json"), OUT / "traceability.json", OUT / "system_guide.txt", OUT / "qlora.yaml", OUT / "smoke.yaml", OUT / "README.md", OUT / "contract_coverage.json"])
    }
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps(manifest["export"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
