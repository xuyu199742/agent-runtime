from pathlib import Path

from app.domain.errors import InvalidConfiguration, NotFound
from app.infrastructure.artifact_storage import LocalArtifactStorage
from app.persistence.repositories.artifacts import ArtifactRepository


class ArtifactService:
    def __init__(self, repository: ArtifactRepository, storage: LocalArtifactStorage):
        self.repository = repository
        self.storage = storage

    async def create_bytes(
        self,
        conversation_id: str,
        name: str,
        type: str,
        mime_type: str,
        content: bytes,
        run_id: str | None = None,
        message_id: str | None = None,
        metadata: dict | None = None,
    ):
        if len(content) > 50 * 1024 * 1024:
            raise InvalidConfiguration("Artifact 文件超过 50MB")
        if not await self.repository.validate_links(conversation_id, run_id, message_id):
            raise InvalidConfiguration("Artifact 关联对象不一致")
        safe_name = Path(name.replace("\\", "/")).name[:250]
        if not safe_name or not type or not mime_type:
            raise InvalidConfiguration("Artifact 元数据不完整")
        key = await self.storage.save_bytes(content)
        try:
            return await self.repository.save(
                {
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "message_id": message_id,
                    "name": safe_name,
                    "type": type,
                    "mime_type": mime_type,
                    "storage_provider": "LOCAL",
                    "storage_key": key,
                    "size": len(content),
                    "metadata_": metadata or {},
                }
            )
        except Exception:
            await self.storage.delete(key)
            raise

    async def get(self, artifact_id: str):
        artifact = await self.repository.get(artifact_id)
        if artifact is None:
            raise NotFound("Artifact 不存在")
        return artifact

    async def visible(self, artifact_id: str, user_id: str):
        artifact = await self.repository.visible(artifact_id, user_id)
        if artifact is None:
            raise NotFound("Artifact 不存在")
        return artifact

    async def conversation(self, conversation_id: str, page: int, page_size: int):
        return await self.repository.page_conversation(conversation_id, page, page_size)

    async def run(self, run_id: str, page: int, page_size: int):
        return await self.repository.page_run(run_id, page, page_size)

    async def admin_page(self, page: int, page_size: int, user_id: str | None):
        return await self.repository.page_admin(page, page_size, user_id)

    def file_path(self, artifact) -> Path:
        if artifact.storage_provider != "LOCAL":
            raise InvalidConfiguration("不支持的 Artifact 存储")
        path = self.storage.path(artifact.storage_key)
        if not path.is_file():
            raise NotFound("Artifact 文件不存在")
        return path
