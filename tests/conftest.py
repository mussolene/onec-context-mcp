"""Pytest fixtures."""

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


# Pre-import submodules so patch() targets resolve under editable installs.
def _ensure_onec_help_submodules():
    """Import frequently patched modules so dotted patch paths resolve reliably."""
    for _name in (
        "onec_help.shared._http",
        "onec_help.search_store.embedding",
        "onec_help.help_core.hbk_container",
        "onec_help.search_store.indexer",
        "onec_help.knowledge.memory",
        "onec_help.knowledge.loaders.parse_fastcode",
        "onec_help.knowledge.loaders.parse_its_v8std",
        "onec_help.knowledge.loaders.standards_loader",
        "onec_help.help_core.toc_parser",
        "onec_help.help_core.unpack",
        "onec_help.runtime.watchdog",
        "onec_help.interfaces.cli",
        "onec_help.interfaces.mcp_server",
    ):
        importlib.import_module(_name)


_ensure_onec_help_submodules()


@pytest.fixture(autouse=True)
def _ensure_onec_help_refs():
    """Re-bind submodules before each test (patch target lookup)."""
    _ensure_onec_help_submodules()
    yield


@pytest.fixture(autouse=True)
def _disable_httpx_in_tests():
    """Force embedding module to use urllib path in tests.
    Tests mock urllib.request.urlopen; setting sys.modules['httpx'] = None makes
    'import httpx' raise ImportError even after importlib.reload(), so _HTTPX_AVAILABLE
    stays False and all HTTP calls go through the urllib fallback path."""
    import sys

    with patch.dict(sys.modules, {"httpx": None}):
        yield


@pytest.fixture(autouse=True)
def _reset_qdrant_singletons():
    """Reset shared QdrantClient singletons between tests.
    Singletons are module-level globals; without reset, a mock from one test leaks into the next."""
    import onec_help.knowledge.memory as _memory
    import onec_help.search_store.indexer as _indexer

    _indexer._default_qdrant_client = None
    _indexer._default_qdrant_client_key = None
    _memory._memory_qdrant_client = None
    yield
    _indexer._default_qdrant_client = None
    _indexer._default_qdrant_client_key = None
    _memory._memory_qdrant_client = None


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def help_sample_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "help_sample"


@pytest.fixture
def sample_html(help_sample_dir: Path) -> Path:
    return help_sample_dir / "field626.html"


@pytest.fixture
def categories_file(help_sample_dir: Path) -> Path:
    return help_sample_dir / "__categories__"


def _nosync_root() -> Path:
    """Root of .nosync / nosync project (crypto library). Env NOSYNC_DIR overrides."""
    root = Path(__file__).resolve().parent.parent
    env_path = __import__("os").environ.get("NOSYNC_DIR")
    if env_path:
        return Path(env_path).resolve()
    for name in (".nosync", "nosync"):
        p = root / name
        if p.is_dir():
            return p
    return root / ".nosync"


@pytest.fixture
def nosync_root() -> Path:
    """Path to .nosync (or nosync) project root for crypto library tests."""
    return _nosync_root()


@pytest.fixture(autouse=True)
def embedding_backend_none_for_network_tests(request):
    """Use EMBEDDING_BACKEND=none in indexer/embedding tests to avoid HuggingFace download."""
    path = str(getattr(request, "fspath", None) or "")
    if "test_indexer" in path or "test_embedding" in path:
        with patch.dict("os.environ", {"EMBEDDING_BACKEND": "none"}, clear=False):
            import onec_help.search_store.embedding as emb

            importlib.reload(emb)
            _ensure_onec_help_submodules()
            yield
    else:
        yield


@pytest.fixture(autouse=True)
def isolate_bm25_vocab_for_indexer_tests(request, tmp_path):
    """Redirect BM25 vocab to tmp_path in indexer tests to avoid overwriting data/bm25_vocab."""
    path = str(getattr(request, "fspath", None) or "")
    if "test_indexer" in path:
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}, clear=False):
            yield
    else:
        yield


@pytest.fixture(autouse=True)
def isolate_ingest_cache(tmp_path_factory):
    """Redirect ingest cache dir (markers) to temp. Cache data is in Redis (mocked in test_ingest)."""
    base = tmp_path_factory.mktemp("ingest_cache_isolate")
    cache_dir = base / "ingest_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "ingest_cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        yield


@pytest.fixture(autouse=True)
def redis_mock_for_ingest(request):
    """Use fakeredis (or in-memory mock) so no test ever touches real Redis.
    Real Redis may be shared with Docker (e.g. localhost:6379 = same as container). If a test called
    clear_all() or any code that writes watchdog:* keys, the container's watchdog would see empty
    state and trigger load-snippets/load-standards. Therefore Redis is mocked for ALL tests."""
    try:
        path = str(request.node.fspath) if hasattr(request.node, "fspath") else ""
    except Exception:
        path = ""
    # Apply to all test files (any path under tests/) so Docker/watchdog is never affected
    if "tests" not in path.replace("\\", "/"):
        yield
        return
    try:
        import fakeredis

        client = fakeredis.FakeRedis(decode_responses=True)
    except ImportError:
        # Fallback: minimal in-memory Redis mock (dict-based) so tests don't require fakeredis
        from unittest.mock import MagicMock

        storage = {}
        client = MagicMock()

        def hgetall(key):
            return storage.get(key, {})

        def hset(key, key_or_map=None, value=None, mapping=None):
            if key not in storage:
                storage[key] = {}
            if mapping is not None:
                storage[key].update(mapping)
            elif key_or_map is not None and value is not None:
                storage[key][key_or_map] = value

        def get(key):
            return storage.get(key)

        def set(key, value, ex=None):
            storage[key] = value

        def delete(*keys):
            for k in keys:
                storage.pop(k, None)

        def lpush(key, *values):
            storage.setdefault(key, []).insert(0, *reversed(values))

        def ltrim(key, start, end):
            storage[key] = (storage.get(key) or [])[start : end + 1]

        def lrange(key, start, end):
            L = storage.get(key) or []
            if end == -1:
                end = len(L)
            return L[start : end + 1]

        def rpush(key, *values):
            storage.setdefault(key, []).extend(values)

        def incr(key):
            storage[key] = int(storage.get(key) or 0) + 1
            return storage[key]

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
        client.scan_iter.return_value = []
        client.ping.return_value = True
    with patch("onec_help.runtime.redis_cache.get_redis", return_value=client):
        yield
