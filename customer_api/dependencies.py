"""Authentication and authorization dependencies for API routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from customer_api.auth import ApiSession
from customer_api.types import AuthenticatedUser


def build_auth_dependencies(sessions, bearer):
    def current_session(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> ApiSession:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="請先登入。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        session = sessions.get(credentials.credentials)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登入已失效，請重新登入。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return session

    def editor_user(
        session: Annotated[ApiSession, Depends(current_session)],
    ) -> AuthenticatedUser:
        if session.user.role not in {"admin", "editor"}:
            raise HTTPException(status_code=403, detail="目前帳號只有檢視權限。")
        return session.user

    return current_session, editor_user
