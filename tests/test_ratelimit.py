import time
from tvrenamer.ratelimit import TokenBucket, CircuitBreaker


def test_token_bucket_rate():
    tb = TokenBucket(rate=5, capacity=5)
    # consume 5 tokens immediately
    for _ in range(5):
        assert tb.consume()
    # next immediate consume should fail
    assert not tb.consume()
    # after a short wait tokens refill
    time.sleep(0.25)
    assert tb.consume()


def test_circuit_breaker_opens():
    cb = CircuitBreaker(failure_threshold=3, recovery_time=1)
    assert not cb.is_open()
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()
    assert cb.is_open()
    # after recovery_time it should allow again
    time.sleep(1.1)
    assert not cb.is_open()
