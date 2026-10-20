import logging

from app.infrastructure.logging import configure_logging


def test_mcp_client_arguments_are_not_logged_at_debug(caplog):
    logger = logging.getLogger("mcp.client.streamable_http")
    original = logging.getLogger("mcp.client").level
    try:
        configure_logging()
        with caplog.at_level(logging.DEBUG):
            logger.debug("Sending client message: tools/call secret=private-value")
        assert "private-value" not in caplog.text
    finally:
        logging.getLogger("mcp.client").setLevel(original)
