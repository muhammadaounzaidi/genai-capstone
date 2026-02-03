"""Shared utilities for MCP tool handlers (DRY)."""
import logging
from typing import Any, Callable, Dict, TypeVar

T = TypeVar("T")


def run_tool(
    fn: Callable[[], T],
    fallback: Dict[str, Any],
    logger_instance: logging.Logger,
    log_message: str,
) -> Dict[str, Any]:
    """Run a callable; on exception log and return fallback with error key.

    Single place for try/except and error logging so tools stay simple.
    """
    try:
        result = fn()
        return result if isinstance(result, dict) else fallback
    except Exception as error:
        logger_instance.error(log_message, exc_info=False)
        return {**fallback, "error": str(error)}
