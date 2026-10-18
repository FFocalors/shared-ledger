"""Run a real local Supabase Auth smoke against an isolated Agent process.

Secrets are read/generated in memory only. Evidence records response statuses,
opaque user UUIDs, boolean checks, and a digest of frozen Agent source inputs.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


AGENT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AGENT_ROOT.parent
DEFAULT_SUPABASE_WORKDIR = REPO_ROOT.with_name("shared-ledger")


class SmokeFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code


class HttpResult:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    handler_order = 490

    def redirect_request(self, request: Any, file_pointer: Any, code: int,
                         message: str, headers: Any, new_url: str) -> None:
        return None

    def http_error_301(self, request: Any, file_pointer: Any, code: int,
                       message: str, headers: Any) -> None:
        raise urllib.error.HTTPError(request.full_url, code, message, headers, file_pointer)

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _http(method: str, url: str, *, api_key: str | None = None,
          bearer: str | None = None, body: dict[str, Any] | None = None,
          timeout: float = 5.0) -> HttpResult:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["apikey"] = api_key
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    raw = b""
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read(262_145)
    except urllib.error.HTTPError as error:
        status = int(error.code)
        try:
            raw = error.read(262_145)
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise SmokeFailure("loopback_http_unavailable") from None
    if len(raw) > 262_144:
        return HttpResult(status, None)
    if not raw:
        return HttpResult(status, None)
    try:
        payload = json.loads(raw)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        payload = None
    return HttpResult(status, payload)


def _api_error_code(result: HttpResult) -> str | None:
    if isinstance(result.payload, dict):
        value = result.payload.get("code")
        if isinstance(value, str) and len(value) <= 80:
            return value
    return None


def _record(evidence: dict[str, Any], name: str, passed: bool, **details: Any) -> None:
    evidence["checks"].append({
        "name": name,
        "status": "PASS" if passed else "FAIL",
        **details,
    })


def _supabase_config(workdir: Path) -> tuple[str, str, str, str]:
    cli = shutil.which("supabase")
    if not cli:
        raise SmokeFailure("supabase_cli_unavailable")
    try:
        completed = subprocess.run(
            [cli, "status", "--workdir", str(workdir), "--output", "json"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if completed.returncode != 0:
            raise SmokeFailure("supabase_status_unavailable")
        status = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        raise SmokeFailure("supabase_status_unavailable") from None
    if not isinstance(status, dict):
        raise SmokeFailure("supabase_status_unavailable")
    api_url = status.get("API_URL")
    api_key = status.get("ANON_KEY") or status.get("PUBLISHABLE_KEY")
    cleanup_key = status.get("SERVICE_ROLE_KEY")
    if not all(isinstance(value, str) and value for value in (api_url, api_key, cleanup_key)):
        raise SmokeFailure("local_auth_credentials_unavailable")
    parsed = urlsplit(api_url)
    try:
        is_loopback = bool(parsed.hostname and ipaddress.ip_address(parsed.hostname).is_loopback)
        _ = parsed.port
    except ValueError:
        is_loopback = False
    if (parsed.scheme != "http" or not is_loopback or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise SmokeFailure("auth_endpoint_not_loopback_http")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    key_kind = "anon" if status.get("ANON_KEY") else "publishable"
    return origin, api_key, cleanup_key, key_kind


def _create_and_login(owner: str, auth_url: str, api_key: str,
                      evidence: dict[str, Any], secret_values: list[str],
                      created_user_ids: list[tuple[str, str]]) -> dict[str, str]:
    email = f"p1-real-auth-{owner.lower()}-{uuid.uuid4().hex}@example.test"
    password = secrets.token_urlsafe(32)
    secret_values.extend((email, password))
    created = _http("POST", auth_url + "/signup", api_key=api_key,
                    body={"email": email, "password": password})
    _record(evidence, f"auth.signup_{owner}", created.status in (200, 201),
            http_status=created.status)
    payload = created.payload if isinstance(created.payload, dict) else {}
    signup_refresh_token = payload.get("refresh_token")
    if isinstance(signup_refresh_token, str) and signup_refresh_token:
        secret_values.append(signup_refresh_token)
    user = payload.get("user") if isinstance(payload.get("user"), dict) else payload
    user_id_raw = user.get("id") if isinstance(user, dict) else None
    try:
        user_id = str(uuid.UUID(str(user_id_raw)))
    except (ValueError, TypeError, AttributeError):
        raise SmokeFailure(f"signup_user_id_missing_{owner.lower()}") from None
    created_user_ids.append((owner, user_id))
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise SmokeFailure(f"signup_session_missing_{owner.lower()}")
    secret_values.append(access_token)
    signed_out = _http("POST", auth_url + "/logout", api_key=api_key,
                       bearer=access_token, body={})
    _record(evidence, f"auth.signup_session_logout_{owner}", signed_out.status in (200, 204),
            http_status=signed_out.status)
    del access_token

    login = _http("POST", auth_url + "/token?grant_type=password", api_key=api_key,
                  body={"email": email, "password": password})
    _record(evidence, f"auth.password_login_{owner}", login.status == 200,
            http_status=login.status)
    session = login.payload if isinstance(login.payload, dict) else {}
    login_refresh_token = session.get("refresh_token")
    if isinstance(login_refresh_token, str) and login_refresh_token:
        secret_values.append(login_refresh_token)
    token = session.get("access_token")
    if not isinstance(token, str) or not token:
        raise SmokeFailure(f"password_login_session_missing_{owner.lower()}")
    secret_values.append(token)
    verified = _http("GET", auth_url + "/user", api_key=api_key, bearer=token)
    verified_user = verified.payload if isinstance(verified.payload, dict) else {}
    matches = verified.status == 200 and verified_user.get("id") == user_id
    _record(evidence, f"auth.user_endpoint_{owner}", matches,
            http_status=verified.status, user_id_matches=matches, user_id=user_id)
    if not matches:
        raise SmokeFailure(f"auth_user_verification_failed_{owner.lower()}")
    return {"user_id": user_id, "email": email, "password": password, "token": token}


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _source_digest() -> str:
    digest = hashlib.sha256()
    roots = (AGENT_ROOT / "app", AGENT_ROOT / "contracts", AGENT_ROOT / "migrations")
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file()
                         and "__pycache__" not in path.parts and path.suffix != ".pyc")
    files.extend(path for path in (AGENT_ROOT / "pyproject.toml", AGENT_ROOT / "uv.lock")
                 if path.is_file())
    for path in sorted(files, key=lambda item: item.relative_to(AGENT_ROOT).as_posix()):
        digest.update(path.relative_to(AGENT_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _stop_process(process: subprocess.Popen[Any] | None) -> bool:
    if process is None:
        return True
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return False
    return process.poll() is not None


def _scan_temp_files(root: Path, secrets_to_find: list[str]) -> bool:
    files = [path for path in root.rglob("*") if path.is_file()]
    contents = b"".join(path.read_bytes() for path in files)
    return not any(value.encode("utf-8") in contents for value in secrets_to_find if value)


def _write_evidence(evidence: dict[str, Any], destination: Path,
                    sensitive_values: list[str]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    jwt_like = "eyJ" in serialized and serialized.count(".") >= 2
    no_secret_values = not any(value and value in serialized for value in sensitive_values)
    _record(evidence, "credential_non_disclosure", no_secret_values and not jwt_like,
            no_secret_values=no_secret_values, jwt_like_value_absent=not jwt_like)
    evidence["overall"] = (
        "PASS" if "failure_code" not in evidence
        and all(item["status"] == "PASS" for item in evidence["checks"])
        and evidence.get("agent_process_stopped") is True
        and evidence.get("agent_temp_removed") is True
        else "FAIL"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "overall": evidence["overall"],
        "evidence": destination.name,
        "checks": len(evidence["checks"]),
        "failed_checks": [item["name"] for item in evidence["checks"] if item["status"] != "PASS"],
    }, ensure_ascii=False, separators=(",", ":")))


def run(supabase_workdir: Path, evidence_path: Path) -> int:
    evidence: dict[str, Any] = {
        "schema": "shared-ledger-agent/p1-real-auth-smoke/v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "auth_endpoint": "local_loopback_only",
            "agent_http": "127.0.0.1_only",
            "agent_storage": "temporary_isolated_sqlite",
            "provider_mode": "disabled",
            "agent_enabled": False,
        },
        "checks": [],
        "expired_token": {
            "status": "NOT_TESTED",
            "reason": "no safely Auth-issued expired token available without changing Auth settings or waiting for token expiry",
        },
    }
    process: subprocess.Popen[Any] | None = None
    temp: tempfile.TemporaryDirectory[str] | None = None
    temp_path: Path | None = None
    users: dict[str, dict[str, str]] = {}
    created_user_ids: list[tuple[str, str]] = []
    sensitive_values: list[str] = []
    source_before = _source_digest()
    api_key = cleanup_key = auth_url = ""
    try:
        origin, api_key, cleanup_key, key_kind = _supabase_config(supabase_workdir)
        sensitive_values.extend((api_key, cleanup_key))
        evidence["supabase_origin"] = origin
        evidence["agent_api_key_kind"] = key_kind
        auth_url = origin + "/auth/v1"
        health = _http("GET", auth_url + "/health", api_key=api_key)
        _record(evidence, "auth.local_health", health.status == 200,
                http_status=health.status,
                auth_version=(health.payload.get("version") if isinstance(health.payload, dict) else None))
        if health.status != 200:
            raise SmokeFailure("local_auth_not_healthy")

        for owner in ("A", "B"):
            user = _create_and_login(owner, auth_url, api_key, evidence, sensitive_values, created_user_ids)
            users[owner] = user


        temp = tempfile.TemporaryDirectory(prefix="shared-ledger-real-auth-")
        temp_path = Path(temp.name)
        storage_path = temp_path / "agent.sqlite3"
        port = _free_loopback_port()
        agent_origin = f"http://127.0.0.1:{port}"
        runtime_env = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("AGENT_")}
        runtime_env.update({
            "AGENT_STORAGE_PATH": str(storage_path),
            "AGENT_LISTEN_HOST": "127.0.0.1",
            "AGENT_LISTEN_PORT": str(port),
            "AGENT_PROVIDER_MODE": "disabled",
            "AGENT_AGENT_ENABLED": "false",
            "AGENT_DISABLE_REVISION": "1",
            "AGENT_SUPABASE_AUTH_BASE_URL": origin,
            "AGENT_SUPABASE_API_KEY": api_key,
            "AGENT_ALLOW_INSECURE_LOOPBACK_AUTH_HTTP": "true",
            "AGENT_CURSOR_SIGNING_SECRET": secrets.token_urlsafe(32),
        })
        sensitive_values.append(runtime_env["AGENT_CURSOR_SIGNING_SECRET"])
        process = subprocess.Popen(
            [sys.executable, "-m", "agent.app.main", "--workers", "1"],
            cwd=REPO_ROOT, env=runtime_env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ready = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and process.poll() is None:
            try:
                ready = _http("GET", agent_origin + "/health/live", timeout=1.0)
                if ready.status == 200:
                    break
            except SmokeFailure:
                pass
            time.sleep(0.15)
        if process.poll() is not None or ready is None or ready.status != 200:
            raise SmokeFailure("isolated_agent_start_failed")
        live = ready.payload if isinstance(ready.payload, dict) else {}
        ready_check = _http("GET", agent_origin + "/health/ready")
        ready_body = ready_check.payload if isinstance(ready_check.payload, dict) else {}
        provider = _http("GET", agent_origin + "/health/provider")
        provider_body = provider.payload if isinstance(provider.payload, dict) else {}
        _record(evidence, "agent.health_and_configuration",
                ready_check.status == 200 and ready_body.get("status") == "ready"
                and live.get("business_api_available") is True
                and live.get("inference_available") is False
                and provider.status == 200 and provider_body.get("status") == "disabled"
                and provider_body.get("inference_available") is False,
                live_status=ready.status, ready_status=ready_check.status,
                provider_status=provider.status,
                provider_mode=(provider_body.get("status") if isinstance(provider_body.get("status"), str) else None),
                inference_available=provider_body.get("inference_available"))

        def agent_request(method: str, path: str, owner: str | None = None,
                          body: dict[str, Any] | None = None) -> HttpResult:
            token = users[owner]["token"] if owner else None
            return _http(method, agent_origin + path, bearer=token, body=body)

        missing = agent_request("GET", "/v1/sessions")
        _record(evidence, "agent.missing_token_rejected", missing.status == 401,
                http_status=missing.status, error_code=_api_error_code(missing))
        invalid_token = "invalid-real-auth-smoke-" + uuid.uuid4().hex
        sensitive_values.append(invalid_token)
        invalid = _http("GET", agent_origin + "/v1/sessions", bearer=invalid_token)
        _record(evidence, "agent.invalid_token_rejected", invalid.status == 401,
                http_status=invalid.status, error_code=_api_error_code(invalid))

        created = agent_request("POST", "/v1/sessions", owner="A", body={
            "client_request_id": str(uuid.uuid4()),
            "title": "P1 real Auth smoke",
        })
        created_body = created.payload if isinstance(created.payload, dict) else {}
        created_session = created_body.get("session") if isinstance(created_body.get("session"), dict) else {}
        session_id = created_session.get("session_id")
        try:
            session_id = str(uuid.UUID(str(session_id)))
        except (ValueError, TypeError, AttributeError):
            session_id = None
        _record(evidence, "agent.session_create_A", created.status == 201 and session_id is not None,
                http_status=created.status, session_id=session_id)

        if session_id is not None:
            list_a = agent_request("GET", "/v1/sessions?limit=100", owner="A")
            list_a_body = list_a.payload if isinstance(list_a.payload, dict) else {}
            items_a = list_a_body.get("items") if isinstance(list_a_body.get("items"), list) else []
            found_a = any(isinstance(item, dict) and item.get("session_id") == session_id for item in items_a)
            _record(evidence, "agent.session_list_A", list_a.status == 200 and len(items_a) == 1 and found_a,
                    http_status=list_a.status, item_count=len(items_a), owner_A_session_found=found_a)

            detail_a = agent_request("GET", f"/v1/sessions/{session_id}", owner="A")
            detail_body = detail_a.payload if isinstance(detail_a.payload, dict) else {}
            _record(evidence, "agent.session_get_A", detail_a.status == 200
                    and isinstance(detail_body.get("session"), dict)
                    and detail_body["session"].get("session_id") == session_id,
                    http_status=detail_a.status)

            list_b = agent_request("GET", "/v1/sessions?limit=100", owner="B")
            list_b_body = list_b.payload if isinstance(list_b.payload, dict) else {}
            items_b = list_b_body.get("items") if isinstance(list_b_body.get("items"), list) else []
            _record(evidence, "agent.owner_B_list_isolated", list_b.status == 200 and len(items_b) == 0,
                    http_status=list_b.status, item_count=len(items_b))

            get_b = agent_request("GET", f"/v1/sessions/{session_id}", owner="B")
            _record(evidence, "agent.owner_B_get_isolated", get_b.status == 404,
                    http_status=get_b.status, error_code=_api_error_code(get_b))

            plan = agent_request("POST", f"/v1/sessions/{session_id}/turns", owner="A", body={
                "client_request_id": str(uuid.uuid4()),
                "text": "P1 local smoke planning gate",
            })
            _record(evidence, "agent.planning_disabled", plan.status == 409
                    and _api_error_code(plan) == "agent_disabled",
                    http_status=plan.status, error_code=_api_error_code(plan))

            after_plan = agent_request("GET", f"/v1/sessions/{session_id}", owner="A")
            after_plan_body = after_plan.payload if isinstance(after_plan.payload, dict) else {}
            turns = after_plan_body.get("turns") if isinstance(after_plan_body.get("turns"), list) else []
            _record(evidence, "agent.denied_plan_not_persisted", after_plan.status == 200 and len(turns) == 0,
                    http_status=after_plan.status, turn_count=len(turns))

            proposal_id = uuid.uuid4()
            confirm = agent_request("POST", f"/v1/proposals/{proposal_id}/confirm", owner="A", body={
                "client_request_id": str(uuid.uuid4()),
                "expected_proposal_revision": 1,
                "command_digest": "a" * 64,
                "confirmation_nonce": "N" * 32,
            })
            _record(evidence, "agent.nonexistent_confirmation_rejected", confirm.status == 404,
                    http_status=confirm.status, error_code=_api_error_code(confirm),
                    proposal_existed=False, business_write_performed=False)
        else:
            for name in ("agent.session_list_A", "agent.session_get_A",
                         "agent.owner_B_list_isolated", "agent.owner_B_get_isolated",
                         "agent.planning_disabled", "agent.denied_plan_not_persisted",
                         "agent.nonexistent_confirmation_rejected"):
                _record(evidence, name, False, skipped="session_create_failed")

        evidence["agent_process_stopped"] = _stop_process(process)
        process = None
        _record(evidence, "agent_process_stopped_check", evidence["agent_process_stopped"])
        evidence["agent_sqlite_contains_no_credentials"] = (
            _scan_temp_files(temp_path, sensitive_values) if temp_path and temp_path.exists() else True
        )
        _record(evidence, "agent_sqlite_credential_scan",
                evidence["agent_sqlite_contains_no_credentials"],
                credential_values_absent=evidence["agent_sqlite_contains_no_credentials"])
    except SmokeFailure as failure:
        evidence["failure_code"] = failure.code
    except Exception:
        evidence["failure_code"] = "unexpected_failure"
    finally:
        if process is not None:
            try:
                evidence["agent_process_stopped"] = _stop_process(process)
            except Exception:
                evidence["agent_process_stopped"] = False
            _record(evidence, "agent_process_stopped_check", evidence["agent_process_stopped"])
        for owner, user in users.items():
            token = user.get("token")
            if not token:
                continue
            try:
                logout = _http("POST", auth_url + "/logout", api_key=api_key,
                               bearer=token, body={})
                passed = logout.status in (200, 204)
                status = logout.status
            except Exception:
                passed, status = False, None
            _record(evidence, f"auth.password_session_logout_{owner}", passed,
                    http_status=status)
            user["token"] = ""
        for owner, user_id in created_user_ids:
            try:
                deleted = _http("DELETE", auth_url + "/admin/users/" + user_id,
                                api_key=cleanup_key, bearer=cleanup_key)
                passed = deleted.status in (200, 204)
                status = deleted.status
            except Exception:
                passed, status = False, None
            _record(evidence, f"auth.test_user_deleted_{owner}", passed,
                    http_status=status, user_id=user_id)
        if temp is not None:
            try:
                temp.cleanup()
            except Exception:
                pass
        evidence["agent_temp_removed"] = temp_path is None or not temp_path.exists()
        _record(evidence, "agent_temp_removed_check", evidence["agent_temp_removed"])
        evidence["source_digest_before"] = source_before
        try:
            evidence["source_digest_after"] = _source_digest()
        except Exception:
            evidence["source_digest_after"] = None
        unchanged = evidence["source_digest_after"] == evidence["source_digest_before"]
        _record(evidence, "frozen_source_unchanged", unchanged,
                source_digest=evidence["source_digest_after"])
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_evidence(evidence, evidence_path, sensitive_values)
    return 0 if evidence["overall"] == "PASS" else 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run a local real Supabase Auth smoke with an isolated Agent process.")
    parser.add_argument("--supabase-workdir", type=Path, default=DEFAULT_SUPABASE_WORKDIR)
    parser.add_argument("--evidence-path", type=Path, default=None)
    args = parser.parse_args()
    output = args.evidence_path
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = AGENT_ROOT / "docs" / "p1" / "evidence" / f"P1-04-RealAuthSmoke-{stamp}.json"
    try:
        return run(args.supabase_workdir.resolve(), output.resolve())
    except Exception:
        print(json.dumps({"overall": "FAIL", "failure_code": "helper_initialization_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
