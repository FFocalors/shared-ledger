from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from shared_ledger_verifier.deepseek import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DeepSeekApiError,
    DeepSeekClient,
    DeepSeekConfigurationError,
    TransportResponse,
)


def completion_response(content: str) -> TransportResponse:
    return TransportResponse(
        200,
        json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8"),
    )


class DeepSeekClientTests(unittest.TestCase):
    def test_complete_posts_chat_messages_and_returns_content(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append((request, timeout))
            return completion_response('{"verdict":"PASS"}')

        client = DeepSeekClient("test-secret", transport=transport)

        result = client.complete("system", "user")

        self.assertEqual(result, '{"verdict":"PASS"}')
        request, timeout = requests[0]
        self.assertEqual(request.full_url, f"{DEFAULT_BASE_URL}/chat/completions")
        self.assertEqual(timeout, 30.0)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["authorization"], "Bearer test-secret")
        self.assertEqual(headers["content-type"], "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["model"], DEFAULT_MODEL)
        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ],
        )
        self.assertFalse(body["stream"])

    def test_opencode_go_headers_are_stable_across_retries_and_format_retry(self) -> None:
        requests = []
        responses = [
            TransportResponse(429, b"rate limit"),
            completion_response("not-json"),
            completion_response('{"verdict":"PASS"}'),
        ]

        def transport(request, timeout):
            requests.append(request)
            return responses.pop(0)

        client = DeepSeekClient(
            "go-test-key",
            base_url="https://opencode.ai/zen/go",
            model="deepseek-v4-flash",
            max_retries=1,
            transport=transport,
        )
        with patch("shared_ledger_verifier.deepseek.time.sleep"):
            self.assertEqual(client.complete("system", "user"), "not-json")
            # A caller-level retry after an invalid verdict is another completion
            # on this same client and therefore remains in the same Go session.
            self.assertEqual(
                client.complete("system", "retry user"),
                '{"verdict":"PASS"}',
            )

        request_headers = [
            {key.lower(): value for key, value in request.header_items()}
            for request in requests
        ]
        self.assertEqual(len(request_headers), 3)
        self.assertTrue(
            all(
                request.full_url == "https://opencode.ai/zen/go/v1/chat/completions"
                for request in requests
            )
        )
        self.assertTrue(
            all(headers["user-agent"] == "shared-ledger-verifier/0.2" for headers in request_headers)
        )
        session_ids = [headers["x-opencode-session"] for headers in request_headers]
        self.assertTrue(session_ids[0].startswith("ses_"))
        self.assertEqual(len(set(session_ids)), 1)

        compatibility_requests = []
        compatibility_client = DeepSeekClient(
            "go-test-key",
            base_url="https://opencode.ai/zen/go/v1",
            model="deepseek-v4-flash",
            transport=lambda request, timeout: (
                compatibility_requests.append(request) or completion_response("ok")
            ),
        )
        self.assertEqual(compatibility_client.complete("system", "user"), "ok")
        self.assertEqual(
            compatibility_requests[0].full_url,
            "https://opencode.ai/zen/go/v1/chat/completions",
        )
        compatibility_headers = {
            key.lower(): value for key, value in compatibility_requests[0].header_items()
        }
        self.assertEqual(compatibility_headers["user-agent"], "shared-ledger-verifier/0.2")
        self.assertTrue(compatibility_headers["x-opencode-session"].startswith("ses_"))

        direct_requests = []
        direct_client = DeepSeekClient(
            "direct-test-key",
            transport=lambda request, timeout: (
                direct_requests.append(request) or completion_response("ok")
            ),
        )
        self.assertEqual(direct_client.complete("system", "user"), "ok")
        direct_headers = {
            key.lower(): value for key, value in direct_requests[0].header_items()
        }
        self.assertNotIn("x-opencode-session", direct_headers)
        self.assertNotIn("user-agent", direct_headers)

    def test_from_env_reads_deepseek_variables_and_uses_official_defaults(self) -> None:
        empty_env_file = Path(tempfile.mkdtemp()) / "missing.env"
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(DeepSeekConfigurationError):
                DeepSeekClient.from_env(env_path=empty_env_file)

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-secret",
                "DEEPSEEK_BASE_URL": "https://proxy.example/v1/",
                "DEEPSEEK_MODEL": "custom-model",
            },
            clear=True,
        ):
            configured = DeepSeekClient.from_env(env_path=empty_env_file)
        self.assertEqual(configured.base_url, "https://proxy.example/v1")
        self.assertEqual(configured.model, "custom-model")

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-secret",
                "DEEPSEEK_BASE_URL": "  ",
                "DEEPSEEK_MODEL": "",
            },
            clear=True,
        ):
            defaults = DeepSeekClient.from_env(env_path=empty_env_file)
        self.assertEqual(defaults.base_url, DEFAULT_BASE_URL)
        self.assertEqual(defaults.model, DEFAULT_MODEL)

    def test_from_env_uses_provider_timeout_defaults_and_honors_override(self) -> None:
        empty_env_file = Path(tempfile.mkdtemp()) / "missing.env"
        received_timeouts = []

        def transport(request, timeout):
            received_timeouts.append(timeout)
            return completion_response("ok")

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-secret",
                "DEEPSEEK_BASE_URL": "https://opencode.ai/zen/go",
                "DEEPSEEK_MODEL": "deepseek-v4.1-flash",
            },
            clear=True,
        ):
            go_client = DeepSeekClient.from_env(
                env_path=empty_env_file,
                transport=transport,
            )
            go_client.complete("system", "user")
            overridden_go_client = DeepSeekClient.from_env(
                env_path=empty_env_file,
                timeout=45.0,
                transport=transport,
            )

        self.assertEqual(received_timeouts, [120.0])
        self.assertEqual(go_client.timeout, 120.0)
        self.assertEqual(overridden_go_client.timeout, 45.0)

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-secret",
                "DEEPSEEK_BASE_URL": "",
                "DEEPSEEK_MODEL": "",
            },
            clear=True,
        ):
            direct_client = DeepSeekClient.from_env(env_path=empty_env_file)
        self.assertEqual(direct_client.timeout, 30.0)

    def test_timeout_env_validation_and_explicit_precedence(self) -> None:
        with patch("shared_ledger_verifier.deepseek.load_local_env"), patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "test", "DEEPSEEK_TIMEOUT_SECONDS": "240"}, clear=True
        ):
            self.assertEqual(DeepSeekClient.from_env().timeout, 240)
            self.assertEqual(DeepSeekClient.from_env(timeout=15).timeout, 15)
            for value in ("0", "-1", "nan", "inf", "bad"):
                os.environ["DEEPSEEK_TIMEOUT_SECONDS"] = value
                with self.subTest(value=value), self.assertRaises(DeepSeekConfigurationError):
                    DeepSeekClient.from_env()
            self.assertEqual(DeepSeekClient.from_env(timeout=15).timeout, 15)

    def test_failure_classification_never_exposes_transport_text(self) -> None:
        for error, expected in ((TimeoutError("private"), "timeout"), (URLError(TimeoutError("private")), "timeout"), (URLError("private"), "network")):
            def transport(request, timeout):
                raise error
            with self.subTest(kind=expected), self.assertRaises(DeepSeekApiError) as caught:
                DeepSeekClient("key", max_retries=0, transport=transport).complete("s", "u")
            self.assertEqual(caught.exception.error_kind, expected)
            self.assertNotIn("private", str(caught.exception))

    def test_retries_429_and_network_errors(self) -> None:
        responses = [TransportResponse(429, b"rate limit"), completion_response("ok")]
        calls = 0

        def transport(request, timeout):
            nonlocal calls
            calls += 1
            return responses.pop(0)

        with patch("shared_ledger_verifier.deepseek.time.sleep"):
            self.assertEqual(DeepSeekClient("key", transport=transport).complete("s", "u"), "ok")
        self.assertEqual(calls, 2)

        attempts = 0

        def flaky_transport(request, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise URLError("temporary network error")
            return completion_response("ok")

        with patch("shared_ledger_verifier.deepseek.time.sleep"):
            self.assertEqual(DeepSeekClient("key", transport=flaky_transport).complete("s", "u"), "ok")
        self.assertEqual(attempts, 2)

    def test_retries_server_errors_only_a_small_number_of_times(self) -> None:
        attempts = 0

        def unavailable(request, timeout):
            nonlocal attempts
            attempts += 1
            return TransportResponse(503, b"server failure")

        with patch("shared_ledger_verifier.deepseek.time.sleep"):
            with self.assertRaises(DeepSeekApiError) as caught:
                DeepSeekClient("key", transport=unavailable).complete("s", "u")
        self.assertEqual(attempts, 3)
        self.assertEqual(caught.exception.status_code, 503)

    def test_http_error_does_not_expose_secret_or_response_body(self) -> None:
        api_key = "private-test-key"
        body = f"echo {api_key} Authorization: Bearer {api_key}".encode("utf-8")
        client = DeepSeekClient(api_key, transport=lambda request, timeout: TransportResponse(401, body))

        with self.assertRaises(DeepSeekApiError) as caught:
            client.complete("s", "u")

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.error_kind, "http")
        self.assertNotIn(api_key, str(caught.exception))
        self.assertNotIn("Authorization", str(caught.exception))

    def test_rejects_invalid_success_payload_without_echoing_it(self) -> None:
        client = DeepSeekClient("key", transport=lambda request, timeout: TransportResponse(200, b"not json"))

        with self.assertRaisesRegex(DeepSeekApiError, "invalid JSON") as caught:
            client.complete("s", "u")
        self.assertEqual(caught.exception.error_kind, "invalid_response")


if __name__ == "__main__":
    unittest.main()
