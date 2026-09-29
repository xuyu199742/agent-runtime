from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.catalog import CatalogService
from app.application.chat import ConversationService
from app.application.runs import RunService
from app.persistence.database import get_db
from app.persistence.repositories.catalog import CatalogRepository
from app.persistence.repositories.conversations import ConversationRepository
from app.persistence.repositories.runs import RunRepository

Db = Annotated[AsyncSession, Depends(get_db)]


def catalog_service(db: Db) -> CatalogService:
    return CatalogService(CatalogRepository(db))


def conversation_service(db: Db) -> ConversationService:
    return ConversationService(ConversationRepository(db))


def run_service(db: Db) -> RunService:
    return RunService(RunRepository(db))


Catalog = Annotated[CatalogService, Depends(catalog_service)]
Conversation = Annotated[ConversationService, Depends(conversation_service)]
Runs = Annotated[RunService, Depends(run_service)]
