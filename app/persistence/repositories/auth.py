from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.passwords import token_hash
from app.persistence.database import AuthSession, User


class AuthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def user_by_name(self, username: str) -> User | None:
        return await self.db.scalar(select(User).where(User.username == username))

    async def access(self, token: str) -> tuple[User, AuthSession] | None:
        row = (
            await self.db.execute(
                select(User, AuthSession)
                .join(AuthSession, AuthSession.user_id == User.id)
                .where(
                    AuthSession.access_hash == token_hash(token),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.access_expires_at > datetime.now(UTC),
                    User.enabled.is_(True),
                )
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def refresh(self, token: str) -> tuple[User, AuthSession] | None:
        row = (
            await self.db.execute(
                select(User, AuthSession)
                .join(AuthSession, AuthSession.user_id == User.id)
                .where(
                    AuthSession.refresh_hash == token_hash(token),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.refresh_expires_at > datetime.now(UTC),
                    User.enabled.is_(True),
                )
                .with_for_update(of=AuthSession)
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def create_session(self, user_id: str, access: str, refresh: str) -> None:
        now = datetime.now(UTC)
        self.db.add(
            AuthSession(
                user_id=user_id,
                access_hash=token_hash(access),
                refresh_hash=token_hash(refresh),
                access_expires_at=now + timedelta(minutes=30),
                refresh_expires_at=now + timedelta(days=7),
            )
        )
        await self.db.commit()

    async def rotate(self, session: AuthSession, access: str, refresh: str) -> None:
        now = datetime.now(UTC)
        session.access_hash = token_hash(access)
        session.refresh_hash = token_hash(refresh)
        session.access_expires_at = now + timedelta(minutes=30)
        session.refresh_expires_at = now + timedelta(days=7)
        await self.db.commit()

    async def revoke(self, session: AuthSession) -> None:
        session.revoked_at = datetime.now(UTC)
        await self.db.commit()
