"""rate_limiter 模块单元测试"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allow_within_limit(self):
        rl = RateLimiter(max_calls=3, window_seconds=60)
        assert rl.allow("user1") is True
        assert rl.allow("user1") is True
        assert rl.allow("user1") is True

    def test_reject_over_limit(self):
        rl = RateLimiter(max_calls=2, window_seconds=60)
        assert rl.allow("user1") is True
        assert rl.allow("user1") is True
        assert rl.allow("user1") is False

    def test_independent_keys(self):
        rl = RateLimiter(max_calls=1, window_seconds=60)
        assert rl.allow("user1") is True
        assert rl.allow("user1") is False
        assert rl.allow("user2") is True

    def test_remaining(self):
        rl = RateLimiter(max_calls=5, window_seconds=60)
        assert rl.remaining("user1") == 5
        rl.allow("user1")
        assert rl.remaining("user1") == 4

    def test_window_expiry(self):
        rl = RateLimiter(max_calls=1, window_seconds=0.1)
        assert rl.allow("user1") is True
        assert rl.allow("user1") is False
        time.sleep(0.15)
        assert rl.allow("user1") is True

    def test_thread_safety(self):
        import threading
        rl = RateLimiter(max_calls=100, window_seconds=60)
        errors = []
        def worker():
            try:
                for _ in range(10):
                    rl.allow("shared")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
