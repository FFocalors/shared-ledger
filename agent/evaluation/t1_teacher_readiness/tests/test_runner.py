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
    {"case_id": "ordinary-prepay-denial", "task_conclusion": "reject_unsupported"},
    {"case_id": "expense-create-conservation", "task_conclusion": "stage_expense_create"},
    {"case_id": "locked-note-presentation", "task_conclusion": "presentation_only"},
]


def config(**overrides):
    values = {
        "provider": "opencode",
        "model": runner.EXPECTED_MODEL,
        "api_key": "synthetic-secret-42",
        "base_url": runner.EXPECTED_ENDPOINT,
        "temperature": 0.1,
    }
    values.update(overrides)
    return ProviderConfig(**values)


def content_object():
    return {"cases": [
        {"case_id": "ordinary-prepay-denial", "task_conclusion": "reject_unsupported", "visible_text": "普通活动不支持预存，我不能将它改成支出或结算。"},
        {"case_id": "expense-create-conservation", "task_conclusion": "stage_expense_create", "visible_text": "我会按总额84元、A付50元、B付34元准备，并由A、B、C均分。"},
        {"case_id": "locked-note-presentation", "task_conclusion": "presentation_only", "visible_text": "可只准备把备注改成车票；金额、付款人和分摊仍锁定，尚未修改。"},
    ]}


def response_body(*, hidden_reasoning="private hidden chain", content=None, finish_reason="stop", usage=None):
    message = {"content": json.dumps(content if content is not None else content_object(), ensure_ascii=False)}
    if hidden_reasoning is not None:
        message["reasoning_content"] = hidden_reasoning
    return json.dumps({
        "id": "req_synthetic_readiness_01",
        "model": runner.EXPECTED_MODEL,
        "choices": [{"finish_reason": finish_reason, "message": message}],
        "usage": usage or {"prompt_tokens": 400, "completion_tokens": 170, "total_tokens": 570},
    }, ensure_ascii=False).encode("utf-8")


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


def prompt():
    return {"messages": [{"role": "user", "content": "synthetic only"}]}


class ReadinessRunnerTests(unittest.TestCase):
    def test_payload_has_exact_2048_output_ceiling_and_json_mode(self):
        payload = runner.build_payload(config(), prompt())
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["stream"])
        self.assertEqual(runner.MAX_RESPONSE_BYTES, 256_000)
        self.assertEqual(runner.TIMEOUT_SECONDS, 60.0)

    def test_fake_http_stable_identity_and_allowlisted_response_omit_hidden_text(self):
        capture = {}

        def fake_open(request, timeout):
            capture["url"] = request.full_url
            capture["authorization"] = request.get_header("Authorization")
            capture["user_agent"] = request.get_header("User-agent")
            capture["session"] = request.get_header("X-opencode-session")
            capture["timeout"] = timeout
            capture["payload"] = json.loads(request.data)
            return FakeResponse(response_body())

        budget = runner.RequestBudget()
        result = runner.post_once(config(), prompt(), session_id="synthetic-stable-session", budget=budget, opener=fake_open)
        self.assertEqual(capture["url"], runner.EXPECTED_ENDPOINT)
        self.assertEqual(capture["authorization"], "Bearer synthetic-secret-42")
        self.assertEqual(capture["user_agent"], runner.USER_AGENT)
        self.assertEqual(capture["session"], "synthetic-stable-session")
        self.assertEqual(capture["timeout"], 60.0)
        self.assertEqual(capture["payload"]["max_tokens"], 2048)
        self.assertNotIn("synthetic-secret-42", json.dumps(capture["payload"]))
        safe_result = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("private hidden chain", safe_result)
        self.assertTrue(result["reasoning_content_field_present"])
        self.assertFalse(result["response_body_saved"])
        self.assertEqual(budget.used, 1)

    def test_strict_candidate_schema_matches_exact_three_ordered_cases(self):
        result = runner.validate_candidate(content_object(), EXPECTED)
        self.assertTrue(result["schema_valid"])
        self.assertTrue(result["task_conclusions_match"])
        self.assertTrue(result["visible_text_valid"])
        self.assertTrue(result["no_completed_write_claim"])
        self.assertTrue(result["manual_semantic_review_required"])

    def test_consumer_persists_only_validated_candidate_texts(self):
        result = runner.consume_visible_content({"visible_content": json.dumps(content_object(), ensure_ascii=False)}, EXPECTED)
        self.assertNotIn("visible_content", result)
        self.assertEqual(len(result["candidate"]["cases"]), 3)
        self.assertEqual(set(result["candidate_text_sha256"]), {case["case_id"] for case in EXPECTED})

    def test_consumer_discards_unstructured_visible_text(self):
        result = runner.consume_visible_content({"visible_content": "untrusted arbitrary text"}, EXPECTED)
        self.assertNotIn("visible_content", result)
        self.assertNotIn("untrusted arbitrary text", json.dumps(result))
        self.assertNotIn("candidate", result)

    def test_reordered_or_extra_cases_fail_contract(self):
        value = content_object()
        value["cases"].reverse()
        self.assertFalse(runner.validate_candidate(value, EXPECTED)["schema_valid"])
        value = content_object()
        value["extra"] = True
        self.assertFalse(runner.validate_candidate(value, EXPECTED)["schema_valid"])

    def test_completed_write_claim_is_rejected(self):
        value = content_object()
        value["cases"][1]["visible_text"] = "支出已创建成功。"
        result = runner.validate_candidate(value, EXPECTED)
        self.assertFalse(result["no_completed_write_claim"])

    def test_one_request_budget_stops_second_call_before_network(self):
        calls = []

        def fake_open(*_, **__):
            calls.append(1)
            return FakeResponse(response_body())

        budget = runner.RequestBudget(limit=1)
        runner.post_once(config(), prompt(), session_id="one", budget=budget, opener=fake_open)
        with self.assertRaises(runner.ReadinessError):
            runner.post_once(config(), prompt(), session_id="one", budget=budget, opener=fake_open)
        self.assertEqual(calls, [1])
        self.assertEqual(budget.used, 1)

    def test_http_error_body_is_only_a_small_redacted_message(self):
        body = json.dumps({"error": {"message": "denied synthetic-secret-42"}}).encode()

        def fake_open(*_, **__):
            raise urllib.error.HTTPError(runner.EXPECTED_ENDPOINT, 403, "Forbidden", {}, BytesIO(body))

        result = runner.post_once(config(api_key="synthetic-secret-42"), prompt(), session_id="s", budget=runner.RequestBudget(), opener=fake_open)
        self.assertEqual(result["http_status"], 403)
        self.assertIn("denied", result["error"])
        self.assertNotIn("synthetic-secret-42", json.dumps(result))
        self.assertFalse(result["response_body_saved"])

    def test_response_byte_limit_is_enforced_without_saving_body(self):
        body = b"{" + b" " * runner.MAX_RESPONSE_BYTES

        def fake_open(*_, **__):
            return FakeResponse(body)

        result = runner.post_once(config(), prompt(), session_id="s", budget=runner.RequestBudget(), opener=fake_open)
        self.assertEqual(result["response_body_bytes"], runner.MAX_RESPONSE_BYTES + 1)
        self.assertIn("byte limit", result["error"])
        self.assertFalse(result["response_body_saved"])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            runner.strict_json_loads('{"cases":[],"cases":[]}')


if __name__ == "__main__":
    unittest.main()
