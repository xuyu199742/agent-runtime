import logging

import structlog

from app.config import get_settings


def configure_logging() -> None:
    logging.basicConfig(level=get_settings().log_level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
