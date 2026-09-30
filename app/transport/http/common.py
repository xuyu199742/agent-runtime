from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.approvals import ApprovalService
from app.application.audit import AuditService
from app.application.catalog import CatalogService
from app.application.chat import ConversationService
from app.application.identity import IdentityService
from app.application.runs import RunService
from app.persistence.database import get_db
from app.persistence.repositories.approvals import ApprovalRepository
from app.persistence.repositories.audit import AuditRepository
from app.persistence.repositories.catalog import CatalogRepository
from app.persistence.repositories.conversations import ConversationRepository
from app.persistence.repositories.identity import IdentityRepository
from app.persistence.repositories.runs import RunRepository

Db = Annotated[AsyncSession, Depends(get_db)]


def catalog_service(db: Db) -> CatalogService:
    return CatalogService(CatalogRepository(db))


def audit_service(db: Db) -> AuditService:
    return AuditService(AuditRepository(db))


def approval_service(db: Db) -> ApprovalService:
    return ApprovalService(ApprovalRepository(db))


def conversation_service(db: Db) -> ConversationService:
    return ConversationService(ConversationRepository(db))


def identity_service(db: Db) -> IdentityService:
    return IdentityService(IdentityRepository(db))


def run_service(db: Db) -> RunService:
    return RunService(RunRepository(db))


Catalog = Annotated[CatalogService, Depends(catalog_service)]
Audit = Annotated[AuditService, Depends(audit_service)]
Approvals = Annotated[ApprovalService, Depends(approval_service)]
Conversation = Annotated[ConversationService, Depends(conversation_service)]
Identity = Annotated[IdentityService, Depends(identity_service)]
Runs = Annotated[RunService, Depends(run_service)]
