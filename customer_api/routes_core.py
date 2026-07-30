"""Root, health, and authentication routes."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from customer_api.auth import ApiSession
from customer_api.schemas import LoginRequest
from customer_version import APP_VERSION, MOBILE_ASSET_VERSION


def register_core_routes(app, *, source, sessions, throttle, bearer, current_session):
    @app.get("/")
    def root():
        return {
            "name": "土地資料系統 API",
            "version": APP_VERSION,
            "mobile_asset_version": MOBILE_ASSET_VERSION,
            "docs": "/docs",
            "mobile": "/mobile/",
        }

    @app.get("/health")
    def health():
        try:
            return {
                **source.health(),
                "version": APP_VERSION,
                "mobile_asset_version": MOBILE_ASSET_VERSION,
            }
        except Exception as exc:
            raise HTTPException(status_code=503, detail="資料庫目前無法使用。") from exc

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request):
        client_host = request.client.host if request.client else "unknown"
        throttle_key = f"{client_host}:{payload.username.casefold()}"
        retry_after = throttle.retry_after(throttle_key)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="登入失敗次數過多，請稍後再試。",
                headers={"Retry-After": str(retry_after)},
            )
        user = source.authenticate(payload.username, payload.password)
        if user is None:
            throttle.failure(throttle_key)
            raise HTTPException(
                status_code=401,
                detail="帳號或密碼錯誤。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        throttle.success(throttle_key)
        token, expires_at = sessions.create(user)
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
            },
        }

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        _session: Annotated[ApiSession, Depends(current_session)],
    ):
        if credentials:
            sessions.revoke(credentials.credentials)
        return None

    @app.get("/api/v1/auth/me")
    def me(session: Annotated[ApiSession, Depends(current_session)]):
        user = session.user
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "expires_at": datetime.fromtimestamp(session.expires_at, timezone.utc).isoformat(),
        }
