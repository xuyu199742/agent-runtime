from dataclasses import dataclass

from app.infrastructure.passwords import new_token, verify_password
from app.persistence.repositories.auth import AuthRepository


class InvalidCredentials(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    display_name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


def principal_from_user(user) -> Principal:
    roles = tuple(role.name for role in user.roles)
    permissions = frozenset(
        permission.code for role in user.roles for permission in role.permissions
    )
    return Principal(user.id, user.username, user.display_name, roles, permissions)


class AuthService:
    def __init__(self, repository: AuthRepository) -> None:
        self.repository = repository

    async def login(self, username: str, password: str) -> dict:
        user = await self.repository.user_by_name(username)
        if user is None or not user.enabled or not verify_password(password, user.password_hash):
            raise InvalidCredentials
        access, refresh = new_token(), new_token()
        await self.repository.create_session(user.id, access, refresh)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": 1800,
        }

    async def refresh(self, token: str) -> dict:
        record = await self.repository.refresh(token)
        if record is None:
            raise InvalidCredentials
        _, session = record
        access, refresh = new_token(), new_token()
        await self.repository.rotate(session, access, refresh)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": 1800,
        }

    async def authenticate(self, token: str):
        record = await self.repository.access(token)
        if record is None:
            raise InvalidCredentials
        user, session = record
        return principal_from_user(user), session

    async def logout(self, session) -> None:
        await self.repository.revoke(session)
