"""简单内存 TTL 缓存，用于 AI 生成结果的短期幂等性。

单进程内存实现，线程安全。重启后清空。
适合缓存 AI 生成结果（相同指令短时间内返回相同结果，节省 API 调用）。
"""
import time
from threading import Lock
from typing import Any, Optional


class TTLCache:
    """带 TTL 的内存缓存。

    用法：
        cache = TTLCache(max_size=100, ttl_seconds=300)
        cache.set("key", value)
        value = cache.get("key")  # 过期返回 None
        cache.clear()
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}  # key -> (expire_at, value)
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，过期或不存在返回 None。"""
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expire_at, value = entry
            if now >= expire_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        """设置缓存值，超出 max_size 时淘汰最旧的条目。"""
        now = time.monotonic()
        with self._lock:
            # 淘汰过期条目
            expired = [k for k, (exp, _) in self._store.items() if now >= exp]
            for k in expired:
                del self._store[k]

            # 超出容量时淘汰最旧的
            if len(self._store) >= self.max_size and key not in self._store:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]

            self._store[key] = (now + self.ttl_seconds, value)

    def delete(self, key: str) -> bool:
        """删除缓存条目，返回是否存在。"""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """清空所有缓存。"""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        """当前有效缓存条目数（自动清理过期）。"""
        now = time.monotonic()
        with self._lock:
            expired = [k for k, (exp, _) in self._store.items() if now >= exp]
            for k in expired:
                del self._store[k]
            return len(self._store)


# 全局 AI 生成结果缓存：5 分钟 TTL，最多 50 条
ai_generate_cache = TTLCache(max_size=50, ttl_seconds=300)
# 全局 AI 调整结果缓存：2 分钟 TTL（调整结果时效性更强）
ai_action_cache = TTLCache(max_size=50, ttl_seconds=120)


def make_cache_key(context_type: str, instruction: str, extra: str = "") -> str:
    """生成缓存 key：context_type + instruction 哈希。

    instruction 做小写+去空白归一化，避免 " 调整排序 " 和 "调整排序" 被视为不同请求。
    """
    import hashlib
    normalized = f"{context_type}:{instruction.strip().lower()}:{extra}"
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()
