"""Offline contract tests for the LM Studio preflight probe."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared_ledger_verifier.local_llm import (
    HTTPResponse,
    LocalLLMClient,
    LocalLLMError,
    _parse_content,
    _response_format,
    _validate_theme,
    run_probe,
)
from shared_ledger_verifier.loader import ScenarioValidationError, load_scenario
from shared_ledger_verifier.models import CreateExpense, TargetedRepayment


def response(value: object, status: int = 200) -> HTTPResponse:
    return HTTPResponse(status, json.dumps(value).encode("utf-8"))


def completion(content: str) -> HTTPResponse:
    return response({
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    })


def simple_scenario() -> dict:
    return {
        "schema_version": 1,
        "scenario_id": "generated_multi_payer_aa",
        "description": "Two payers, three equal beneficiaries.",
        "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
        "participants": ["A", "B", "C"],
        "operations": [{
            "type": "create_expense", "ref": "expense_1", "title": "Meal",
            "amount": "100.0", "currency": "CNY",
            "payments": {"A": "60.0", "B": "40.0"},
            "split_method": "aa", "aa_participants": ["A", "B", "C"],
        }],
    }


def combined_scenario() -> dict:
    return {
        "schema_version": 1,
        "scenario_id": "generated_targeted_repayment",
        "description": "A pays for B, who partially repays A.",
        "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
        "participants": ["A", "B", "C"],
        "operations": [
            {
                "type": "create_expense", "ref": "expense_1", "title": "Tickets",
                "amount": "100.0", "currency": "CNY", "payments": {"A": "100.0"},
                "split_method": "manual", "splits": {"B": "100.0"},
            },
            {
                "type": "targeted_repayment", "ref": "transfer_1",
                "from_participant": "B", "to_participant": "A", "amount": "40.0",
                "currency": "CNY", "target_expense_refs": ["expense_1"],
            },
        ],
    }


class LocalLLMClientTests(unittest.TestCase):
    def test_models_parse_and_select_qwen_with_explicit_override(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append((request, timeout))
            return response({"data": [{"id": "other"}, {"id": "qwen/qwen3.5-9b"}]})

        client = LocalLLMClient(transport=transport, timeout=12)
        ids, status, elapsed = client.models()
        self.assertEqual(ids, ["other", "qwen/qwen3.5-9b"])
        self.assertEqual(status, 200)
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual(client.select_model(ids), "qwen/qwen3.5-9b")
        request, timeout = requests[0]
        self.assertEqual((request.get_method(), request.full_url, timeout),
                         ("GET", "http://127.0.0.1:1234/v1/models", 12.0))
        self.assertNotIn("authorization", {name.lower() for name, _ in request.header_items()})

        explicit = LocalLLMClient(model="qwen3.5-9b", transport=transport)
        self.assertEqual(explicit.select_model(["qwen3.5-9b", "qwen/qwen3.5-9b"]), "qwen3.5-9b")
        with self.assertRaisesRegex(LocalLLMError, "LOCAL_MODEL_NOT_AVAILABLE"):
            LocalLLMClient().select_model(["other"])
        with self.assertRaisesRegex(LocalLLMError, "LOCAL_MODEL_NOT_AVAILABLE"):
            LocalLLMClient().select_model(["qwen3.5-9b", "qwen/qwen3.5-9b"])
        with self.assertRaisesRegex(LocalLLMError, "SCHEMA_MISMATCH"):
            LocalLLMClient(transport=lambda request, timeout: response({"data": [{"name": "missing id"}]})).models()

    def test_chat_and_structured_request_parse_final_message_content(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return completion('{"status":"ok","value":7}')

        client = LocalLLMClient(model="qwen3.5-9b", transport=transport)
        result = client.complete([{"role": "user", "content": "probe"}], max_tokens=128)
        self.assertEqual(_parse_content(result.content), {"status": "ok", "value": 7})
        self.assertEqual(result.usage, {"prompt_tokens": 10, "completion_tokens": 20})
        self.assertEqual(result.http_status, 200)
        self.assertGreaterEqual(result.elapsed_seconds, 0)
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(requests[0].get_method(), "POST")
        payload = json.loads(requests[0].data)
        self.assertEqual(payload["model"], "qwen3.5-9b")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "probe"}])
        self.assertEqual((payload["stream"], payload["temperature"], payload["max_tokens"]),
                         (False, 0, 128))
        self.assertNotIn("response_format", payload)

        fmt = _response_format("probe", {"type": "object"})
        structured = client.complete([{"role": "user", "content": "json"}],
                                     max_tokens=32, response_format=fmt)
        self.assertEqual(_parse_content(structured.content)["value"], 7)
        self.assertEqual(json.loads(requests[1].data)["response_format"], fmt)

    def test_invalid_json_timeout_and_http_error_are_classified_without_echo(self) -> None:
        for body in (b"not json", b"[1,2]", b'{"data":NaN}'):
            with self.subTest(body=body), self.assertRaises(LocalLLMError) as caught:
                LocalLLMClient(transport=lambda request, timeout: HTTPResponse(200, body)).models()
            self.assertIn(caught.exception.category, {"INVALID_JSON", "SCHEMA_MISMATCH"})
        with self.assertRaises(LocalLLMError) as caught:
            _parse_content("```json\n{}\n```")
        self.assertEqual(caught.exception.category, "INVALID_JSON")

        def timeout(request, seconds):
            raise socket.timeout("private timeout details")

        with self.assertRaises(LocalLLMError) as caught:
            LocalLLMClient(transport=timeout).models()
        self.assertEqual(caught.exception.category, "TIMEOUT")
        self.assertNotIn("private", str(caught.exception))

        key = "private-test-token"
        echoed = f"Authorization: Bearer {key}".encode("utf-8")
        with self.assertRaises(LocalLLMError) as caught:
            LocalLLMClient(api_key=key, transport=lambda request, seconds: HTTPResponse(401, echoed)).models()
        self.assertEqual((caught.exception.category, caught.exception.http_status), ("HTTP_ERROR", 401))
        self.assertNotIn(key, str(caught.exception))
        self.assertNotIn("Authorization", str(caught.exception))

        with self.assertRaises(LocalLLMError) as caught:
            LocalLLMClient(transport=lambda request, seconds: HTTPResponse(413, b"context length exceeded")).models()
        self.assertEqual(caught.exception.category, "CONTEXT_TOO_SMALL")

    def test_auth_is_optional_and_only_sent_to_loopback(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return response({"data": []})

        LocalLLMClient(api_key="private-test-token", transport=transport).models()
        headers = {name.lower(): value for name, value in requests[0].header_items()}
        self.assertEqual(headers["authorization"], "Bearer private-test-token")
        with self.assertRaises(LocalLLMError) as caught:
            LocalLLMClient(base_url="http://example.com:1234/v1", api_key="private-test-token")
        self.assertEqual(caught.exception.category, "INVALID_CONFIG")


class ScenarioProbeTests(unittest.TestCase):
    def test_fake_generation_passes_loader_and_theme_for_both_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind, document, expected_types in (
                ("simple", simple_scenario(), (CreateExpense,)),
                ("combined", combined_scenario(), (CreateExpense, TargetedRepayment)),
            ):
                path = root / f"{kind}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                scenario = load_scenario(path)
                self.assertEqual(tuple(type(operation) for operation in scenario.operations), expected_types)
                _validate_theme(path, kind)

            invalid = combined_scenario()
            invalid["operations"][1]["target_expense_refs"] = ["missing_expense"]
            path = root / "invalid.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ScenarioValidationError):
                _validate_theme(path, "combined")

    def test_probe_uses_fake_transport_and_writes_only_safe_artifacts(self) -> None:
        calls = []
        responses = [
            response({"data": [{"id": "qwen/qwen3.5-9b"}]}),
            completion('{"status":"ok"}'),
            completion('{"status":"ok","value":7}'),
            completion(json.dumps(simple_scenario())),
            completion(json.dumps(combined_scenario())),
        ]

        def transport(request, timeout):
            calls.append(request)
            return responses.pop(0)

        secret = "private-test-token"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logic_path = root / "BUSINESS_LOGIC.md"
            logic_path.write_text("Business rules for fake test.", encoding="utf-8")
            output_dir = root / "probe"
            client = LocalLLMClient(api_key=secret, transport=transport)
            with patch("shared_ledger_verifier.local_llm._business_logic_commit", return_value="test-commit"):
                result = run_probe(client=client, output_dir=output_dir, business_logic_path=logic_path)

            self.assertEqual(len(calls), 5)
            self.assertEqual(result["model"], "qwen/qwen3.5-9b")
            self.assertTrue(result["server_reachable"])
            self.assertTrue(result["chat_completion_ok"])
            self.assertTrue(result["structured_output_supported"])
            self.assertTrue(result["simple_scenario_valid"])
            self.assertTrue(result["combined_scenario_valid"])
            self.assertIsNone(result["error_category"])
            self.assertEqual(result["business_logic_commit"], "test-commit")
            self.assertEqual(result["business_logic_characters"], len("Business rules for fake test."))
            self.assertEqual(load_scenario(output_dir / "generated_simple.json").scenario_id,
                             "generated_multi_payer_aa")
            self.assertEqual(load_scenario(output_dir / "generated_combined.json").scenario_id,
                             "generated_targeted_repayment")
            self.assertNotIn(secret, (output_dir / "probe_result.json").read_text(encoding="utf-8"))
            self.assertIn("Business rules for fake test.", json.loads(calls[3].data)["messages"][1]["content"])
            self.assertEqual(json.loads(calls[4].data)["response_format"]["type"], "json_schema")

    def test_invalid_generated_scenario_stops_before_combined_step(self) -> None:
        invalid = simple_scenario()
        invalid["operations"][0]["payments"] = {"A": "60.0", "B": "39.0"}
        responses = [
            response({"data": [{"id": "qwen3.5-9b"}]}),
            completion('{"status":"ok"}'),
            completion('{"status":"ok","value":1}'),
            completion(json.dumps(invalid)),
        ]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logic_path = root / "BUSINESS_LOGIC.md"
            logic_path.write_text("Business rules", encoding="utf-8")
            client = LocalLLMClient(transport=lambda request, timeout: responses.pop(0))
            with patch("shared_ledger_verifier.local_llm._business_logic_commit", return_value="test"):
                result = run_probe(client=client, output_dir=root / "probe", business_logic_path=logic_path)
            self.assertEqual(result["error_category"], "GENERATION_INVALID")
            self.assertFalse(result["simple_scenario_valid"])
            self.assertIsNone(result["combined_scenario_valid"])
            self.assertIn("payment amounts must sum exactly", result["loader_error"])
            self.assertEqual(responses, [])


if __name__ == "__main__":
    unittest.main()
