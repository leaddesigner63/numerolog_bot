import logging


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
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    access_logger = logging.getLogger("uvicorn.access")
    has_filter = any(isinstance(existing_filter, AccessNoiseFilter) for existing_filter in access_logger.filters)
    if not has_filter:
        access_logger.addFilter(AccessNoiseFilter())
