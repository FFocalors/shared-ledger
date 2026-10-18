import json
import sys
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import runner
from live_provider import ProviderConfig


EXPECTED = [
    {"case_id": "activity-meadow-prepay", "task_conclusion": "reject_prepaid_activity"},
    {"case_id": "expense-tea-84-two-payers", "task_conclusion": "stage_expense_create"},
    {"case_id": "expense-locked-memo", "task_conclusion": "presentation_only_memo"},
]


def config(**overrides):
    values = {
        "provider": "opencode",
        "model": runner.EXPECTED_MODEL,
        "api_key": "synthetic-secret-42",
        "base_url": runner.EXPECTED_ENDPOINT,
        "temperature": 0.0,
    }
    values.update(overrides)
    return ProviderConfig(**values)


def candidate(*, text="候选回复内容" * 13):
    return {"cases": [
        {**EXPECTED[0], "visible_text": text},
        {**EXPECTED[1], "visible_text": text},
        {**EXPECTED[2], "visible_text": text},
    ]}


def envelope(content=None, *, raw_content=None, finish_reason="stop", usage=None, model=None, hidden_reasoning="private hidden chain", request_id="req_synthetic_v2_01"):
    message = {"content": raw_content if raw_content is not None else json.dumps(content if content is not None else candidate(), ensure_ascii=False)}
    if hidden_reasoning is not None:
        message["reasoning_content"] = hidden_reasoning
    return json.dumps({
        "id": request_id,
        "model": model or runner.EXPECTED_MODEL,
        "choices": [{"finish_reason": finish_reason, "message": message}],
        "usage": usage or {"prompt_tokens": 428, "completion_tokens": 180, "total_tokens": 608, "reasoning_tokens": 0},
    }, ensure_ascii=False).encode("utf-8")


def transport(body, *, http_status=200):
    return {"http_status": http_status, "duration_seconds": 0.125, "response_body_bytes": len(body)}


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit=-1):
        return self.body[:limit]


class TeacherReadinessV2Tests(unittest.TestCase):
    def test_synthetic_legacy_400_char_slice_turns_valid_json_into_parse_failure(self):
        fixture = {"cases": [
            {"id": "ordinary_activity_prepayment", "conclusion": "reject", "reason_code": "PREPAYMENT_FORBIDDEN", "text": "合成候选文字" * 13},
            {"id": "two_payer_equal_expense", "conclusion": "accept", "reason_code": "AMOUNTS_BALANCE", "text": "合成候选文字" * 13},
            {"id": "locked_expense_memo_presentation", "conclusion": "memo_only", "reason_code": "LOCKED_RECORD_PRESENTATION", "text": "合成候选文字" * 13},
        ]}
        synthetic = json.dumps(fixture, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(len(synthetic), 569)
        self.assertEqual([len(case["text"]) for case in fixture["cases"]], [78, 78, 78])
        self.assertEqual(runner.strict_json_loads(synthetic), fixture)
        with self.assertRaises(json.JSONDecodeError):
            runner.strict_json_loads(synthetic[:400])

    def test_valid_strict_json_over_400_chars_is_preserved_and_accepted(self):
        content = json.dumps(candidate(), ensure_ascii=False, separators=(",", ":"))
        self.assertGreater(len(content), 400)
        self.assertTrue(all(len(item["visible_text"]) <= 80 for item in candidate()["cases"]))
        parsed = runner.strict_json_loads(content)
        self.assertTrue(runner.validate_candidate(parsed, EXPECTED)["schema_valid"])
        body = envelope(raw_content=content)
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "TEXT_CANDIDATE_SCHEMA_READY")
        self.assertEqual(result["visible_content_character_count"], len(content))
        self.assertTrue(result["completion_strict_json_valid"])
        self.assertTrue(result["reasoning_content_field_present"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("private hidden chain", serialized)
        self.assertNotIn("visible_content_truncated", serialized)

    def test_exact_credential_echo_quarantines_without_saving_secret_or_candidate(self):
        secret = "synthetic-secret-42"
        body = envelope(raw_content=json.dumps({"cases": [], "note": secret}, ensure_ascii=False))
        result = runner.process_success_response(transport(body), body, secret=secret, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "QUARANTINED_EXACT_SECRET_ECHO")
        self.assertEqual(result["detection_types"], ["exact_credential_echo"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("candidate", result)
        self.assertFalse(result["response_body_saved"])

    def test_json_escaped_exact_secret_in_hidden_field_is_also_quarantined(self):
        secret = "synthetic-secret-42"
        body = envelope(hidden_reasoning=secret).replace(secret.encode(), b"\\u0073ynthetic-secret-42")
        self.assertNotIn(secret.encode(), body)
        result = runner.process_success_response(transport(body), body, secret=secret, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "QUARANTINED_EXACT_SECRET_ECHO")
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("candidate", result)

    def test_malformed_visible_json_is_rejected_without_echoing_completion(self):
        body = envelope(raw_content="{malformed private completion")
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "INVALID_COMPLETION_JSON")
        self.assertFalse(result["completion_strict_json_valid"])
        self.assertNotIn("malformed private completion", json.dumps(result))

    def test_duplicate_json_object_key_is_rejected(self):
        body = envelope(raw_content='{"cases":[],"cases":[]}')
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "INVALID_COMPLETION_JSON")

    def test_duplicate_case_id_fails_the_candidate_contract(self):
        value = candidate()
        value["cases"][1]["case_id"] = value["cases"][0]["case_id"]
        body = envelope(value)
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "CANDIDATE_CONTRACT_FAILED")
        self.assertFalse(result["validation"]["schema_valid"])
        self.assertNotIn("candidate", result)

    def test_text_over_80_characters_fails_contract(self):
        body = envelope(candidate(text="超长合成回复" * 14))
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "CANDIDATE_CONTRACT_FAILED")
        self.assertFalse(result["validation"]["visible_text_valid"])
        self.assertNotIn("candidate", result)

    def test_allowlisted_metadata_is_recorded_but_hidden_reasoning_value_is_not(self):
        usage = {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46, "reasoning_tokens": 3}
        body = envelope(usage=usage, hidden_reasoning="synthetic private reasoning");
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["server_request_id"], "req_synthetic_v2_01")
        self.assertTrue(result["provider_returned_model_matches_expected"])
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"], usage)
        self.assertTrue(result["reasoning_content_field_present"])
        self.assertNotIn("synthetic private reasoning", json.dumps(result))
        self.assertFalse(result["reasoning_content_value_saved"])

    def test_token_pattern_is_classified_by_name_without_persisting_value(self):
        token = "sk-" + "A" * 24
        body = envelope(raw_content=json.dumps({"cases": [], "note": token}, ensure_ascii=False))
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "QUARANTINED_TOKEN_PATTERN")
        self.assertEqual(result["detection_types"], ["openai_style_token_pattern"])
        self.assertNotIn(token, json.dumps(result))
        self.assertNotIn("candidate", result)

    def test_json_escaped_token_pattern_is_classified_without_value(self):
        token = "sk-" + "A" * 24
        body = envelope(hidden_reasoning=token).replace(b"sk-", b"s\\u006b-")
        self.assertNotIn(token.encode(), body)
        result = runner.process_success_response(transport(body), body, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "QUARANTINED_TOKEN_PATTERN")
        self.assertEqual(result["detection_types"], ["openai_style_token_pattern"])
        self.assertNotIn(token, json.dumps(result))

    def test_error_message_redaction_and_400_limit_apply_only_to_errors(self):
        long_error = "denied " + "x" * 500 + " synthetic-secret-42 " + "Bearer " + "B" * 24
        safe, detections = runner.bounded_error_message(long_error, "synthetic-secret-42")
        self.assertEqual(len(safe), 400)
        self.assertIn("exact_credential_echo", detections)
        self.assertIn("bearer_token_pattern", detections)
        self.assertNotIn("synthetic-secret-42", safe)
        self.assertNotIn("Bearer " + "B" * 24, safe)

    def test_fake_http_uses_fixed_route_limits_and_stable_request_identity(self):
        capture = {}

        def fake_open(request, timeout):
            capture["url"] = request.full_url
            capture["authorization"] = request.get_header("Authorization")
            capture["user_agent"] = request.get_header("User-agent")
            capture["session"] = request.get_header("X-opencode-session")
            capture["timeout"] = timeout
            capture["payload"] = json.loads(request.data)
            return FakeResponse(envelope())

        budget = runner.RequestBudget()
        details, body = runner.post_once(config(), load_prompt_for_test(), session_id="synthetic-stable-session", budget=budget, opener=fake_open)
        self.assertEqual(capture["url"], runner.EXPECTED_ENDPOINT)
        self.assertEqual(capture["authorization"], "Bearer synthetic-secret-42")
        self.assertEqual(capture["user_agent"], runner.USER_AGENT)
        self.assertEqual(capture["session"], "synthetic-stable-session")
        self.assertEqual(capture["timeout"], 60.0)
        self.assertEqual(capture["payload"]["max_tokens"], 2048)
        self.assertEqual(details["response_body_bytes"], len(body))
        self.assertEqual(budget.used, 1)

    def test_one_request_budget_blocks_second_fake_before_network(self):
        calls = []

        def fake_open(*_, **__):
            calls.append(1)
            return FakeResponse(envelope())

        budget = runner.RequestBudget(limit=1)
        runner.post_once(config(), load_prompt_for_test(), session_id="one", budget=budget, opener=fake_open)
        with self.assertRaises(runner.ReadinessError):
            runner.post_once(config(), load_prompt_for_test(), session_id="one", budget=budget, opener=fake_open)
        self.assertEqual(calls, [1])

    def test_oversize_response_is_rejected_without_retaining_body(self):
        raw = b"x" * (runner.MAX_RESPONSE_BYTES + 1)
        result = runner.process_success_response(transport(raw), raw, secret=config().api_key, expected_cases=EXPECTED)
        self.assertEqual(result["status"], "RESPONSE_BYTE_LIMIT_EXCEEDED")
        self.assertFalse(result["response_body_saved"])
        self.assertNotIn("candidate", result)

    def test_http_error_excerpt_is_redacted_and_bounded(self):
        raw = json.dumps({"error": {"message": "denied synthetic-secret-42"}}).encode()
        transport_meta = transport(raw, http_status=403)
        result = runner.process_http_failure(transport_meta, raw, secret="synthetic-secret-42")
        self.assertEqual(result["http_status"], 403)
        self.assertIn("denied", result["error_message"])
        self.assertNotIn("synthetic-secret-42", json.dumps(result))
        self.assertFalse(result["response_body_saved"])

    def test_json_escaped_secret_in_http_error_is_omitted(self):
        secret = "synthetic-secret-42"
        raw = json.dumps({"error": {"message": secret}}).encode().replace(secret.encode(), b"\\u0073ynthetic-secret-42")
        result = runner.process_http_failure(transport(raw, http_status=403), raw, secret=secret)
        self.assertEqual(result["status"], "QUARANTINED_SENSITIVE_HTTP_ERROR")
        self.assertEqual(result["error_message"], "[SENSITIVE_ERROR_OMITTED]")
        self.assertNotIn(secret, json.dumps(result))


def load_prompt_for_test():
    return runner.load_prompt()


if __name__ == "__main__":
    unittest.main()
