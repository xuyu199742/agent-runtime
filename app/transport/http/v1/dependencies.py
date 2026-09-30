from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.auth import AuthService, InvalidCredentials, Principal
from app.persistence.repositories.auth import AuthRepository
from app.transport.http.common import Db

bearer = HTTPBearer(auto_error=False)


def auth_service(db: Db) -> AuthService:
    return AuthService(AuthRepository(db))


Auth = Annotated[AuthService, Depends(auth_service)]


async def authenticated(
    auth: Auth, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if credentials is None:
        raise HTTPException(401, detail="需要登录", headers={"WWW-Authenticate": "Bearer"})
    try:
        principal, _ = await auth.authenticate(credentials.credentials)
    except InvalidCredentials:
        raise HTTPException(
            401, detail="登录已失效", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    return principal


CurrentUser = Annotated[Principal, Depends(authenticated)]


def require(permission: str):
    async def dependency(user: CurrentUser) -> Principal:
        if not user.can(permission):
            raise HTTPException(403, detail="权限不足")
        return user

    return dependency
