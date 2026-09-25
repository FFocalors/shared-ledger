"""Producer/consumer pipeline for mass generated-case verification.

Running one case end to end is latency-bound on three different services: the
local Qwen generator (one request at a time), DeepSeek (compiler and judge, both
remote and concurrent) and loopback Supabase (fast, but not free).  Executing
cases strictly one after another leaves the local model idle for most of a
batch, because a case spends the bulk of its time waiting for DeepSeek.

This module runs the four stages as independent worker pools connected by
bounded queues:

    ScenarioPlans -> [generator x1] -> [compiler xN] -> [runner xM] -> [judge xK] -> results

The local generator does exactly one request at a time (LM Studio is configured
with ``Max Concurrent Predictions = 1``), so it never competes with itself, but
it also never waits for DeepSeek: as soon as one raw case is written the next
plan is picked up.  DeepSeek calls from the compiler and the judge share one
global semaphore so the provider sees a bounded number of concurrent requests.

Every queue is bounded, so a slow judge applies backpressure to the runner and
then to the compiler instead of growing memory without limit.  Each case keeps
its own directory, run id, Supabase test user and activity, so concurrency never
mixes case data; progress events carry the case id, so the dashboard can route
them without cross-talk.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .focus_contract import ALL_FOCUSES, FocusDefinitionError
from .generate_case import CaseRun, stage_compile, stage_generate, start_case
from .run_generated_case import stage_execute, stage_judge
from .scenario_plan import ScenarioPlan, plan_for

# The local model must never be asked for two predictions at once.
LOCAL_GENERATOR_CONCURRENCY = 1


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 64) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class PipelineConfig:
    """Worker counts and queue bounds for one pipeline run."""

    generator_workers: int = 1
    compiler_workers: int = 2
    runner_workers: int = 2
    judge_workers: int = 4
    deepseek_max_concurrency: int = 4
    raw_queue_size: int = 20
    compiled_queue_size: int = 20
    judge_queue_size: int = 20

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        return cls(
            generator_workers=_env_int("LOCAL_GENERATOR_WORKERS", 1),
            compiler_workers=_env_int("COMPILER_WORKERS", 2),
            runner_workers=_env_int("RUNNER_WORKERS", 2),
            judge_workers=_env_int("JUDGE_WORKERS", 4),
            deepseek_max_concurrency=_env_int("DEEPSEEK_MAX_CONCURRENCY", 4),
            raw_queue_size=_env_int("RAW_QUEUE_SIZE", 20, maximum=500),
            compiled_queue_size=_env_int("COMPILED_QUEUE_SIZE", 20, maximum=500),
            judge_queue_size=_env_int("JUDGE_QUEUE_SIZE", 20, maximum=500),
        )

    def resolved(self) -> tuple["PipelineConfig", bool]:
        """Clamp the generator to a single worker; report whether that changed it."""
        if self.generator_workers == LOCAL_GENERATOR_CONCURRENCY:
            return self, False
        return (
            PipelineConfig(
                generator_workers=LOCAL_GENERATOR_CONCURRENCY,
                compiler_workers=self.compiler_workers,
                runner_workers=self.runner_workers,
                judge_workers=self.judge_workers,
                deepseek_max_concurrency=self.deepseek_max_concurrency,
                raw_queue_size=self.raw_queue_size,
                compiled_queue_size=self.compiled_queue_size,
                judge_queue_size=self.judge_queue_size,
            ),
            True,
        )


class DeepSeekGate:
    """One global semaphore shared by every DeepSeek call."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._semaphore = threading.BoundedSemaphore(self.limit)

    def __enter__(self) -> "DeepSeekGate":
        self._semaphore.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._semaphore.release()


class GatedClient:
    """Proxy that makes every ``complete`` call take a shared gate slot."""

    def __init__(self, inner: Any, gate: DeepSeekGate) -> None:
        self._inner = inner
        self._gate = gate

    @property
    def model(self) -> Any:
        return getattr(self._inner, "model", None)

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        with self._gate:
            return self._inner.complete(*args, **kwargs)


@dataclass
class PipelineStats:
    """Counters and queue high-water marks for one pipeline run."""

    planned: int = 0
    generated: int = 0
    compiled: int = 0
    executed: int = 0
    judged: int = 0
    queue_max: dict[str, int] = field(default_factory=lambda: {
        "raw": 0, "compiled": 0, "judge": 0,
    })
    started_at: float = 0.0
    finished_at: float = 0.0
    elapsed_seconds: float = 0.0

    def record_queue(self, name: str, depth: int) -> None:
        if depth > self.queue_max.get(name, 0):
            self.queue_max[name] = depth

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Queue:
    """A bounded queue that remembers its own high-water mark."""

    def __init__(self, name: str, maxsize: int, stats: PipelineStats) -> None:
        self.name = name
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self._stats = stats
        self.maxsize = maxsize

    def put(self, item: Any) -> None:
        self._queue.put(item)
        self._stats.record_queue(self.name, self._queue.qsize())

    def get(self) -> Any:
        item = self._queue.get()
        self._stats.record_queue(self.name, self._queue.qsize())
        return item

    def task_done(self) -> None:
        self._queue.task_done()


def build_batch_plans(
    focuses: Sequence[str] | Mapping[str, int],
    *,
    per_focus: int = 1,
    seed_base: int = 1,
) -> list[ScenarioPlan]:
    """Pre-generate every ScenarioPlan for a batch, deterministically.

    ``focuses`` is either an ordered list (``per_focus`` cases each) or a mapping
    from focus to case count, which is how a batch controls its coverage mix.
    Seeds are unique across the whole batch, so no two cases share a plan, and
    the same arguments always rebuild the same plan list.
    """
    if isinstance(focuses, Mapping):
        mix = [(focus, int(count)) for focus, count in focuses.items()]
    else:
        mix = [(focus, per_focus) for focus in focuses]

    plans: list[ScenarioPlan] = []
    for focus, count in mix:
        if focus not in ALL_FOCUSES:
            raise FocusDefinitionError(f"unsupported focus: {focus}")
        if count < 0:
            raise ValueError(f"case count for {focus} must not be negative")
        for _ in range(count):
            seed = seed_base + len(plans)
            plans.append(plan_for(focus, seed))
    return plans


def _progress_for(
    case_id: str, focus: str, seed: int | None,
    sink: Callable[[dict[str, Any]], None] | None,
) -> Callable[[str, str, dict[str, Any]], None] | None:
    if sink is None:
        return None

    def report(stage: str, status: str, details: dict[str, Any]) -> None:
        sink({
            "case_id": case_id,
            "focus": focus,
            "plan_seed": seed,
            "stage": stage,
            "status": status,
            "details": details,
        })

    return report


def run_pipeline(
    plans: Iterable[ScenarioPlan],
    *,
    config: PipelineConfig | None = None,
    business_logic_path: Path | None = None,
    local_client: Any = None,
    compiler_client: Any = None,
    judge_client: Any = None,
    runner: Callable[..., dict[str, Any]] | None = None,
    judge: Callable[..., dict[str, Any]] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_case_done: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run every plan through the four stages and return results plus statistics.

    Returns ``{"results": [result, ...], "stats": {...}, "config": {...}}`` in
    plan order.  A case that fails at any stage is recorded and the pipeline
    continues; nothing is retried to improve a verdict.
    """
    plan_list = list(plans)
    resolved, clamped = (config or PipelineConfig.from_env()).resolved()
    stats = PipelineStats(planned=len(plan_list), started_at=time.time())

    gate = DeepSeekGate(resolved.deepseek_max_concurrency)
    compiler_call = GatedClient(compiler_client, gate) if compiler_client is not None else None
    judge_call = GatedClient(judge_client, gate) if judge_client is not None else None

    raw_queue = _Queue("raw", resolved.raw_queue_size, stats)
    compiled_queue = _Queue("compiled", resolved.compiled_queue_size, stats)
    judge_queue = _Queue("judge", resolved.judge_queue_size, stats)

    class _StageEnd:
        """Counts finished workers and lets the last one close the next stage."""

        def __init__(self, workers: int, downstream: "_Queue", downstream_workers: int) -> None:
            self._remaining = workers
            self._downstream = downstream
            self._downstream_workers = downstream_workers
            self._lock = threading.Lock()

        def finish(self) -> None:
            with self._lock:
                self._remaining -= 1
                last = self._remaining == 0
            if last:
                for _ in range(self._downstream_workers):
                    self._downstream.put(None)

    compiler_end = _StageEnd(resolved.compiler_workers, compiled_queue, resolved.runner_workers)
    runner_end = _StageEnd(resolved.runner_workers, judge_queue, resolved.judge_workers)
    results: list[tuple[int, CaseRun]] = []
    results_lock = threading.Lock()
    failures: list[str] = []

    def record(index: int, run: CaseRun) -> None:
        with results_lock:
            results.append((index, run))
        if on_case_done is not None:
            on_case_done(run.result)

    def guard(name: str, body: Callable[[], None]) -> Callable[[], None]:
        def worker() -> None:
            try:
                body()
            except Exception as exc:  # a dead worker must not stall the batch
                failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:200]}")
        return worker

    def generator_stage() -> None:
        for index, plan in enumerate(plan_list):
            run = start_case(plan.focus, plan=plan, business_logic_path=business_logic_path)
            report = _progress_for(run.output_dir.name, plan.focus, plan.seed, on_progress)
            stage_generate(run, local_client=local_client, on_progress=report)
            stats.generated += 1
            raw_queue.put((index, run))
        for _ in range(resolved.compiler_workers):
            raw_queue.put(None)

    def compiler_stage() -> None:
        while True:
            item = raw_queue.get()
            try:
                if item is None:
                    break
                index, run = item
                report = _progress_for(
                    run.output_dir.name, run.focus, run.result.get("plan_seed"), on_progress
                )
                stage_compile(run, compiler_client=compiler_call, on_progress=report)
                stats.compiled += 1
                if run.result.get("status") in ("VALID", "FOCUS_MISMATCH"):
                    compiled_queue.put((index, run))
                else:
                    record(index, run)
            finally:
                raw_queue.task_done()
        compiler_end.finish()

    def runner_stage() -> None:
        while True:
            item = compiled_queue.get()
            try:
                if item is None:
                    break
                index, run = item
                report = _progress_for(
                    run.output_dir.name, run.focus, run.result.get("plan_seed"), on_progress
                )
                stage_execute(run, runner=runner, on_progress=report)
                stats.executed += 1
                judge_queue.put((index, run))
            finally:
                compiled_queue.task_done()
        runner_end.finish()

    def judge_stage() -> None:
        while True:
            item = judge_queue.get()
            try:
                if item is None:
                    break
                index, run = item
                report = _progress_for(
                    run.output_dir.name, run.focus, run.result.get("plan_seed"), on_progress
                )
                stage_judge(run, judge=judge, judge_client=judge_call, on_progress=report)
                stats.judged += 1
                record(index, run)
            finally:
                judge_queue.task_done()

    threads: list[threading.Thread] = []
    # The downstream pools start first so the bounded queues fill and apply
    # backpressure from the start rather than only once they are saturated.
    for _ in range(resolved.judge_workers):
        threads.append(threading.Thread(target=guard("judge", judge_stage), daemon=True))
    for _ in range(resolved.runner_workers):
        threads.append(threading.Thread(target=guard("runner", runner_stage), daemon=True))
    for _ in range(resolved.compiler_workers):
        threads.append(threading.Thread(target=guard("compiler", compiler_stage), daemon=True))
    threads.append(threading.Thread(target=guard("generator", generator_stage), daemon=True))

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stats.finished_at = time.time()
    stats.elapsed_seconds = round(stats.finished_at - stats.started_at, 3)
    ordered = [run.result for _, run in sorted(results, key=lambda item: item[0])]
    return {
        "results": ordered,
        "stats": stats.as_dict(),
        "config": asdict(resolved),
        "generator_clamped": clamped,
        "worker_failures": failures,
    }


def summarise_pipeline(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a pipeline run to the counters the batch report needs."""
    results = list(payload.get("results") or [])
    stats = dict(payload.get("stats") or {})
    statuses = Counter(str(run.get("status")) for run in results)
    error_kinds = Counter(
        str(run.get("error_category")) for run in results if run.get("error_category")
    )
    elapsed = float(stats.get("elapsed_seconds") or 0.0)
    return {
        "cases": len(results),
        "statuses": dict(statuses),
        "error_categories": dict(error_kinds),
        "elapsed_seconds": elapsed,
        "cases_per_hour": round(len(results) / elapsed * 3600, 1) if elapsed > 0 else None,
        "queue_max": stats.get("queue_max", {}),
        "config": payload.get("config", {}),
        "worker_failures": payload.get("worker_failures", []),
        "deepseek_timeouts": sum(
            1 for run in results
            if str(run.get("error_category", "")).upper() in {"TIMEOUT", "NETWORK"}
        ),
    }


__all__ = [
    "DeepSeekGate",
    "GatedClient",
    "LOCAL_GENERATOR_CONCURRENCY",
    "PipelineConfig",
    "PipelineStats",
    "build_batch_plans",
    "run_pipeline",
    "summarise_pipeline",
]
