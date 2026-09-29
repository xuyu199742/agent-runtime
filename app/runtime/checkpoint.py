from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def create_checkpoint_pool(dsn: str, concurrency: int) -> AsyncConnectionPool:
    """官方 saver 使用 psycopg pool；每个 Run 独立 saver，池限制连接数。"""
    return AsyncConnectionPool(
        dsn,
        min_size=1,
        max_size=concurrency + 2,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )


def create_saver(pool: AsyncConnectionPool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(pool, serde=JsonPlusSerializer(allowed_msgpack_modules=None))
