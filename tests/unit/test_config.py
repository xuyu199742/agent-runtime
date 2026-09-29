from app.config import Settings


def test_checkpoint_url_uses_same_database_and_psycopg_driver():
    settings = Settings(database_url="postgresql+asyncpg://agent:secret@localhost:5434/agent")
    assert settings.checkpoint_database_url == "postgresql://agent:secret@localhost:5434/agent"
