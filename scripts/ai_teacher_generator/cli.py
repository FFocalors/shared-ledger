from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from generator import (
    GeneratorError,
    build_request,
    create_plan,
    run_mock,
    validate_candidate_file,
    _write_json,
)
from live_provider import LiveProviderError, load_env
from live_pilot import run_adapter_fix_verification, run_connectivity_probe, run_live_pilot
from full_generation import build_generation_plan, run_full_generation, write_generation_plan


def _summary(plan: dict) -> dict:
    return {key: plan[key] for key in ("scenario_id", "scenario_family_id", "family_code", "gold_sample_id", "split_group_id", "seed", "style", "difficulty", "available_styles", "context_profile", "matrix", "frozen_hashes")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build offline Teacher requests and non-training candidates anchored to the frozen Gold Seed.")
    commands = parser.add_subparsers(dest="command", required=True)

    plan_cmd = commands.add_parser("plan", help="Create a deterministic Family → Gold Seed → Variant Plan.")
    plan_cmd.add_argument("--family", required=True)
    plan_cmd.add_argument("--seed", type=int, required=True)
    plan_cmd.add_argument("--style", choices=("colloquial", "typo_asr_like", "pronoun_ellipsis", "multi_turn"))

    request_cmd = commands.add_parser("request", help="Write a versioned Teacher Request without contacting a provider.")
    request_cmd.add_argument("--family", required=True)
    request_cmd.add_argument("--seed", type=int, required=True)
    request_cmd.add_argument("--style", choices=("colloquial", "typo_asr_like", "pronoun_ellipsis", "multi_turn"))
    request_cmd.add_argument("--out", type=Path, required=True)

    dry_cmd = commands.add_parser("mock-dry-run", help="Run deterministic offline mock generation and candidate validation.")
    dry_cmd.add_argument("--families", nargs="+", required=True)
    dry_cmd.add_argument("--seed", type=int, default=19)
    dry_cmd.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "runs" / "mock-dry-run")

    validate_cmd = commands.add_parser("validate", help="Validate a Candidate Sample against its canonical Scenario.")
    validate_cmd.add_argument("--candidate", type=Path, required=True)
    validate_cmd.add_argument("--scenario", type=Path, required=True)

    live_cmd = commands.add_parser("live-pilot", help="Run the bounded, explicitly authorized remote-provider pilot.")
    live_cmd.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "runs" / "live-pilot")
    live_cmd.add_argument("--timeout", type=float, default=60.0)
    live_cmd.add_argument("--initial-http-attempts", type=int, default=0)
    live_cmd.add_argument("--linked-previous-pilot-id")
    live_cmd.add_argument("--linked-probe-id")

    verify_cmd = commands.add_parser("verify-live-pilot", help="Run one endpoint-fix verification request per Family, without retries.")
    verify_cmd.add_argument("--pilot-dir", type=Path, required=True)
    verify_cmd.add_argument("--timeout", type=float, default=60.0)

    probe_cmd = commands.add_parser("probe-live", help="Send one non-retried connectivity probe and validate its response contract.")
    probe_cmd.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "runs" / "live-pilot")
    probe_cmd.add_argument("--timeout", type=float, default=60.0)

    plan_full_cmd = commands.add_parser("plan-full-generation", help="Write a stratified, versioned Family/source/style plan without calling a provider.")
    plan_full_cmd.add_argument("--pilot-path", type=Path)

    full_cmd = commands.add_parser("run-full-generation", help="Execute a bounded full candidate-pool run from a saved plan.")
    full_cmd.add_argument("--plan", type=Path, required=True)
    full_cmd.add_argument("--timeout", type=float, default=75.0)

    args = parser.parse_args(argv)
    try:
        if args.command in {"plan", "request"}:
            plan = create_plan(args.family, args.seed, style=args.style)
            if args.command == "plan":
                print(json.dumps(_summary(plan), ensure_ascii=False, indent=2))
            else:
                request = build_request(plan)
                _write_json(args.out, request)
                print(f"Wrote offline request: {args.out}")
        elif args.command == "mock-dry-run":
            results = []
            for family in args.families:
                plan = create_plan(family, args.seed)
                run_id = build_request(plan)["run_id"]
                output_dir = args.out_dir / run_id
                manifest = run_mock(plan, output_dir)
                results.append({"run_id": manifest["run_id"], "path": str(output_dir), "status": manifest["status"], "training_eligible": manifest["training_eligible"], "remote_provider_called": manifest["remote_provider_called"]})
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.command == "live-pilot":
            config = load_env(Path(__file__).parent / ".env")
            manifest = run_live_pilot(
                config,
                args.out_dir,
                args.timeout,
                initial_http_attempts=args.initial_http_attempts,
                linked_previous_pilot_id=args.linked_previous_pilot_id,
                linked_probe_id=args.linked_probe_id,
            )
            summary = {key: manifest.get(key) for key in ("pilot_id", "status", "provider", "model", "training_eligible", "summary", "frozen_hashes_unchanged")}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        elif args.command == "verify-live-pilot":
            config = load_env(Path(__file__).parent / ".env")
            manifest_path = args.pilot_dir / "pilot_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            verification = run_adapter_fix_verification(config, args.pilot_dir, manifest, args.timeout)
            summary = {key: verification.get(key) for key in ("verification_id", "status", "provider", "model", "summary")}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        elif args.command == "probe-live":
            config = load_env(Path(__file__).parent / ".env")
            manifest = run_connectivity_probe(config, args.out_dir, args.timeout)
            summary = {key: manifest.get(key) for key in ("probe_id", "status", "provider", "model", "http_status", "error_kind", "frozen_hashes_unchanged")}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        elif args.command == "plan-full-generation":
            plan = build_generation_plan(pilot_path=args.pilot_path) if args.pilot_path else build_generation_plan()
            run_dir = write_generation_plan(plan)
            summary = {"run_id": plan["run_id"], "run_dir": str(run_dir), **plan["summary"]}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        elif args.command == "run-full-generation":
            config = load_env(Path(__file__).parent / ".env")
            batch = run_full_generation(args.plan, config, args.timeout)
            summary = {key: batch.get(key) for key in ("run_id", "status", "planned_new_calls", "completed_calls", "http_attempts", "http_success_responses", "candidate_count_machine_pass", "candidate_count_pre_review_pool", "usage", "frozen_hashes_unchanged")}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            report = validate_candidate_file(args.candidate, args.scenario)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (GeneratorError, LiveProviderError, OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        # Provider configuration and exception messages are sanitized by the adapter.
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
