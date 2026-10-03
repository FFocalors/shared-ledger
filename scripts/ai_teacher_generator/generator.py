from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scripts.ai_dataset_validator.validator import DatasetValidator


GENERATOR_VERSION = "0.1.0"
PROMPT_VERSION = "surface-variant-v1.0.0"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
FROZEN_DIR = Path("docs/ai/dataset/gold_seed/v0.1/p0")
MANIFEST_REL = FROZEN_DIR / "dataset_manifest.json"
SCENARIOS_REL = FROZEN_DIR / "scenarios.json"
SAMPLES_REL = FROZEN_DIR / "samples.json"
MATRIX_REL = Path("docs/ai/dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md")
CONTRACT_ASSETS = {
    "ai_contract_sha256": Path("docs/ai/AI_MODEL_CONTRACT.md"),
    "ai_scope_sha256": Path("docs/ai/AI_SCOPE_FREEZE_V0.1.md"),
    "intent_catalog_sha256": Path("docs/ai/schema/intent_catalog.json"),
    "tool_catalog_sha256": Path("docs/ai/schema/tool_catalog.json"),
    "model_output_schema_sha256": Path("docs/ai/schema/model_output.schema.json"),
    "context_envelope_schema_sha256": Path("docs/ai/schema/context_envelope.schema.json"),
    "scenario_schema_sha256": Path("docs/ai/dataset/schema/scenario.schema.json"),
    "sample_schema_sha256": Path("docs/ai/dataset/schema/sample.schema.json"),
    "validation_rules_sha256": Path("docs/ai/dataset/DATASET_VALIDATION_RULES.md"),
}
MOCK_TIME = "2026-09-29T00:00:00+00:00"
STYLES = ("colloquial", "typo_asr_like", "pronoun_ellipsis", "multi_turn")


class GeneratorError(ValueError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _repo_root() -> Path:
    return _PROJECT_ROOT


def frozen_assets(root: Path | None = None) -> dict[str, Any]:
    repo = root or _repo_root()
    manifest = _read_json(repo / MANIFEST_REL)
    if manifest.get("status") != "frozen":
        raise GeneratorError("Teacher generation requires a frozen Gold Seed manifest.")
    scenarios_path, samples_path = repo / SCENARIOS_REL, repo / SAMPLES_REL
    expected = {entry["path"]: entry["sha256"] for entry in manifest["artifacts"]}
    actual = {"scenarios.json": _sha256(scenarios_path), "samples.json": _sha256(samples_path)}
    for filename, digest in actual.items():
        if expected.get(filename) != digest:
            raise GeneratorError(f"Frozen Gold Seed hash mismatch for {filename}.")
    return {
        "root": repo,
        "manifest": manifest,
        "scenarios": _read_json(scenarios_path),
        "samples": _read_json(samples_path),
        "scenario_sha256": actual["scenarios.json"],
        "sample_sha256": actual["samples.json"],
        "matrix_sha256": _sha256(repo / MATRIX_REL),
        "contract_hashes": {key: _sha256(repo / path) for key, path in CONTRACT_ASSETS.items()},
    }


def _matrix_rows(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 12:
            continue
        family_id = cells[0].strip("`")
        if not re.fullmatch(r"[A-Z][A-Z0-9-]+", family_id):
            continue
        try:
            target = int(cells[10])
        except ValueError:
            continue
        rows[family_id] = {
            "family_id": family_id,
            "title": cells[1].strip("`"),
            "primary_task": cells[3].strip("`").strip(),
            "sample_target": target,
            "priority": cells[11].strip("`").strip(),
        }
    return rows


def _family_code(scenario: dict[str, Any]) -> str:
    return str(scenario.get("source", {}).get("source_id", ""))


def _style_options(sample: dict[str, Any]) -> list[str]:
    options = ["colloquial", "typo_asr_like"]
    user_text = sample.get("surface_form", {}).get("user_message", "")
    if re.search(r"我|你|他|她|它|这|那|刚才|上面|里面|其中", user_text):
        options.append("pronoun_ellipsis")
    if sample.get("surface_form", {}).get("conversation"):
        options.append("multi_turn")
    return options


def _context_profile(sample: dict[str, Any]) -> dict[str, Any]:
    envelope = sample.get("input", {})
    ui = envelope.get("ui_context", {})
    page = envelope.get("page_state", {})
    recent = envelope.get("recent_actions", [])
    conversation = envelope.get("conversation_context", {})
    return {
        "page_type": ui.get("page_type", "unknown"),
        "form_mode": ui.get("form_mode"),
        "has_draft": page.get("draft") is not None,
        "has_recent_action": bool(recent),
        "has_conversation": bool(conversation.get("messages")),
        "has_pending_clarification": conversation.get("pending_clarification") is not None,
    }


def create_plan(family_id: str, seed: int, root: Path | None = None, style: str | None = None) -> dict[str, Any]:
    assets = frozen_assets(root)
    scenarios_by_family: dict[str, list[dict[str, Any]]] = {}
    for scenario in assets["scenarios"]:
        scenarios_by_family.setdefault(scenario.get("scenario_family_id", ""), []).append(scenario)
    family_scenarios = scenarios_by_family.get(family_id, [])
    if not family_scenarios:
        raise GeneratorError(f"Family is absent from the frozen Scenario set: {family_id}")
    family_code = _family_code(family_scenarios[0])
    matrix = _matrix_rows(assets["root"] / MATRIX_REL)
    if family_code not in matrix:
        raise GeneratorError(f"Family has no Matrix row: {family_code}")
    scenarios_by_id = {s["scenario_id"]: s for s in family_scenarios}
    samples = sorted(
        (s for s in assets["samples"] if s.get("scenario_family_id") == family_id and s.get("trust", {}).get("level") == "GOLD"),
        key=lambda s: s["sample_id"],
    )
    if not samples:
        raise GeneratorError("Family has no approved Gold seed sample; unverified families cannot be generated.")
    seed_sample = samples[seed % len(samples)]
    scenario = scenarios_by_id.get(seed_sample["scenario_id"])
    if scenario is None or scenario.get("trust", {}).get("business_validated") is not True:
        raise GeneratorError("Seed sample does not resolve to a validated canonical scenario.")
    options = _style_options(seed_sample)
    if style is None:
        style = options[seed % len(options)]
    if style not in STYLES or style not in options:
        raise GeneratorError(f"Style {style!r} is not supported by the selected seed context; available={options!r}.")
    return {
        "plan_version": "0.1",
        "generator_version": GENERATOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "seed": seed,
        "scenario_id": scenario["scenario_id"],
        "scenario_family_id": family_id,
        "family_code": family_code,
        "gold_sample_id": seed_sample["sample_id"],
        "split_group_id": seed_sample["split_group_id"],
        "matrix": matrix[family_code],
        "style": style,
        "available_styles": options,
        "difficulty": seed_sample["difficulty"],
        "context_profile": _context_profile(seed_sample),
        "scenario": scenario,
        "seed_sample": seed_sample,
        "frozen_hashes": {
            "scenarios_sha256": assets["scenario_sha256"],
            "samples_sha256": assets["sample_sha256"],
            "matrix_sha256": assets["matrix_sha256"],
            **assets["contract_hashes"],
            "prompt_template_sha256": _sha256(PROMPT_PATH),
        },
    }


def _anonymized_expected(expected: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    aliases = {entity["id"]: entity.get("alias", "ENTITY") for entity in scenario.get("state", {}).get("entities", []) if entity.get("id")}
    opaque: dict[str, str] = {}

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            if value in aliases:
                return f"<{aliases[value]}>"
            if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", value):
                return "<LOCKED_ID>"
            if re.match(r"^(result|request|screen|conversation|draft)[-_][A-Za-z0-9_-]+$", value):
                if value not in opaque:
                    opaque[value] = f"<LOCKED_{len(opaque) + 1}>"
                return opaque[value]
        return copy.deepcopy(value)

    return scrub(expected)


def teacher_visible_anchor(plan: dict[str, Any]) -> dict[str, Any]:
    scenario, sample = plan["scenario"], plan["seed_sample"]
    user_context = sample["input"].get("conversation_context", {})
    surface = sample["surface_form"]
    state_entities = scenario.get("state", {}).get("entities", [])
    op = scenario.get("operation", {})
    facts = scenario.get("state", {}).get("facts", {})
    entity_aliases = {entity["id"]: f"<{entity.get('alias', 'ENTITY')}>" for entity in state_entities if entity.get("id")}

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            return entity_aliases.get(value, value)
        return copy.deepcopy(value)

    entities = [{"alias": e.get("alias"), "type": e.get("type"), "display_name": e.get("display_name")} for e in state_entities]
    messages = [{key: turn[key] for key in ("turn_id", "role", "content") if key in turn} for turn in surface.get("conversation", [])]
    return {
        "seed_surface_form": {
            "language": surface.get("language"),
            "register": surface.get("register"),
            "conversation": messages,
            "context_turn_count": surface.get("context_turn_count"),
            "user_message": surface.get("user_message"),
        },
        "context_profile": plan["context_profile"],
        "context_text": {
            "messages": [{key: message[key] for key in ("role", "content") if key in message} for message in user_context.get("messages", [])],
            "has_recent_actions": bool(sample["input"].get("recent_actions")),
        },
        "locked_business_facts": {
            "entities": entities,
            "operation": scrub(op),
            "recorded_facts": scrub(facts.get("recorded_facts", [])),
            "supporting_lookup": scrub(facts.get("supporting_lookup_result")),
            "output_type": sample["expected"].get("output_type"),
            "execution_policy": scrub(sample["expected"].get("execution")),
            "expected_diff": _anonymized_expected(sample["expected"].get("expected_diff", []), scenario),
        },
        "locked_expected_output": _anonymized_expected(sample["expected"].get("model_output", {}), scenario),
    }


def build_request(plan: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    run_key = f"{plan['scenario_family_id']}:{plan['seed']}"
    run_id = run_id or "mock-" + hashlib.sha256(run_key.encode()).hexdigest()[:16]
    request_id = "req-" + hashlib.sha256(f"{run_id}:{plan['gold_sample_id']}".encode()).hexdigest()[:20]
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    visible = teacher_visible_anchor(plan)
    visible["variant_plan"] = {
        "style": plan["style"],
        "difficulty": plan["difficulty"],
        "context_profile": plan["context_profile"],
        "variant_instruction": {
            "colloquial": "Rewrite naturally in conversational Chinese while preserving every explicit fact.",
            "typo_asr_like": "Add a minimal realistic ASR-like hesitation/recognition form without changing any entity, amount, date, currency, or intent.",
            "pronoun_ellipsis": "Use a natural pronoun or ellipsis only when the supplied conversation resolves it; keep the same intended facts.",
            "multi_turn": "Preserve the supplied turn count/order/roles and make only a natural wording variation that relies on the existing conversation.",
        }[plan["style"]],
    }
    payload = {
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(visible, ensure_ascii=False, sort_keys=True)},
        ],
        "response_format": {"type": "json_object", "required_top_level": ["surface_form"]},
    }
    return {
        "request_version": "0.1",
        "request_id": request_id,
        "run_id": run_id,
        "provider_mode": "mock_only",
        "local_trace": {
            "scenario_id": plan["scenario_id"],
            "scenario_family_id": plan["scenario_family_id"],
            "family_code": plan["family_code"],
            "gold_sample_id": plan["gold_sample_id"],
            "split_group_id": plan["split_group_id"],
            "seed": plan["seed"],
            "prompt_version": PROMPT_VERSION,
            "generator_version": GENERATOR_VERSION,
            "frozen_hashes": plan["frozen_hashes"],
        },
        "teacher_payload": payload,
    }


def parse_response(response: Any, seed_sample: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict) or set(response) != {"surface_form"}:
        raise GeneratorError("Teacher response must contain only the required surface_form object.")
    surface = response.get("surface_form")
    allowed = {"language", "register", "conversation", "context_turn_count", "user_message"}
    if not isinstance(surface, dict) or set(surface) != allowed:
        raise GeneratorError("surface_form response is incomplete or contains forbidden fields.")
    if surface.get("language") != "zh-CN" or surface.get("register") not in {"neutral", "colloquial", "asr_like", "mixed"}:
        raise GeneratorError("Teacher response uses an unsupported language or register.")
    if not isinstance(surface.get("user_message"), str) or not surface["user_message"].strip():
        raise GeneratorError("Teacher response user_message must be non-empty text.")
    if not isinstance(surface.get("conversation"), list) or not isinstance(surface.get("context_turn_count"), int):
        raise GeneratorError("Teacher response conversation fields are malformed.")
    if surface["context_turn_count"] != len(surface["conversation"]) or len(surface["conversation"]) > 12:
        raise GeneratorError("Teacher response context_turn_count must match the bounded conversation length.")
    source_turns = seed_sample["surface_form"].get("conversation", [])
    if len(surface["conversation"]) != len(source_turns):
        raise GeneratorError("Teacher response must preserve the existing conversation turn count.")
    for index, (turn, source) in enumerate(zip(surface["conversation"], source_turns)):
        if not isinstance(turn, dict) or set(turn) != {"turn_id", "role", "content"}:
            raise GeneratorError(f"Conversation turn {index} has malformed or additional fields.")
        if turn["turn_id"] != source["turn_id"] or turn["role"] != source["role"] or not isinstance(turn["content"], str) or not turn["content"].strip():
            raise GeneratorError(f"Conversation turn {index} changed its identity/role or has empty content.")
    return copy.deepcopy(surface)


def deterministic_mock_response(request: dict[str, Any]) -> dict[str, Any]:
    user_visible = json.loads(request["teacher_payload"]["messages"][1]["content"])
    source = user_visible["seed_surface_form"]
    style = user_visible["variant_plan"]["style"]
    surface = copy.deepcopy(source)
    if style == "colloquial":
        surface["user_message"] = "麻烦帮我记一下，" + source["user_message"].strip()
        surface["register"] = "colloquial"
    elif style == "typo_asr_like":
        surface["user_message"] = "呃，" + source["user_message"].strip()
        surface["register"] = "asr_like"
    elif style == "pronoun_ellipsis":
        surface["user_message"] = "刚才提到的这笔，" + source["user_message"].strip()
        surface["register"] = "colloquial"
    elif style == "multi_turn":
        surface["user_message"] = "接着刚才说的，" + source["user_message"].strip()
        surface["register"] = "colloquial"
    return {"surface_form": surface}


def _validate_no_metadata_in_input(sample: dict[str, Any]) -> None:
    visible_parts: list[str] = []
    metadata_keys = {"scenario_id", "family_id", "sample_id", "dataset_id", "dataset_version", "training_metadata"}

    def collect_visible(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in metadata_keys:
                    visible_parts.append(key)
                elif key not in {"result_id", "result_ids", "verified_result_ids", "action_id"}:
                    collect_visible(child)
        elif isinstance(value, list):
            for child in value:
                collect_visible(child)
        elif isinstance(value, str):
            visible_parts.append(value)

    collect_visible(sample.get("input", {}))
    encoded = "\n".join(visible_parts)
    forbidden = (
        r"\bscenario_[a-z0-9][a-z0-9_-]*\b",
        r"\bfamily_[a-z0-9_-]+\b",
        r"\bsample_[a-z0-9][a-z0-9_-]*\b",
        r"\b[A-Z]{2,6}(?:-[A-Z0-9]+){1,3}-[0-9]{3}\b",
        r"\"(?:scenario|family|sample|dataset)_(?:id|version|metadata)\"\s*:",
        r"\bgold[_ -]?seed\b",
        r"\btraining[_ -]?(?:sample|dataset|metadata)\b",
        r"\bdataset[_ -]?(?:version|id|metadata)\b",
    )
    if any(re.search(pattern, encoded, flags=re.IGNORECASE) for pattern in forbidden):
        raise GeneratorError("Model-visible input contains dataset/family/scenario production metadata.")


def make_candidate(plan: dict[str, Any], request: dict[str, Any], response: Any, provider: str = "mock", model: str = "deterministic-mock-teacher-v1", temperature: float = 0.0, generated_at: str = MOCK_TIME) -> dict[str, Any]:
    surface = parse_response(response, plan["seed_sample"])
    candidate = copy.deepcopy(plan["seed_sample"])
    run_id, request_id = request["run_id"], request["request_id"]
    candidate_id = f"sample_teacher_{hashlib.sha256(run_id.encode()).hexdigest()[:12]}"
    candidate["sample_id"] = candidate_id
    candidate["surface_form"] = surface
    candidate["input"]["user_message"] = surface["user_message"]
    # The prior-turn text is part of the visible Surface Form; retain its IDs,
    # roles, timestamps, bindings, and all other Context Envelope facts.
    input_messages = candidate["input"].get("conversation_context", {}).get("messages", [])
    for input_turn, surface_turn in zip(input_messages, surface["conversation"]):
        if input_turn.get("turn_id") != surface_turn["turn_id"] or input_turn.get("role") != surface_turn["role"]:
            raise GeneratorError("Surface Form turn identity differs from frozen Context Envelope history.")
        input_turn["content"] = surface_turn["content"]
    candidate["example_only"] = True
    candidate["source"] = {
        "surface_form_type": "teacher_generated",
        "generator": f"ai_teacher_generator/{GENERATOR_VERSION}",
        "source_reference": f"run:{run_id}/request:{request_id}/seed:{plan['gold_sample_id']}",
        "teacher": {
            "provider": provider,
            "model": model,
            "generation_run_id": run_id,
            "prompt_version": PROMPT_VERSION,
            "generated_at": generated_at,
            "temperature": temperature,
            "seed": plan["seed"],
        },
    }
    candidate["trust"] = {
        "level": "SILVER",
        "ground_truth_locked": True,
        "surface_form_reviewed": False,
        "validation_evidence": [
            f"Frozen Gold Seed source: {plan['gold_sample_id']}#/expected",
            f"Teacher request: {request_id}; candidate output is not approved and is not training eligible.",
        ],
    }
    candidate["dataset_metadata"]["lifecycle_status"] = "generated"
    candidate["dataset_metadata"]["dedup_key"] = f"sample:teacher:{hashlib.sha256(run_id.encode()).hexdigest()[:24]}"
    normalized = re.sub(r"\s+", " ", surface["user_message"].casefold()).strip()
    norm_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    candidate["dataset_metadata"]["normalization_key"] = f"surface:teacher:{norm_hash}"
    candidate["dataset_metadata"]["review_notes"] = "Generated candidate only; requires independent surface review. Never include mock or unreviewed candidates in training."
    if candidate["expected"] != plan["seed_sample"]["expected"]:
        raise GeneratorError("Candidate Ground Truth drifted from the frozen source Sample.")
    for key in ("scenario_id", "scenario_family_id", "split_group_id", "split"):
        if candidate[key] != plan["seed_sample"][key]:
            raise GeneratorError(f"Candidate changed frozen trace/split field {key}.")
    if candidate["trust"]["level"] == "GOLD" or candidate["dataset_metadata"]["lifecycle_status"] == "approved":
        raise GeneratorError("Teacher candidate cannot be Gold or approved.")
    _validate_no_metadata_in_input(candidate)
    return candidate


def validate_candidate(candidate: dict[str, Any], scenario: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    repo = root or _repo_root()
    assets = frozen_assets(repo)
    validator = DatasetValidator(repo)
    report = validator.validate_dataset([copy.deepcopy(scenario)], [copy.deepcopy(candidate)])
    if not report.valid:
        detail = "; ".join(f"{item.code}: {item.message}" for item in report.errors)
        raise GeneratorError(f"Candidate failed Dataset Validator: {detail}")
    validator._issues = []
    validator._deduplicate([*assets["samples"], copy.deepcopy(candidate)])
    duplicate_report = validator._report({})
    duplicate_errors = duplicate_report.errors
    if duplicate_errors:
        detail = "; ".join(f"{item.code}: {item.message}" for item in duplicate_errors)
        raise GeneratorError(f"Candidate duplicates frozen Gold Seed data: {detail}")
    warnings = [*report.warnings, *duplicate_report.warnings]
    return {
        "valid": True,
        "errors": 0,
        "warnings": len(warnings),
        "warning_codes": sorted({item.code for item in warnings}),
        "statistics": report.statistics,
    }


def run_mock(plan: dict[str, Any], output_dir: Path, root: Path | None = None) -> dict[str, Any]:
    request = build_request(plan)
    response = deterministic_mock_response(request)
    candidate = make_candidate(plan, request, response)
    validation = validate_candidate(candidate, plan["scenario"], root)
    frozen = frozen_assets(root)
    current_hashes = {
        "scenarios_sha256": frozen["scenario_sha256"],
        "samples_sha256": frozen["sample_sha256"],
        "matrix_sha256": frozen["matrix_sha256"],
        **frozen["contract_hashes"],
        "prompt_template_sha256": _sha256(PROMPT_PATH),
    }
    if current_hashes != plan["frozen_hashes"]:
        raise GeneratorError("Frozen Gold Seed changed during the run.")
    manifest = {
        "run_manifest_version": "0.1",
        "run_id": request["run_id"],
        "mode": "mock_dry_run",
        "status": "candidate_validated" if validation["warnings"] == 0 else "candidate_review_required",
        "created_at": MOCK_TIME,
        "generator_version": GENERATOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "training_eligible": False,
        "remote_provider_called": False,
        "source": {
            "scenario_id": plan["scenario_id"],
            "scenario_family_id": plan["scenario_family_id"],
            "gold_sample_id": plan["gold_sample_id"],
            "split_group_id": plan["split_group_id"],
            "frozen_hashes": plan["frozen_hashes"],
        },
        "outputs": {
            "request": "request.json",
            "response": "response.json",
            "candidate_sample": "candidate_sample.json",
        },
        "sha256": {
            "request": hashlib.sha256(_json_bytes(request)).hexdigest(),
            "response": hashlib.sha256(_json_bytes(response)).hexdigest(),
            "candidate_sample": hashlib.sha256(_json_bytes(candidate)).hexdigest(),
        },
        "candidate_validation": validation,
        "candidate_governance": {"trust_level": "SILVER", "lifecycle_status": "generated", "example_only": True},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "request.json", request)
    _write_json(output_dir / "response.json", response)
    _write_json(output_dir / "candidate_sample.json", candidate)
    _write_json(output_dir / "run_manifest.json", manifest)
    return manifest


def validate_candidate_file(candidate_path: Path, scenario_path: Path, root: Path | None = None) -> dict[str, Any]:
    candidate, scenario = _read_json(candidate_path), _read_json(scenario_path)
    if isinstance(scenario, list):
        scenario = next((item for item in scenario if item.get("scenario_id") == candidate.get("scenario_id")), None)
        if scenario is None:
            raise GeneratorError("Scenario index does not contain the Candidate's scenario_id.")
    if not isinstance(scenario, dict):
        raise GeneratorError("Scenario file must contain one Scenario object or an array index.")
    return validate_candidate(candidate, scenario, root)
