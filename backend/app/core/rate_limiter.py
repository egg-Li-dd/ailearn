"""简单内存限流：滑动窗口计数，保护 AI 调用不被滥用。

单进程内存实现，重启后重置。如需分布式限流请改用 Redis。
"""
import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    """滑动窗口限流器。

    用法：
        limiter = RateLimiter(max_calls=10, window_seconds=60)
        if not limiter.allow("user_or_ip_key"):
            raise HTTPException(429, "请求过于频繁")
    """

    def __init__(self, max_calls: int = 10, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """检查 key 是否允许通过，通过则记录本次调用时间。"""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            dq = self._calls[key]
            # 清理窗口外的旧记录
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_calls:
                return False
            dq.append(now)
            return True

    def remaining(self, key: str) -> int:
        """查询 key 剩余可用次数（不消耗额度）。"""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            dq = self._calls.get(key)
            if not dq:
                return self.max_calls
            while dq and dq[0] < cutoff:
                dq.popleft()
            return max(0, self.max_calls - len(dq))


# 全局 AI 生成/调整限流器：每分钟最多 20 次（按 IP/客户端区分）
ai_limiter = RateLimiter(max_calls=20, window_seconds=60)
