"""simple_cache 模块单元测试"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.simple_cache import TTLCache, make_cache_key


class TestTTLCache:
    def test_set_and_get(self):
        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing(self):
        cache = TTLCache(max_size=10, ttl_seconds=60)
        assert cache.get("missing") is None

    def test_expiry(self):
        cache = TTLCache(max_size=10, ttl_seconds=0.1)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_max_size_eviction(self):
        cache = TTLCache(max_size=2, ttl_seconds=60)
        cache.set("key1", "v1")
        cache.set("key2", "v2")
        cache.set("key3", "v3")  # 应该淘汰最旧的 key1
        assert cache.get("key1") is None
        assert cache.get("key2") == "v2"
        assert cache.get("key3") == "v3"

    def test_delete(self):
        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        assert cache.delete("key1") is False

    def test_clear(self):
        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "v1")
        cache.set("key2", "v2")
        cache.clear()
        assert cache.size() == 0

    def test_size(self):
        cache = TTLCache(max_size=10, ttl_seconds=60)
        assert cache.size() == 0
        cache.set("key1", "v1")
        assert cache.size() == 1
        cache.set("key2", "v2")
        assert cache.size() == 2

    def test_overwrite(self):
        cache = TTLCache(max_size=10, ttl_seconds=60)
        cache.set("key1", "v1")
        cache.set("key1", "v2")
        assert cache.get("key1") == "v2"
        assert cache.size() == 1


class TestMakeCacheKey:
    def test_deterministic(self):
        k1 = make_cache_key("course", "按重要度排序")
        k2 = make_cache_key("course", "按重要度排序")
        assert k1 == k2

    def test_different_context(self):
        k1 = make_cache_key("course", "排序")
        k2 = make_cache_key("schedule_item", "排序")
        assert k1 != k2

    def test_different_instruction(self):
        k1 = make_cache_key("course", "排序")
        k2 = make_cache_key("course", "重命名")
        assert k1 != k2

    def test_whitespace_normalization(self):
        k1 = make_cache_key("course", "  排序  ")
        k2 = make_cache_key("course", "排序")
        assert k1 == k2

    def test_case_normalization(self):
        k1 = make_cache_key("course", "SORT")
        k2 = make_cache_key("course", "sort")
        assert k1 == k2
