from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from core.settings import get_settings
from services.auth_service import AuthService


class _MockResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class AuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_snapshot = {
            "GITHUB_OAUTH_CLIENT_ID": os.getenv("GITHUB_OAUTH_CLIENT_ID"),
            "GITHUB_OAUTH_CLIENT_SECRET": os.getenv("GITHUB_OAUTH_CLIENT_SECRET"),
            "GITHUB_OAUTH_REDIRECT_URI": os.getenv("GITHUB_OAUTH_REDIRECT_URI"),
            "SESSION_SECRET": os.getenv("SESSION_SECRET"),
        }
        os.environ["GITHUB_OAUTH_CLIENT_ID"] = "github-client-id"
        os.environ["GITHUB_OAUTH_CLIENT_SECRET"] = "github-client-secret"
        os.environ["GITHUB_OAUTH_REDIRECT_URI"] = "http://localhost:17327/auth/github/callback"
        os.environ["SESSION_SECRET"] = "unit-test-session-secret"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        for key, value in self._env_snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    def test_build_github_authorize_url_contains_client_and_state(self) -> None:
        service = AuthService()
        authorize_url = service.build_github_authorize_url()
        parsed = urlparse(authorize_url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "github.com")
        self.assertEqual(parsed.path, "/login/oauth/authorize")
        self.assertEqual(query.get("client_id"), ["github-client-id"])
        self.assertEqual(query.get("redirect_uri"), ["http://localhost:17327/auth/github/callback"])

        state_values = query.get("state") or []
        self.assertTrue(state_values)
        decoded = service._verify_oauth_state(state_token=state_values[0], provider="github")
        self.assertEqual(str(decoded.get("provider") or ""), "github")

    @patch("services.auth_service.requests.get")
    @patch("services.auth_service.requests.post")
    def test_exchange_github_code_creates_session(self, mocked_post, mocked_get) -> None:
        service = AuthService()
        state_token = service._create_oauth_state(provider="github")

        mocked_post.return_value = _MockResponse(
            status_code=200,
            payload={"access_token": "gho_test_access_token"},
        )
        mocked_get.side_effect = [
            _MockResponse(
                status_code=200,
                payload={
                    "id": 42,
                    "login": "octocat",
                    "name": "The Octocat",
                    "avatar_url": "https://avatars.githubusercontent.com/u/42?v=4",
                    "email": "",
                },
            ),
            _MockResponse(
                status_code=200,
                payload=[
                    {"email": "octocat-primary@example.com", "primary": True, "verified": True},
                    {"email": "octocat-secondary@example.com", "primary": False, "verified": True},
                ],
            ),
        ]

        session = service.exchange_github_code(code="code-12345678", state_value=state_token)
        self.assertEqual(session.token_type, "bearer")
        self.assertEqual(session.user.id, "github:42")
        self.assertEqual(session.user.email, "octocat-primary@example.com")
        self.assertEqual(session.user.name, "The Octocat")

        verified_user = service.verify_session_token(session.access_token)
        self.assertEqual(verified_user.id, "github:42")
        self.assertEqual(verified_user.email, "octocat-primary@example.com")

    def test_exchange_github_code_rejects_invalid_state(self) -> None:
        service = AuthService()
        with self.assertRaises(HTTPException) as context:
            service.exchange_github_code(code="code-12345678", state_value="invalid-state-token")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "invalid_github_state")


if __name__ == "__main__":
    unittest.main()
