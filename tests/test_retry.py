from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from app.core.retry import RetryPolicy

def test_retry_policy_delays_bounded():
    policy = RetryPolicy(
        max_retries=3,
        initial_backoff=1.0,
        max_backoff=6.0,
        backoff_factor=2.0,
        jitter_ratio=0.0 # disable jitter for deterministic math
    )

    # Attempt 1 -> 1.0 * (2^0) = 1.0
    assert policy.calculate_delay(1) == 1.0
    # Attempt 2 -> 1.0 * (2^1) = 2.0
    assert policy.calculate_delay(2) == 2.0
    # Attempt 3 -> 1.0 * (2^2) = 4.0
    assert policy.calculate_delay(3) == 4.0
    # Attempt 4 -> 1.0 * (2^3) = 8.0, bounded to max_backoff 6.0
    assert policy.calculate_delay(4) == 6.0

def test_retry_policy_retry_after_seconds():
    policy = RetryPolicy(max_backoff=10.0)
    parsed = policy.parse_retry_after("5")
    assert parsed == 5.0
    assert policy.calculate_delay(1, retry_after=5.0) == 5.0

def test_retry_policy_retry_after_http_date():
    policy = RetryPolicy(max_backoff=60.0)
    future_time = datetime.now(timezone.utc) + timedelta(seconds=15)
    header_val = format_datetime(future_time)
    
    parsed = policy.parse_retry_after(header_val)
    assert parsed is not None
    assert 12.0 <= parsed <= 18.0

def test_is_retryable_status():
    policy = RetryPolicy()
    assert policy.is_retryable_status(429) is True
    assert policy.is_retryable_status(500) is True
    assert policy.is_retryable_status(502) is True
    assert policy.is_retryable_status(503) is True
    assert policy.is_retryable_status(504) is True
    assert policy.is_retryable_status(400) is False
    assert policy.is_retryable_status(404) is False
    assert policy.is_retryable_status(200) is False
