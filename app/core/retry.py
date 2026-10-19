import random
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

class RetryPolicy:
    """
    Configurable Bounded Exponential Backoff with Jitter and Retry-After support.
    """
    def __init__(
        self,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        max_backoff: float = 8.0,
        backoff_factor: float = 2.0,
        jitter_ratio: float = 0.25,
        retryable_status_codes: set[int] | None = None
    ):
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_factor = backoff_factor
        self.jitter_ratio = jitter_ratio
        self.retryable_status_codes = retryable_status_codes or {429, 500, 502, 503, 504}

    def is_retryable_status(self, status_code: int) -> bool:
        return status_code in self.retryable_status_codes

    @staticmethod
    def parse_retry_after(header_value: str | None) -> float | None:
        """
        Parses standard HTTP Retry-After header which can be either seconds (integer)
        or an HTTP-date (RFC 7231 / RFC 2822).
        """
        if not header_value:
            return None
        
        header_clean = header_value.strip()
        # Check if it is integer seconds
        if re.match(r"^\d+$", header_clean):
            return max(0.0, float(header_clean))
        
        # Try parsing HTTP date
        try:
            target_dt = parsedate_to_datetime(header_clean)
            now = datetime.now(timezone.utc)
            diff = (target_dt - now).total_seconds()
            return max(0.0, diff)
        except Exception:
            return None

    def calculate_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """
        Calculates sleep delay for a given attempt (1-indexed).
        If Retry-After is specified, it respects it up to max_backoff.
        Otherwise calculates exponential backoff: initial_backoff * (backoff_factor ^ (attempt - 1)) +/- jitter.
        """
        if retry_after is not None and retry_after > 0:
            return min(self.max_backoff, retry_after)

        # Exponential backoff
        exp_delay = self.initial_backoff * (self.backoff_factor ** (attempt - 1))
        bounded_delay = min(self.max_backoff, exp_delay)

        # Add uniform jitter: +/- jitter_ratio
        if self.jitter_ratio > 0:
            jitter_range = bounded_delay * self.jitter_ratio
            jitter = random.uniform(-jitter_range, jitter_range)
            delay = max(0.1, bounded_delay + jitter)
        else:
            delay = bounded_delay

        return min(self.max_backoff, delay)
