from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jwt.exceptions import InvalidTokenError

from core.settings import get_settings
from models.schemas import AuthSessionResponse, UserProfile


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

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


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()

