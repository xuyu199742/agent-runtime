from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.context.errors import ContextLeaseLost


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


class LeaseFencedPostgresSaver(AsyncPostgresSaver):
    """在官方 Saver 写入事务内锁定 Run 并验证租约。"""

    def __init__(
        self, connection: AsyncConnectionPool | AsyncConnection, run_id: str, worker_id: str
    ):
        super().__init__(connection, serde=JsonPlusSerializer(allowed_msgpack_modules=None))
        self.run_id = run_id
        self.worker_id = worker_id

    @asynccontextmanager
    async def _connection(self):
        if isinstance(self.conn, AsyncConnectionPool):
            async with self.conn.connection() as conn:
                yield conn
        else:
            # from_conn_string 测试入口只有一条连接；写事务需独立连接，避免与原 Saver 并发复用。
            async with await AsyncConnection.connect(
                self.conn.info.dsn,
                password=self.conn.info.password,
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            ) as conn:
                yield conn

    async def _write_transaction(self, method: str, *args):
        async with self.lock, self._connection() as conn, conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT id FROM runs
                        WHERE id = %s AND status = 'RUNNING'
                        AND lease_owner = %s AND lease_until > now()
                        FOR UPDATE""",
                    (self.run_id, self.worker_id),
                )
                if await cur.fetchone() is None:
                    raise ContextLeaseLost
            # 官方 saver 使用同一 psycopg 连接，检查点与租约检查一起提交。
            saver = AsyncPostgresSaver(conn, serde=self.serde)
            return await getattr(saver, method)(*args)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._write_transaction("aput", config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return await self._write_transaction("aput_writes", config, writes, task_id, task_path)


def create_run_saver(
    connection: AsyncConnectionPool | AsyncConnection, run_id: str, worker_id: str
):
    return LeaseFencedPostgresSaver(connection, run_id, worker_id)
