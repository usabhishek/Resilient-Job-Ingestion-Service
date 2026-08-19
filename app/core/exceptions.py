class IngestionError(Exception):
    """Base exception for all ingestion related failures."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class SourceError(IngestionError):
    """Base exception for source-related errors."""
    pass

class TemporarySourceError(SourceError):
    """Transient source error that can be retried or triggers failover (e.g., 500, 502, 503, 504, connection reset)."""
    pass

class PermanentSourceError(SourceError):
    """Fatal non-retryable source error (e.g., 401 Unauthorized, 403 Forbidden, 404 Board Not Found)."""
    pass

class RateLimitExceededError(TemporarySourceError):
    """Raised when upstream returns HTTP 429 Too Many Requests and retries are exhausted."""
    def __init__(self, message: str, retry_after: float | None = None, details: dict | None = None):
        super().__init__(message, details)
        self.retry_after = retry_after

class HttpTimeoutError(TemporarySourceError):
    """Raised when an HTTP request times out."""
    pass

class EmptyResponseWarning(IngestionError):
    """Raised/warned when a source returns HTTP 200 with an empty job list."""
    pass

class MalformedResponseError(IngestionError):
    """Raised when a source returns invalid JSON or unparseable HTML error payload."""
    pass

class SchemaValidationError(IngestionError):
    """Raised when raw job payload fails required Pydantic normalization rules."""
    pass
