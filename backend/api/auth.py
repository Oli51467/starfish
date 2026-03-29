from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from models.schemas import (
    AuthGithubCodeRequest,
    AuthGithubStartResponse,
    AuthGoogleRequest,
    AuthSessionResponse,
    UserProfile,
)
from services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/google", response_model=AuthSessionResponse)
def auth_with_google(
    request: AuthGoogleRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    return auth_service.exchange_google_credential(request.credential)


@router.get("/github/start", response_model=AuthGithubStartResponse)
def start_github_auth(
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthGithubStartResponse:
    return AuthGithubStartResponse(authorize_url=auth_service.build_github_authorize_url())


@router.post("/github", response_model=AuthSessionResponse)
def auth_with_github(
    request: AuthGithubCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    return auth_service.exchange_github_code(code=request.code, state_value=request.state)


@router.get("/me", response_model=UserProfile)
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    token = credentials.credentials if credentials else ""
    return auth_service.verify_session_token(token)
