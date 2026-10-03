import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ai_teacher_generator"))

from live_provider import (  # noqa: E402
    ADAPTER_VERSION,
    USER_AGENT,
    LiveProviderError,
    ProviderConfig,
    load_env,
    parse_completion,
    request_completion,
)


class LiveProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = ProviderConfig("openai-compatible", "model-test", "secret-test-value", "https://example.invalid/v1", 0.0)
        self.request = {"teacher_payload": {"messages": [{"role": "system", "content": "prompt"}, {"role": "user", "content": "facts"}]}}

    def test_configuration_loads_without_logging_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "TEACHER_PROVIDER=openai-compatible\nTEACHER_MODEL=m\nTEACHER_API_KEY=secret-test-value\nTEACHER_BASE_URL=https://example.invalid/v1\nTEACHER_TEMPERATURE=0\n",
                encoding="utf-8",
            )
            config = load_env(path)
            self.assertEqual(config.api_key, "secret-test-value")
            self.assertEqual(config.temperature, 0.0)

    @patch("live_provider.urllib.request.urlopen")
    def test_success_uses_secret_only_in_header_and_never_returns_headers(self, open_url):
        response_body = json.dumps({"choices": [{"message": {"content": '{"surface_form":{}}'}}]}).encode()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = response_body
        open_url.side_effect = [response, response]
        self.request["local_trace"] = {"opencode_session_id": "opencode-session-test"}
        result = request_completion(self.config, self.request)
        request_obj = open_url.call_args.args[0]
        self.assertEqual(request_obj.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(request_obj.get_header("Authorization"), "Bearer secret-test-value")
        self.assertEqual(request_obj.get_header("User-agent"), USER_AGENT)
        self.assertEqual(request_obj.get_header("X-opencode-session"), "opencode-session-test")
        self.assertEqual(ADAPTER_VERSION, "0.1.2")
        self.assertNotIn("secret-test-value", result["raw_response"])
        self.assertFalse(result["headers_recorded"])
        request_completion(self.config, self.request)
        second_request = open_url.call_args.args[0]
        self.assertEqual(second_request.get_header("X-opencode-session"), request_obj.get_header("X-opencode-session"))

    def test_opencode_zen_base_resolves_to_documented_go_chat_endpoint(self):
        config = ProviderConfig("opencode", "deepseek-v4.1-flash", "secret", "https://opencode.ai/zen/go", 0.0)
        with patch("live_provider.urllib.request.urlopen") as open_url:
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.status = 200
            response.__enter__.return_value.read.return_value = b'{"choices":[]}'
            open_url.return_value = response
            request_completion(config, self.request)
            self.assertEqual(open_url.call_args.args[0].full_url, "https://opencode.ai/zen/go/v1/chat/completions")

    def test_opencode_complete_endpoint_is_not_extended_again(self):
        endpoint = "https://opencode.ai/zen/go/v1/chat/completions"
        config = ProviderConfig("opencode", "deepseek-v4.1-flash", "secret", endpoint, 0.0)
        with patch("live_provider.urllib.request.urlopen") as open_url:
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.status = 200
            response.__enter__.return_value.read.return_value = b'{"choices":[]}'
            open_url.return_value = response
            request_completion(config, self.request)
            self.assertEqual(open_url.call_args.args[0].full_url, endpoint)

    @patch("live_provider.urllib.request.urlopen")
    def test_transient_http_error_is_retryable_and_secret_redacted(self, open_url):
        body = b'{"message":"secret-test-value"}'
        error = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            "https://example.invalid", 503, "unavailable", {}, io.BytesIO(body)
        )
        open_url.side_effect = error
        with self.assertRaises(LiveProviderError) as raised:
            request_completion(self.config, self.request)
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("secret-test-value", str(raised.exception))

    def test_completion_parser_extracts_json_and_usage_and_rejects_bad_envelopes(self):
        parsed, usage = parse_completion(json.dumps({
            "choices": [{"message": {"content": '{"surface_form":{"user_message":"ok"}}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }))
        self.assertEqual(parsed["surface_form"]["user_message"], "ok")
        self.assertEqual(usage["total_tokens"], 18)
        with self.assertRaises(LiveProviderError):
            parse_completion("not-json")
        with self.assertRaises(LiveProviderError):
            parse_completion('{"choices":[]}')


if __name__ == "__main__":
    unittest.main()
