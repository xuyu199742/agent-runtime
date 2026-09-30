"""本地 Artifact 文件存储；数据库仅保存随机键和元数据。"""

import asyncio
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4


class LocalArtifactStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def path(self, key: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", key) is None:
            raise ValueError("无效的 Artifact 存储键")
        return self.root / key

    async def save_bytes(self, content: bytes) -> str:
        key = uuid4().hex

        def write() -> None:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as output:
                    temporary = Path(output.name)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path(key))
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        await asyncio.to_thread(write)
        return key

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.path(key).unlink, missing_ok=True)
