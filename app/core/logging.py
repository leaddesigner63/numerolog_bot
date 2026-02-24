import logging


class ExtraFieldsFormatter(logging.Formatter):
    """Добавляет поля из `extra` в итоговую строку лога."""

    _STANDARD_ATTRS = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._STANDARD_ATTRS and not key.startswith("_")
        }
        record.extra_fields = ""
        if extras:
            formatted = " ".join(f"{key}={value}" for key, value in sorted(extras.items()))
            record.extra_fields = f" | {formatted}"
        return super().format(record)


class AccessNoiseFilter(logging.Filter):
    """Фильтрует шумные скан-запросы в access-логах uvicorn."""

    _SUSPICIOUS_PATH_MARKERS = (
        "/wordpress",
        "wp-admin",
        "wp-login.php",
        "setup-config.php",
        "/xmlrpc.php",
        "/.env",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        return not any(marker in message for marker in self._SUSPICIOUS_PATH_MARKERS)


def setup_logging(level: str) -> None:
    formatter = ExtraFieldsFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s%(extra_fields)s"
    )
    logging.basicConfig(level=level.upper(), force=True)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    access_logger = logging.getLogger("uvicorn.access")
    has_filter = any(isinstance(existing_filter, AccessNoiseFilter) for existing_filter in access_logger.filters)
    if not has_filter:
        access_logger.addFilter(AccessNoiseFilter())
