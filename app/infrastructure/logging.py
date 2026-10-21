import logging

import structlog

from app.config import get_settings


def configure_logging() -> None:
    logging.basicConfig(level=get_settings().log_level.upper())
    # MCP SDK 的 DEBUG 日志会输出 tools/call 的完整参数，服务日志不能记录这些内容。
    logging.getLogger("mcp.client").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
