from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from models.schemas import UserProfile
from services.auth_service import AuthService, get_auth_service

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_profile(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    token = credentials.credentials if credentials else ""
    return auth_service.verify_session_token(token)
