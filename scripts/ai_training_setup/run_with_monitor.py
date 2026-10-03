#!/usr/bin/env python3
"""Run a local LLaMA-Factory train config with external step/resource telemetry."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
import torch
import yaml
from transformers import TrainerCallback


class Jsonl:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, item: dict[str, Any]) -> None:
        item.setdefault("timestamp", datetime.now().astimezone().isoformat())
        def finite(value):
            if isinstance(value, dict):
                return {key: finite(child) for key, child in value.items()}
            if isinstance(value, (list, tuple)):
                return [finite(child) for child in value]
            if isinstance(value, float) and not math.isfinite(value):
                return str(value)
            return value
        item = finite(item)
        with self.lock, self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")


def resource_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ram_total_bytes": psutil.virtual_memory().total,
        "ram_available_bytes": psutil.virtual_memory().available,
        "ram_used_percent": psutil.virtual_memory().percent,
        "pagefile_total_bytes": psutil.swap_memory().total,
        "pagefile_used_bytes": psutil.swap_memory().used,
    }
    if torch.cuda.is_available():
        result.update({
            "torch_cuda_allocated_bytes": torch.cuda.memory_allocated(),
            "torch_cuda_reserved_bytes": torch.cuda.memory_reserved(),
            "torch_cuda_max_allocated_bytes": torch.cuda.max_memory_allocated(),
            "torch_cuda_max_reserved_bytes": torch.cuda.max_memory_reserved(),
        })
        free, total = torch.cuda.mem_get_info()
        result.update({"torch_cuda_free_bytes": free, "torch_cuda_total_bytes": total})
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.free,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        result["nvidia_smi"] = proc.stdout.strip().splitlines()[0]
    except Exception as error:
        result["nvidia_smi_error"] = type(error).__name__
    return result


class ResourcePoller(threading.Thread):
    def __init__(self, path: Path, interval: float = 1.0):
        super().__init__(daemon=True)
        self.writer = Jsonl(path)
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.writer.write({"kind": "resource_sample", **resource_snapshot()})
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=5)


class StepTelemetry(TrainerCallback):
    def __init__(self, path: Path):
        self.writer = Jsonl(path)
        self.step_started_at: float | None = None
        self.step_seconds: dict[int, float] = {}

    def on_train_begin(self, args, state, control, model=None, optimizer=None, **kwargs):
        trainable = total = lora_params = 0
        if model is not None:
            for name, parameter in model.named_parameters():
                count = parameter.numel()
                total += count
                if parameter.requires_grad:
                    trainable += count
                    if "lora_" in name.lower():
                        lora_params += count
        self.writer.write({"kind": "train_begin", "global_step": state.global_step,
                           "trainable_parameters": trainable, "total_parameters": total,
                           "lora_trainable_parameters": lora_params,
                           "trainable_percent": (100 * trainable / total) if total else None,
                           **resource_snapshot()})

    def on_step_begin(self, args, state, control, **kwargs):
        self.step_started_at = time.perf_counter()

    def on_step_end(self, args, state, control, model=None, optimizer=None, lr_scheduler=None, **kwargs):
        elapsed = time.perf_counter() - self.step_started_at if self.step_started_at is not None else None
        self.step_seconds[state.global_step] = elapsed or 0.0
        lr = optimizer.param_groups[0].get("lr") if optimizer and optimizer.param_groups else None
        self.writer.write({"kind": "optimizer_step", "global_step": state.global_step,
                           "seconds": elapsed, "learning_rate": lr,
                           "optimizer_state_entries": len(getattr(optimizer, "state", {})) if optimizer else None,
                           **resource_snapshot()})

    def on_log(self, args, state, control, logs=None, **kwargs):
        values = dict(logs or {})
        loss = values.get("loss")
        if loss is not None and not math.isfinite(float(loss)):
            values["finite_loss"] = False
            control.should_training_stop = True
        elif loss is not None:
            values["finite_loss"] = True
        self.writer.write({"kind": "trainer_log", "global_step": state.global_step,
                           "step_seconds": self.step_seconds.get(state.global_step),
                           "metrics": values, **resource_snapshot()})

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        self.writer.write({"kind": "evaluation", "global_step": state.global_step,
                           "metrics": dict(metrics or {}), **resource_snapshot()})

    def on_save(self, args, state, control, **kwargs):
        self.writer.write({"kind": "checkpoint_saved", "global_step": state.global_step,
                           "checkpoint_dir": str(Path(args.output_dir) / f"checkpoint-{state.global_step}"),
                           **resource_snapshot()})

    def on_train_end(self, args, state, control, **kwargs):
        self.writer.write({"kind": "train_end", "global_step": state.global_step,
                           "best_metric": state.best_metric, "best_model_checkpoint": state.best_model_checkpoint,
                           **resource_snapshot()})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--llamafactory-src", default=r"D:\AI\LlamaFactory\src", type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.llamafactory_src.resolve()))
    import llamafactory
    from llamafactory.train.tuner import run_exp

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    config["output_dir"] = str((run_dir / "checkpoints").resolve())
    config["overwrite_output_dir"] = True
    effective_config = run_dir / "effective.yaml"
    effective_config.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (run_dir / "environment.json").write_text(json.dumps({
        "python": sys.version.split()[0], "llamafactory": llamafactory.__version__, "torch": torch.__version__,
        "torch_cuda": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "gpu_capability": torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None,
        "transformers": __import__("transformers").__version__,
        "bitsandbytes": __import__("bitsandbytes").__version__,
        "config": config,
    }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    gpu_monitor = ResourcePoller(run_dir / "resources.jsonl")
    callback = StepTelemetry(run_dir / "training_metrics.jsonl")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    gpu_monitor.start()
    start = time.perf_counter()
    result: dict[str, Any] = {"status": "running", "start": datetime.now().astimezone().isoformat()}
    try:
        run_exp(config, callbacks=[callback])
        result["status"] = "completed"
    except BaseException as error:
        result["status"] = "failed"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        raise
    finally:
        result["elapsed_seconds"] = time.perf_counter() - start
        result["end"] = datetime.now().astimezone().isoformat()
        gpu_monitor.stop()
        result["last_resource_snapshot"] = resource_snapshot()
        (run_dir / "run_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
