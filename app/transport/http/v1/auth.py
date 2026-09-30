from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.application.auth import InvalidCredentials
from app.transport.http.v1.dependencies import Auth, CurrentUser, bearer

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/login")
async def login(body: LoginIn, auth: Auth):
    try:
        return await auth.login(body.username, body.password)
    except InvalidCredentials:
        raise HTTPException(401, detail="用户名或密码错误") from None


@router.post("/refresh")
async def refresh(body: RefreshIn, auth: Auth):
    try:
        return await auth.refresh(body.refresh_token)
    except InvalidCredentials:
        raise HTTPException(401, detail="刷新凭证无效") from None


@router.post("/logout", status_code=204)
async def logout(
    auth: Auth,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    if credentials is None:
        raise HTTPException(401, detail="需要登录")
    try:
        _, session = await auth.authenticate(credentials.credentials)
    except InvalidCredentials:
        raise HTTPException(401, detail="登录已失效") from None
    await auth.logout(session)


@router.get("/me")
async def me(user: CurrentUser):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "roles": list(user.roles),
        "permissions": sorted(user.permissions),
    }
