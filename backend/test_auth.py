"""Identity verification tests (Build Plan step 16).

Covers backend/auth.py directly (mock header, stubbed Clerk SDK, startup
fail-fast checks) plus a couple of end-to-end checks through the FastAPI app
(via TestClient) for wiring that can only be observed at the HTTP layer.
Never calls the real Clerk service: the SDK is stubbed by injecting a fake
`clerk_backend_api` module into `sys.modules` before it is lazily imported.

Run with: python -m unittest test_auth.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402

app = main.app


def make_request(headers: dict[str, str] | None = None) -> Request:
    """Build a bare Starlette Request carrying only the given headers.

    require_identity only reads request.headers, so a full ASGI app/receive
    channel is unnecessary -- this keeps the mock/Clerk unit tests hermetic
    and fast, with no TestClient or running app required.
    """
    # ASGI requires header names as lowercase bytes; Starlette's Headers
    # lookup relies on that.
    encoded = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": encoded,
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 123),
    }
    return Request(scope)


# -- a small, realistic stand-in for clerk_backend_api -----------------------
#
# Real behavior it mirrors (see clerk_backend_api.security.authenticaterequest
# and .types): `authenticate_request` looks up the bearer token, and if its
# claims include an `azp` (authorized party) that isn't in the configured
# `authorized_parties` allowlist, the request is rejected even though the
# token itself is otherwise valid.

_FAKE_TOKENS: dict[str, dict] = {}


class _FakeRequestState:
    def __init__(self, is_signed_in: bool, payload: dict | None = None, reason: str | None = None) -> None:
        self.is_signed_in = is_signed_in
        self.payload = payload
        self.reason = reason


class _FakeAuthenticateRequestOptions:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeClerk:
    def __init__(self, bearer_auth: str | None = None) -> None:
        self.bearer_auth = bearer_auth

    def authenticate_request(self, request: Request, options: _FakeAuthenticateRequestOptions) -> _FakeRequestState:
        token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        payload = _FAKE_TOKENS.get(token)
        if payload is None:
            return _FakeRequestState(False, reason="token-invalid")
        azp = payload.get("azp")
        authorized_parties = options.kwargs.get("authorized_parties")
        if azp is not None and authorized_parties is not None and azp not in authorized_parties:
            return _FakeRequestState(False, reason="token-invalid-authorized-parties")
        return _FakeRequestState(True, payload=payload)


def _fake_clerk_module() -> types.ModuleType:
    module = types.ModuleType("clerk_backend_api")
    module.Clerk = _FakeClerk  # type: ignore[attr-defined]
    module.AuthenticateRequestOptions = _FakeAuthenticateRequestOptions  # type: ignore[attr-defined]
    return module


class MockIdentityTests(unittest.TestCase):
    """SKETCHSCAPE_AUTH_MODE=mock (the default)."""

    def test_default_dev_user(self) -> None:
        with patch.dict(os.environ, {"SKETCHSCAPE_AUTH_MODE": "mock"}):
            identity = auth.require_identity(make_request())
        self.assertEqual(identity, auth.Identity(user_id="dev-user", kind="dev", via="mock"))

    def test_dev_header_is_honored(self) -> None:
        with patch.dict(os.environ, {"SKETCHSCAPE_AUTH_MODE": "mock"}):
            identity = auth.require_identity(make_request({"X-SketchScape-Dev-User": "alice"}))
        self.assertEqual(identity, auth.Identity(user_id="alice", kind="dev", via="mock"))

    def test_auth_mode_defaults_to_mock_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKETCHSCAPE_AUTH_MODE", None)
            identity = auth.require_identity(make_request())
        self.assertEqual(identity.via, "mock")

    def test_require_user_accepts_dev_identity(self) -> None:
        with patch.dict(os.environ, {"SKETCHSCAPE_AUTH_MODE": "mock"}):
            identity = auth.require_user(auth.require_identity(make_request()))
        self.assertEqual(identity.kind, "dev")

    def test_require_service_rejects_dev_identity(self) -> None:
        with patch.dict(os.environ, {"SKETCHSCAPE_AUTH_MODE": "mock"}):
            with self.assertRaises(HTTPException) as ctx:
                auth.require_service(auth.require_identity(make_request()))
        self.assertEqual(ctx.exception.status_code, 403)


class ClerkIdentityTests(unittest.TestCase):
    """SKETCHSCAPE_AUTH_MODE=clerk, against a stubbed clerk_backend_api."""

    def setUp(self) -> None:
        _FAKE_TOKENS.clear()
        self._env = patch.dict(
            os.environ,
            {
                "SKETCHSCAPE_AUTH_MODE": "clerk",
                "CLERK_SECRET_KEY": "sk_test_fake",
                "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com",
            },
        )
        self._env.start()
        self._modules = patch.dict(sys.modules, {"clerk_backend_api": _fake_clerk_module()})
        self._modules.start()

    def tearDown(self) -> None:
        self._modules.stop()
        self._env.stop()
        _FAKE_TOKENS.clear()

    def test_session_token_gives_user_identity(self) -> None:
        _FAKE_TOKENS["sess_ok"] = {"sub": "user_123", "azp": "https://app.example.com"}
        identity = auth.require_identity(make_request({"Authorization": "Bearer sess_ok"}))
        self.assertEqual(identity, auth.Identity(user_id="user_123", kind="user", via="clerk"))

    def test_m2m_token_gives_service_identity(self) -> None:
        _FAKE_TOKENS["m2m_ok"] = {"subject": "client_42"}
        identity = auth.require_identity(make_request({"Authorization": "Bearer m2m_ok"}))
        self.assertEqual(identity, auth.Identity(user_id="nemoclaw:client_42", kind="service", via="clerk"))

    def test_require_user_accepts_session_identity(self) -> None:
        _FAKE_TOKENS["sess_ok"] = {"sub": "user_123", "azp": "https://app.example.com"}
        identity = auth.require_user(auth.require_identity(make_request({"Authorization": "Bearer sess_ok"})))
        self.assertEqual(identity.kind, "user")

    def test_require_service_accepts_m2m_identity(self) -> None:
        _FAKE_TOKENS["m2m_ok"] = {"subject": "client_42"}
        identity = auth.require_service(auth.require_identity(make_request({"Authorization": "Bearer m2m_ok"})))
        self.assertEqual(identity.kind, "service")

    def test_require_user_rejects_service_identity(self) -> None:
        _FAKE_TOKENS["m2m_ok"] = {"subject": "client_42"}
        with self.assertRaises(HTTPException) as ctx:
            auth.require_user(auth.require_identity(make_request({"Authorization": "Bearer m2m_ok"})))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_rejected_token_raises_401_with_reason(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth.require_identity(make_request({"Authorization": "Bearer garbage"}))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("token-invalid", str(ctx.exception.detail))

    def test_no_authorization_header_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth.require_identity(make_request())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_origin_session_token_raises_401(self) -> None:
        _FAKE_TOKENS["sess_wrong_origin"] = {"sub": "user_123", "azp": "https://evil.example.com"}
        with self.assertRaises(HTTPException) as ctx:
            auth.require_identity(make_request({"Authorization": "Bearer sess_wrong_origin"}))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("authorized-parties", str(ctx.exception.detail))

    def test_missing_secret_key_raises_500_before_calling_sdk(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLERK_SECRET_KEY", None)
            with self.assertRaises(HTTPException) as ctx:
                auth.require_identity(make_request({"Authorization": "Bearer sess_ok"}))
        self.assertEqual(ctx.exception.status_code, 500)

    def test_end_to_end_rejected_request_returns_401_with_reason_in_body(self) -> None:
        """One full HTTP round trip, not just a direct auth.py call."""
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects",
                json={"name": "Should be rejected"},
                headers={"Authorization": "Bearer garbage"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertIn("token-invalid", response.json()["detail"])


class InternalRoutesStayWorkerOnlyTests(unittest.TestCase):
    """/v1/internal/** must never accept a Clerk identity as an alternative."""

    def setUp(self) -> None:
        _FAKE_TOKENS.clear()
        self._env = patch.dict(
            os.environ,
            {
                "SKETCHSCAPE_AUTH_MODE": "clerk",
                "CLERK_SECRET_KEY": "sk_test_fake",
                "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com",
                # A worker token must be required here, otherwise
                # worker_is_authorized(None) trivially passes (no token
                # configured means none is required -- fine for local dev,
                # useless for proving a Clerk token isn't an alternative).
                "SKETCHSCAPE_WORKER_TOKEN": "worker-secret-token",
            },
        )
        self._env.start()
        self._modules = patch.dict(sys.modules, {"clerk_backend_api": _fake_clerk_module()})
        self._modules.start()

    def tearDown(self) -> None:
        self._modules.stop()
        self._env.stop()
        _FAKE_TOKENS.clear()

    def test_valid_clerk_bearer_token_is_not_enough_for_internal_route(self) -> None:
        _FAKE_TOKENS["sess_ok"] = {"sub": "user_123", "azp": "https://app.example.com"}
        with TestClient(app) as client:
            response = client.get(
                "/v1/internal/reconstructions/does-not-exist/task",
                headers={"Authorization": "Bearer sess_ok"},
            )
        # Rejected for lacking the worker token -- a Clerk identity, even a
        # valid one, is never an alternative to X-SketchScape-Worker-Token.
        self.assertEqual(response.status_code, 401)
        self.assertIn("worker token", response.json()["detail"].lower())


class LegacyDemoRoutesModeGateTests(unittest.TestCase):
    """/scene, /modify-scene, /sketch, and /v1/scene: mock-mode-only."""

    def test_legacy_routes_reachable_in_mock_mode(self) -> None:
        with patch.dict(os.environ, {"SKETCHSCAPE_AUTH_MODE": "mock"}), TestClient(app) as client:
            self.assertEqual(client.get("/v1/scene").status_code, 200)
            self.assertEqual(client.get("/scene").status_code, 200)

    def test_legacy_routes_404_in_clerk_mode(self) -> None:
        env = {
            "SKETCHSCAPE_AUTH_MODE": "clerk",
            "CLERK_SECRET_KEY": "sk_test_fake",
            "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com",
        }
        with patch.dict(os.environ, env), TestClient(app) as client:
            self.assertEqual(client.get("/v1/scene").status_code, 404)
            self.assertEqual(client.get("/scene").status_code, 404)
            self.assertEqual(client.get("/v1/interactives").status_code, 404)
            self.assertEqual(
                client.post(
                    "/v1/scene/actions",
                    json={"target_id": "tree_1", "action": "scale_by", "value": [1, 2, 1]},
                ).status_code,
                404,
            )
            self.assertEqual(client.post("/v1/scene/modify", json={"instruction": "x"}).status_code, 404)
            self.assertEqual(client.post("/modify-scene", json={"instruction": "x"}).status_code, 404)
            self.assertEqual(
                client.post("/sketch", files={"sketch": ("s.png", b"x", "image/png")}).status_code, 404
            )


class StartupChecksTests(unittest.TestCase):
    """Each rule in the fail-fast table refuses to start (raises, never warns)."""

    def _run(self, env: dict[str, str]) -> None:
        with patch.dict(os.environ, env):
            auth.run_startup_checks()

    def test_clerk_without_secret_key_refuses_to_start(self) -> None:
        env = {"SKETCHSCAPE_AUTH_MODE": "clerk", "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com"}
        with patch.dict(os.environ, env):
            os.environ.pop("CLERK_SECRET_KEY", None)
            with self.assertRaises(RuntimeError):
                auth.run_startup_checks()

    def test_clerk_with_empty_web_origins_refuses_to_start(self) -> None:
        env = {
            "SKETCHSCAPE_AUTH_MODE": "clerk",
            "CLERK_SECRET_KEY": "sk_test_fake",
            "SKETCHSCAPE_WEB_ORIGINS": "",
        }
        with self.assertRaises(RuntimeError):
            self._run(env)

    def test_clerk_with_wildcard_web_origins_refuses_to_start(self) -> None:
        env = {
            "SKETCHSCAPE_AUTH_MODE": "clerk",
            "CLERK_SECRET_KEY": "sk_test_fake",
            "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com,*",
        }
        with self.assertRaises(RuntimeError):
            self._run(env)

    def test_clerk_with_valid_config_starts_cleanly(self) -> None:
        env = {
            "SKETCHSCAPE_AUTH_MODE": "clerk",
            "CLERK_SECRET_KEY": "sk_test_fake",
            "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com",
        }
        self._run(env)  # must not raise

    def test_mock_with_dynamodb_storage_refuses_to_start(self) -> None:
        env = {"SKETCHSCAPE_AUTH_MODE": "mock", "SKETCHSCAPE_STORAGE_BACKEND": "dynamodb"}
        with self.assertRaises(RuntimeError):
            self._run(env)

    def test_mock_with_non_mock_pipeline_refuses_to_start(self) -> None:
        env = {"SKETCHSCAPE_AUTH_MODE": "mock", "PIPELINE_MODE": "aws-local"}
        with self.assertRaises(RuntimeError):
            self._run(env)

    def test_mock_with_default_config_starts_cleanly(self) -> None:
        env = {"SKETCHSCAPE_AUTH_MODE": "mock", "PIPELINE_MODE": "mock", "SKETCHSCAPE_STORAGE_BACKEND": "local"}
        self._run(env)  # must not raise

    def test_unknown_auth_mode_refuses_to_start(self) -> None:
        with self.assertRaises(RuntimeError):
            self._run({"SKETCHSCAPE_AUTH_MODE": "bogus"})

    def test_lifespan_runs_the_startup_checks(self) -> None:
        """Proves main.py's lifespan actually calls run_startup_checks, not
        just that the standalone function works in isolation."""
        env = {"SKETCHSCAPE_AUTH_MODE": "clerk", "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com"}

        async def enter_and_exit_lifespan() -> None:
            async with main.lifespan(main.app):
                pass

        with patch.dict(os.environ, env):
            os.environ.pop("CLERK_SECRET_KEY", None)
            with self.assertRaises(RuntimeError):
                asyncio.run(enter_and_exit_lifespan())


if __name__ == "__main__":
    unittest.main()
