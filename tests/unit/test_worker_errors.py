from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.runtime.tools import ToolConfigurationError
from app.worker.runner import classify_run_error


def test_worker_distinguishes_model_tool_timeout_and_infrastructure_errors():
    assert classify_run_error(ValueError("模型配置无效")) == "MODEL_ERROR"
    assert classify_run_error(ToolConfigurationError("工具无效")) == "TOOL_ERROR"
    assert classify_run_error(TimeoutError("超时")) == "TIMEOUT"
    assert classify_run_error(RedisConnectionError("断开")) == "INTERNAL_ERROR"
    assert classify_run_error(RuntimeError("未知")) == "INTERNAL_ERROR"
    assert (
        classify_run_error(
            ModelCallLimitExceededError(thread_count=0, run_count=2, thread_limit=None, run_limit=2)
        )
        == "VALIDATION_ERROR"
    )
