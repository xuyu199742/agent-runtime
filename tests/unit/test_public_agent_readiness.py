from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.application.catalog import CatalogService


async def test_public_agents_hide_missing_model_limits_and_disabled_models():
    agents = [SimpleNamespace(id=str(i), model_id=str(i)) for i in range(4)]
    models = [
        SimpleNamespace(
            enabled=True,
            archived_at=None,
            config={"context_window": 8192, "max_output_tokens": 1024},
        ),
        SimpleNamespace(enabled=True, archived_at=None, config={}),
        SimpleNamespace(
            enabled=False,
            archived_at=None,
            config={"context_window": 8192, "max_output_tokens": 1024},
        ),
        None,
    ]
    repository = SimpleNamespace(
        public_agents=AsyncMock(return_value=agents), model=AsyncMock(side_effect=models)
    )
    assert await CatalogService(repository).public_agents() == agents[:1]
