import asyncio
import socket

import uvicorn

from app.application.model_test import probe_model_connection
from app.domain.agent import ModelDefinition
from app.runtime.factory import ModelRuntimeConfig
from tests.support.openai_stub import app as stub_app


async def test_model_connection_performs_real_minimal_inference():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(stub_app, host="127.0.0.1", port=port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        config = ModelRuntimeConfig(
            definition=ModelDefinition(
                provider="openai-compatible",
                model_name="stub-model",
                base_url=f"http://127.0.0.1:{port}/v1",
            )
        )
        result = await probe_model_connection(config)
        assert result["success"] is True, result
        assert result["stages"]["inference"] == "success"
        assert result["latency_ms"] >= 0
    finally:
        server.should_exit = True
        await task
