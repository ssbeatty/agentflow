"""Backend operational logging (loguru).

This is the FastAPI process's own log (startup, migrations, execution engine
lifecycle, auth, MCP/OAuth, ...) — console + a rotating file under
data/logs/agentflow.log. It is UNRELATED to user-script execution logs (the
per-run ExecutionLog rows / WS log stream in services/execution_engine.py),
which are a separate protocol that must keep working exactly as-is. Do not add
loguru to backend/agentflow/** — that package runs inside user-script
subprocesses and its print() calls are intentionally captured by the runner
protocol as execution output, not backend logs.
"""
import inspect
import logging
import sys

from loguru import logger

from app.config import settings, DEFAULT_DATA_DIR

LOG_DIR = DEFAULT_DATA_DIR / "logs"

CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"

# Standard-library loggers (uvicorn, sqlalchemy, apscheduler, the mcp SDK, ...)
# get redirected into loguru so every backend log line shares one format/sink.
_INTERCEPTED_LOGGERS = (
    "uvicorn", "uvicorn.access", "uvicorn.error",
    "sqlalchemy.engine", "apscheduler", "mcp",
)


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


_configured = False


def setup_logging() -> None:
    """Call once, as early as possible on startup (before uvicorn/sqlalchemy
    have a chance to configure their own stdlib logging handlers)."""
    global _configured
    if _configured:
        return
    _configured = True

    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, colorize=True, format=CONSOLE_FORMAT)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        LOG_DIR / "agentflow.log",
        level=settings.log_level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        format=FILE_FORMAT,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in _INTERCEPTED_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False
