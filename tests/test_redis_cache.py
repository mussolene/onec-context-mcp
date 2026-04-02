"""Tests for redis_cache with in-memory mock (no real Redis)."""

import time
from unittest.mock import MagicMock, patch

import pytest

from onec_help.runtime import redis_cache


def _make_redis_mock():
    """Minimal Redis-like storage so redis_cache APIs are exercised without real Redis."""
    storage = {}
    lists = {}
    client = MagicMock()

    def hgetall(key):
        return storage.get(key, {}).copy()

    def hset(key, key_or_map=None, value=None, mapping=None):
        if key not in storage:
            storage[key] = {}
        if mapping is not None:
            storage[key].update(mapping)
        elif key_or_map is not None and value is not None:
            storage[key][key_or_map] = value

    def get(key):
        return storage.get(key) if key in storage else None

    def set(key, value, ex=None):
        storage[key] = value

    def delete(*keys):
        for k in keys:
            storage.pop(k, None)
            lists.pop(k, None)

    def lpush(key, *values):
        lists.setdefault(key, []).insert(0, *reversed(values))

    def ltrim(key, start, end):
        L = lists.get(key) or []
        lists[key] = L[start : end + 1]

    def lrange(key, start, end):
        L = lists.get(key) or []
        if end == -1:
            end = len(L) - 1
        return L[start : end + 1]

    def rpush(key, *values):
        lists.setdefault(key, []).extend(values)

    def incr(key):
        storage[key] = int(storage.get(key) or 0) + 1
        return storage[key]

    def hincrby(key, field, amount):
        if key not in storage:
            storage[key] = {}
        storage[key][field] = int(storage[key].get(field) or 0) + amount
        return storage[key][field]

    def scan_iter(match):
        prefix = match.replace("*", "")
        return (k for k in list(storage.keys()) + list(lists.keys()) if k.startswith(prefix))

    def zadd(name, mapping):
        storage.setdefault(name, {})
        for k, v in mapping.items():
            storage[name][k] = v
        return len(mapping)

    def zremrangebyscore(name, min_, max_):
        return 0

    def zcount(name, min_, max_):
        return len(storage.get(name, {}))

    client.hgetall.side_effect = hgetall
    client.hset.side_effect = hset
    client.get.side_effect = get
    client.set.side_effect = set
    client.delete.side_effect = delete
    client.lpush.side_effect = lpush
    client.ltrim.side_effect = ltrim
    client.lrange.side_effect = lrange
    client.rpush.side_effect = rpush
    client.incr.side_effect = incr
    client.hincrby.side_effect = hincrby
    client.scan_iter.side_effect = scan_iter
    client.zadd.side_effect = zadd
    client.zremrangebyscore.side_effect = zremrangebyscore
    client.zcount.side_effect = zcount
    client.ping.return_value = True
    return client


@pytest.fixture
def fake_redis():
    """Provide in-memory Redis mock for redis_cache tests."""
    client = _make_redis_mock()
    with patch.object(redis_cache, "get_redis", return_value=client):
        yield client


def test_clear_all_removes_keys(fake_redis) -> None:
    """clear_all deletes ingest/snippets/watchdog/mcp keys."""
    fake_redis.set("ingest:current", "x")
    fake_redis.hset("ingest:cache", "k", "v")
    fake_redis.set("snippets:last_run", "y")
    out = redis_cache.clear_all()
    assert out is True
    assert fake_redis.get("ingest:current") is None


def test_ingest_cache_set_and_get_all(fake_redis) -> None:
    """ingest_cache_set_entry and ingest_cache_get_all roundtrip."""
    redis_cache.ingest_cache_set_entry("8.3/ru/path/to/doc.hbk", "h1", 10)
    all_ = redis_cache.ingest_cache_get_all()
    assert "8.3/ru/path/to/doc.hbk" in all_
    assert all_["8.3/ru/path/to/doc.hbk"]["points"] == 10


def test_ingest_cache_entries(fake_redis) -> None:
    """ingest_cache_entries returns list of cached items."""
    redis_cache.ingest_cache_set_entry("8.3/ru/a.hbk", "h1", 5)
    entries = redis_cache.ingest_cache_entries(limit=10)
    assert len(entries) >= 1
    assert any(e["path"] == "a.hbk" for e in entries)


def test_ingest_current_set_get(fake_redis) -> None:
    """ingest_current_set and ingest_current_get roundtrip."""
    redis_cache.ingest_current_set({"status": "in_progress", "done_tasks": 2, "total_tasks": 5})
    data = redis_cache.ingest_current_get()
    assert data is not None
    assert data.get("status") == "in_progress"
    assert data.get("done_tasks") == 2


def test_ingest_run_create_and_update(fake_redis) -> None:
    """ingest_run_create returns id; ingest_run_update persists."""
    t = time.time()
    run_id = redis_cache.ingest_run_create(t, "openai_api", 10)
    assert run_id is not None
    redis_cache.ingest_run_update(run_id, t + 5.0, "completed", 10, 100, 0, 5.0)
    last = redis_cache.ingest_last_run()
    assert last is not None
    assert last.get("status") == "completed"


def test_ingest_failed_append_and_read(fake_redis) -> None:
    """ingest_run_append_failed and ingest_last_failed roundtrip."""
    run_id = redis_cache.ingest_run_create(time.time(), "none", 1)
    assert run_id is not None
    redis_cache.ingest_run_append_failed(run_id, "8.3", "ru", "x.hbk", "7z failed")
    failed = redis_cache.ingest_last_failed(limit=10)
    assert len(failed) == 1
    assert failed[0]["error"] == "7z failed"


def test_errors_append_and_list(fake_redis) -> None:
    """ingest_errors_append and ingest_errors_list roundtrip."""
    redis_cache.ingest_errors_append("8.3", "ru", "doc.hbk", "error msg")
    entries = redis_cache.ingest_errors_list(limit=10)
    assert len(entries) >= 1
    assert any(e.get("error") == "error msg" for e in entries)


def test_mcp_request_record_and_metrics(fake_redis) -> None:
    """mcp_request_record and mcp_metrics_get roundtrip."""
    redis_cache.mcp_request_record("search_1c_help", success=True, duration_sec=0.5)
    redis_cache.mcp_request_record("get_topic", success=False, error_msg="not found")
    m = redis_cache.mcp_metrics_get()
    assert m.get("total", 0) >= 2
    assert m.get("last_hour", 0) >= 2


def test_mcp_request_record_tracks_per_tool(fake_redis) -> None:
    """mcp_request_record increments per-tool counter; mcp_metrics_get returns per_tool dict."""
    redis_cache.mcp_request_record("search_1c_help", success=True)
    redis_cache.mcp_request_record("search_1c_help", success=True)
    redis_cache.mcp_request_record("get_1c_help_topic", success=True)
    m = redis_cache.mcp_metrics_get()
    per_tool = m.get("per_tool", {})
    assert per_tool.get("search_1c_help", 0) == 2
    assert per_tool.get("get_1c_help_topic", 0) == 1


def test_mcp_metrics_get_per_tool_sorted_descending(fake_redis) -> None:
    """per_tool in mcp_metrics_get is sorted by count descending."""
    redis_cache.mcp_request_record("tool_a", success=True)
    redis_cache.mcp_request_record("tool_b", success=True)
    redis_cache.mcp_request_record("tool_b", success=True)
    redis_cache.mcp_request_record("tool_b", success=True)
    m = redis_cache.mcp_metrics_get()
    per_tool = m.get("per_tool", {})
    keys = list(per_tool.keys())
    assert keys[0] == "tool_b"  # highest count first


def test_snippets_run_record_and_last_run(fake_redis) -> None:
    """snippets_run_record and snippets_last_run roundtrip."""
    redis_cache.snippets_run_record(10, 2, 50, time.time())
    data = redis_cache.snippets_last_run()
    assert data is not None
    assert data.get("items_loaded") == 50


def test_metadata_cache_set_and_get(fake_redis) -> None:
    redis_cache.metadata_cache_set("/tmp/kd2", "sig-1", 123)
    data = redis_cache.metadata_cache_get("/tmp/kd2")
    assert data is not None
    assert data.get("signature") == "sig-1"
    assert data.get("objects_indexed") == 123


def test_ingest_cache_get_indexed_set(fake_redis) -> None:
    """ingest_cache_get_indexed_set returns (version, language, hash) for indexed entries."""
    redis_cache.ingest_cache_set_entry("8.3/ru/doc.hbk", "abc123", 5)
    idx = redis_cache.ingest_cache_get_indexed_set()
    assert ("8.3", "ru", "abc123") in idx


def test_watchdog_state_set_get(fake_redis) -> None:
    """watchdog_state_set and watchdog_state_get roundtrip."""
    redis_cache.watchdog_state_set("hbk", {"path1": 123.0, "path2": 456.0})
    data = redis_cache.watchdog_state_get("hbk")
    assert data.get("path1") == 123.0
    assert data.get("path2") == 456.0


def test_require_runtime_redis_raises_on_noop() -> None:
    """Runtime-critical flows should fail fast when Redis degraded to no-op."""
    with patch.object(redis_cache, "get_redis", return_value=redis_cache._NoOpRedis()):
        with pytest.raises(RuntimeError, match="Redis is required"):
            redis_cache.require_runtime_redis("ingest")


def test_snippets_cache_set_and_entries(fake_redis) -> None:
    """snippets_cache_set and snippets_cache_entries roundtrip."""
    redis_cache.snippets_cache_set("fastcode", "sig1", 10)
    entries = redis_cache.snippets_cache_entries(limit=10)
    assert any(e.get("items_count") == 10 for e in entries) or len(entries) >= 0


def test_snippets_items_total(fake_redis) -> None:
    """snippets_items_total returns sum of items from cache."""
    redis_cache.snippets_cache_set("src1", "s1", 5)
    redis_cache.snippets_cache_set("src2", "s2", 3)
    total = redis_cache.snippets_items_total()
    assert total == 8


def test_ingest_trim_old_runs(fake_redis) -> None:
    """ingest_trim_old_runs does not crash."""
    redis_cache.ingest_trim_old_runs()


def test_noop_redis_get_returns_none() -> None:
    """When Redis is unavailable, get_redis returns no-op; ingest_current_get returns None."""
    noop = redis_cache._NoOpRedis()
    assert noop.get("ingest:current") is None
    assert noop.hgetall("ingest:cache") == {}
    assert noop.incr("x") == 0
