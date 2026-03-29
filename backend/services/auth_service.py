from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import secrets
from typing import Any
from urllib.parse import urlencode

import jwt
from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jwt.exceptions import InvalidTokenError
import requests

from core.settings import get_settings
from models.schemas import AuthSessionResponse, UserProfile


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def build_github_authorize_url(self) -> str:
        self._assert_github_login_configured()

        redirect_uri = self._resolve_github_redirect_uri()
        state = self._create_oauth_state(provider="github")
        query = urlencode(
            {
                "client_id": self.settings.github_oauth_client_id,
                "redirect_uri": redirect_uri,
                "scope": "read:user user:email",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    def exchange_google_credential(self, credential: str) -> AuthSessionResponse:
        if not self.settings.google_client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="google_login_not_configured",
            )

        if not credential.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_google_credential")

        try:
            payload = id_token.verify_oauth2_token(
                credential.strip(),
                google_requests.Request(),
                self.settings.google_client_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_google_credential") from exc

        issuer = str(payload.get("iss") or "").strip()
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_google_issuer")

        if not bool(payload.get("email_verified")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="google_email_not_verified")

        user = UserProfile(
            id=str(payload.get("sub") or "").strip(),
            email=str(payload.get("email") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            picture=str(payload.get("picture") or "").strip() or None,
        )
        if not user.id or not user.email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="google_profile_incomplete")

        expires_in = int(self.settings.session_expire_hours * 3600)
        token = self._create_session_token(user=user, expires_in=expires_in)
        return AuthSessionResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=user,
        )

    def exchange_github_code(self, code: str, state_value: str) -> AuthSessionResponse:
        self._assert_github_login_configured()

        safe_code = str(code or "").strip()
        if not safe_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_github_code")

        safe_state = str(state_value or "").strip()
        if not safe_state:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_github_state")

        self._verify_oauth_state(state_token=safe_state, provider="github")
        github_access_token = self._exchange_github_code_for_access_token(code=safe_code, state_token=safe_state)
        user = self._fetch_github_user(github_access_token=github_access_token)

        expires_in = int(self.settings.session_expire_hours * 3600)
        token = self._create_session_token(user=user, expires_in=expires_in)
        return AuthSessionResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=user,
        )

    def verify_session_token(self, token: str) -> UserProfile:
        raw = str(token or "").strip()
        if not raw:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_access_token")

        try:
            payload = jwt.decode(raw, self.settings.session_secret, algorithms=["HS256"])
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_access_token") from exc

        user = UserProfile(
            id=str(payload.get("sub") or "").strip(),
            email=str(payload.get("email") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            picture=str(payload.get("picture") or "").strip() or None,
        )
        if not user.id or not user.email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_access_token_payload")
        return user

    def _create_session_token(self, *, user: UserProfile, expires_in: int) -> str:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        }
        return jwt.encode(payload, self.settings.session_secret, algorithm="HS256")

    def _assert_github_login_configured(self) -> None:
        redirect_uri = self._resolve_github_redirect_uri()
        if self.settings.github_oauth_client_id and self.settings.github_oauth_client_secret and redirect_uri:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="github_login_not_configured",
        )

    def _resolve_github_redirect_uri(self) -> str:
        configured = str(self.settings.github_oauth_redirect_uri or "").strip()
        if configured:
            return configured
        if self.settings.cors_origins:
            return f"{self.settings.cors_origins[0].rstrip('/')}/auth/github/callback"
        return ""

    def _create_oauth_state(self, *, provider: str, ttl_seconds: int = 600) -> str:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "purpose": "oauth_state",
            "provider": provider,
            "nonce": secrets.token_urlsafe(24),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=max(60, ttl_seconds))).timestamp()),
        }
        return jwt.encode(payload, self.settings.session_secret, algorithm="HS256")

    def _verify_oauth_state(self, *, state_token: str, provider: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(state_token, self.settings.session_secret, algorithms=["HS256"])
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_state") from exc

        if str(payload.get("purpose") or "").strip() != "oauth_state":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_state")

        if str(payload.get("provider") or "").strip() != provider:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_state")
        return payload

    def _exchange_github_code_for_access_token(self, *, code: str, state_token: str) -> str:
        try:
            response = requests.post(
                "https://github.com/login/oauth/access_token",
                headers={
                    "Accept": "application/json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                data={
                    "client_id": self.settings.github_oauth_client_id,
                    "client_secret": self.settings.github_oauth_client_secret,
                    "code": code,
                    "redirect_uri": self._resolve_github_redirect_uri(),
                    "state": state_token,
                },
                timeout=self.settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="github_token_exchange_failed",
            ) from exc

        payload = self._safe_json_payload(response)
        error_code = str(payload.get("error") or "").strip().lower()
        if error_code:
            if error_code == "bad_verification_code":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_code")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="github_token_exchange_failed")

        if response.status_code >= 400:
            if response.status_code in {400, 401, 403, 422}:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_code")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="github_token_exchange_failed")

        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="github_access_token_missing")
        return access_token

    def _fetch_github_user(self, *, github_access_token: str) -> UserProfile:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github_access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            response = requests.get(
                "https://api.github.com/user",
                headers=headers,
                timeout=self.settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="github_profile_request_failed") from exc

        if response.status_code in {401, 403}:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_access_token")
        if response.status_code >= 400:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="github_profile_request_failed")

        payload = self._safe_json_payload(response)
        github_user_id = str(payload.get("id") or "").strip()
        if not github_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="github_profile_incomplete")

        email = str(payload.get("email") or "").strip().lower()
        if not email:
            email = self._fetch_github_verified_email(github_access_token=github_access_token)

        login = str(payload.get("login") or "").strip()
        name = str(payload.get("name") or "").strip() or login
        picture = str(payload.get("avatar_url") or "").strip() or None
        user = UserProfile(
            id=f"github:{github_user_id}",
            email=email,
            name=name,
            picture=picture,
        )
        if not user.email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="github_profile_incomplete")
        return user

    def _fetch_github_verified_email(self, *, github_access_token: str) -> str:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github_access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            response = requests.get(
                "https://api.github.com/user/emails",
                headers=headers,
                timeout=self.settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="github_email_request_failed") from exc

        if response.status_code in {401, 403}:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_github_access_token")
        if response.status_code >= 400:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="github_email_request_failed")

        payload = self._safe_json_payload(response)
        if not isinstance(payload, list):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="github_email_not_verified")

        primary_verified_email = ""
        fallback_verified_email = ""
        for item in payload:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip().lower()
            if not email:
                continue
            if not bool(item.get("verified")):
                continue
            if bool(item.get("primary")) and not primary_verified_email:
                primary_verified_email = email
            if not fallback_verified_email:
                fallback_verified_email = email

        selected_email = primary_verified_email or fallback_verified_email
        if not selected_email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="github_email_not_verified")
        return selected_email

    @staticmethod
    def _safe_json_payload(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()
