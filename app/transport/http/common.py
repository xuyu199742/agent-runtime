from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.approvals import ApprovalService
from app.application.artifacts import ArtifactService
from app.application.audit import AuditService
from app.application.catalog import CatalogService
from app.application.chat import ConversationService
from app.application.dashboard import DashboardService
from app.application.identity import IdentityService
from app.application.runs import RunService
from app.application.workers import WorkerService
from app.config import get_settings
from app.infrastructure.artifact_storage import LocalArtifactStorage
from app.messaging.run_queue import RunQueue
from app.messaging.worker_registry import WorkerRegistry
from app.persistence.database import get_db
from app.persistence.repositories.approvals import ApprovalRepository
from app.persistence.repositories.artifacts import ArtifactRepository
from app.persistence.repositories.audit import AuditRepository
from app.persistence.repositories.catalog import CatalogRepository
from app.persistence.repositories.conversations import ConversationRepository
from app.persistence.repositories.dashboard import DashboardRepository
from app.persistence.repositories.identity import IdentityRepository
from app.persistence.repositories.runs import RunRepository

Db = Annotated[AsyncSession, Depends(get_db)]


def catalog_service(db: Db) -> CatalogService:
    return CatalogService(CatalogRepository(db))


def audit_service(db: Db) -> AuditService:
    return AuditService(AuditRepository(db))


def approval_service(db: Db) -> ApprovalService:
    return ApprovalService(ApprovalRepository(db))


def artifact_service(db: Db) -> ArtifactService:
    return ArtifactService(
        ArtifactRepository(db), LocalArtifactStorage(get_settings().artifact_storage_dir)
    )


def conversation_service(db: Db) -> ConversationService:
    return ConversationService(ConversationRepository(db))


def identity_service(db: Db) -> IdentityService:
    return IdentityService(IdentityRepository(db))


def run_service(db: Db) -> RunService:
    return RunService(RunRepository(db))


def worker_service(request: Request, db: Db) -> WorkerService:
    return WorkerService(WorkerRegistry(request.app.state.redis), RunRepository(db))


def dashboard_service(request: Request, db: Db) -> DashboardService:
    redis = request.app.state.redis
    return DashboardService(DashboardRepository(db), WorkerRegistry(redis), RunQueue(redis))


Catalog = Annotated[CatalogService, Depends(catalog_service)]
Audit = Annotated[AuditService, Depends(audit_service)]
Approvals = Annotated[ApprovalService, Depends(approval_service)]
Artifacts = Annotated[ArtifactService, Depends(artifact_service)]
Conversation = Annotated[ConversationService, Depends(conversation_service)]
Identity = Annotated[IdentityService, Depends(identity_service)]
Runs = Annotated[RunService, Depends(run_service)]
Workers = Annotated[WorkerService, Depends(worker_service)]
Dashboard = Annotated[DashboardService, Depends(dashboard_service)]
