from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from models.schemas import AuthGoogleRequest, AuthSessionResponse, UserProfile
from services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/google", response_model=AuthSessionResponse)
def auth_with_google(
    request: AuthGoogleRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    return auth_service.exchange_google_credential(request.credential)


@router.get("/me", response_model=UserProfile)
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    token = credentials.credentials if credentials else ""
    return auth_service.verify_session_token(token)
