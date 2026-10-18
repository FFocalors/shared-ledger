import json
import sys
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import probe
from live_provider import ProviderConfig


def config(**overrides):
    values = {
        "provider": "opencode",
        "model": probe.EXPECTED_MODEL,
        "api_key": "test-secret-value",
        "base_url": probe.EXPECTED_ENDPOINT,
        "temperature": 0.1,
    }
    values.update(overrides)
    return ProviderConfig(**values)


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


def canary_envelope(content=None):
    content = content or {
        "schema_version": "t1-teacher-probe-contract-v1",
        "status": "ok",
        "task": "contract-sanity",
        "must_not_call_tools": True,
    }
    return json.dumps({
        "id": "req_synthetic_123",
        "model": "provider-returned-label",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 21, "completion_tokens": 18, "total_tokens": 39, "cost": 0.001},
    }).encode()


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.prompt = {
            "messages": [{"role": "user", "content": "synthetic canary"}],
            "expected_content": {
                "schema_version": "t1-teacher-probe-contract-v1",
                "status": "ok",
                "task": "contract-sanity",
                "must_not_call_tools": True,
            },
        }

    def test_payload_has_hard_output_bound_and_json_mode(self):
        payload = probe.build_payload(config(), self.prompt)
        self.assertLessEqual(payload["max_tokens"], 1024)
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["stream"])

    def test_fake_http_records_identity_without_exposing_secret_in_body(self):
        captured = {}

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["user_agent"] = request.get_header("User-agent")
            captured["session"] = request.get_header("X-opencode-session")
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data)
            return FakeResponse(canary_envelope())

        budget = probe.RequestBudget()
        result = probe.post_once(config(), self.prompt, timeout=60, session_id="synthetic-session", budget=budget, opener=fake_open)
        self.assertEqual(captured["url"], probe.EXPECTED_ENDPOINT)
        self.assertEqual(captured["authorization"], "Bearer test-secret-value")
        self.assertEqual(captured["user_agent"], probe.USER_AGENT)
        self.assertEqual(captured["session"], "synthetic-session")
        self.assertEqual(captured["timeout"], 60)
        self.assertEqual(captured["payload"]["max_tokens"], 256)
        self.assertNotIn("test-secret-value", json.dumps(captured["payload"]))
        self.assertNotIn("test-secret-value", result["raw_response"])
        self.assertEqual(budget.used, 1)

    def test_exact_secret_and_bearer_tokens_are_redacted(self):
        body = '{"message":"bad test-secret-value and Bearer abc123token","token":"token-value"}'
        redacted = probe._redact_text(body, "test-secret-value")
        self.assertNotIn("test-secret-value", redacted)
        self.assertNotIn("abc123token", redacted)
        self.assertNotIn('"token":"token-value"', redacted)

    def test_http_error_keeps_small_sanitized_message_only(self):
        safe_body = json.dumps({"error": {"message": "denied test-secret-value"}}).encode()

        def fake_open(*_, **__):
            raise urllib.error.HTTPError(probe.EXPECTED_ENDPOINT, 403, "Forbidden", {}, BytesIO(safe_body))

        result = probe.post_once(config(), self.prompt, timeout=20, session_id="synthetic-session", budget=probe.RequestBudget(), opener=fake_open)
        self.assertEqual(result["http_status"], 403)
        self.assertIn("denied", result["error"])
        self.assertNotIn("test-secret-value", result["error"])
        self.assertIsNone(result["raw_response"])

    def test_budget_stops_before_third_http_call(self):
        calls = []

        def fake_open(*_, **__):
            calls.append(1)
            return FakeResponse(canary_envelope())

        budget = probe.RequestBudget(max_requests=1)
        probe.post_once(config(), self.prompt, timeout=20, session_id="synthetic-session", budget=budget, opener=fake_open)
        with self.assertRaises(probe.ProbeError):
            probe.post_once(config(), self.prompt, timeout=20, session_id="synthetic-session", budget=budget, opener=fake_open)
        self.assertEqual(len(calls), 1)
        self.assertEqual(budget.used, 1)

    def test_timeout_and_route_mismatch_refuse_without_consuming_budget(self):
        calls = []

        def fake_open(*_, **__):
            calls.append(1)
            return FakeResponse(canary_envelope())

        budget = probe.RequestBudget()
        with self.assertRaises(probe.ProbeError):
            probe.post_once(config(), self.prompt, timeout=60.1, session_id="s", budget=budget, opener=fake_open)
        with self.assertRaises(probe.ProbeError):
            probe.post_once(config(base_url="https://example.invalid"), self.prompt, timeout=30, session_id="s", budget=budget, opener=fake_open)
        self.assertEqual(calls, [])
        self.assertEqual(budget.used, 0)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            probe.strict_json_loads('{"status":"ok","status":"wrong"}')

    def test_contract_canary_schema_and_usage_are_independently_readable(self):
        parsed, metadata = probe.inspect_envelope(canary_envelope().decode())
        self.assertTrue(probe.validate_sanity(parsed, self.prompt["expected_content"]))
        self.assertEqual(metadata["finish_reason"], "stop")
        self.assertEqual(metadata["server_request_id"], "req_synthetic_123")
        self.assertEqual(metadata["usage"]["total_tokens"], 39)
        self.assertEqual(metadata["provider_returned_model_label"], "provider-returned-label")


if __name__ == "__main__":
    unittest.main()
