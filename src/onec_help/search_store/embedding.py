"""
Embedding backend: local (sentence-transformers), openai_api, or none (placeholder).
Retry, timeout and batch support for indexing. Lazy import of sentence-transformers.
"""

import hashlib
import json
import logging
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

try:
    import httpx as _httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _httpx = None  # type: ignore[assignment]
    _HTTPX_AVAILABLE = False

_http_client: Any = None
_http_client_lock = threading.Lock()


def _get_http_client() -> Any:
    """Return a module-level httpx.Client singleton (thread-safe, connection pooling).
    Falls back to None when httpx is not available; callers fall back to urllib in that case."""
    global _http_client
    if not _HTTPX_AVAILABLE or _httpx is None:
        return None
    if _http_client is None:
        with _http_client_lock:
            if _http_client is None:
                _http_client = _httpx.Client(
                    timeout=_httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
                    limits=_httpx.Limits(
                        max_connections=200,
                        max_keepalive_connections=100,
                    ),
                )
    return _http_client

from ..shared import env_config as _env_config  # noqa: E402


def sanitize_text_for_embedding(text: str) -> str:
    """Replace control chars (0x00-0x1F except \\n, \\r, \\t) with space before embedding."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


# Last resort when no model, no Qdrant collection, no EMBEDDING_DIMENSION (e.g. first run).
# Dimension is otherwise taken from model (startup) or from DB (when already running).
# 768 matches default model nomic-embed-text-v2-moe.
_DIMENSION_LAST_RESORT = 768
MAX_EMBEDDING_INPUT_CHARS = 2000
# When EMBEDDING_FORCE_BATCH=1: use max batch and workers for maximum throughput (any backend)
MAX_EMBEDDING_BATCH_SIZE = 256
# Max concurrent HTTP requests (each = one batch). LM Studio/Ollama "queue" = this many requests in flight.
MAX_EMBEDDING_WORKERS = 150
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0

_embedding_model = None

# All defaults from env_config (single source for env and docker-compose)
_EMBEDDING_BACKEND = _env_config.get_embedding_backend()
_EMBEDDING_MODEL = _env_config.get_embedding_model()
_LMSTUDIO_PREFERRED_EMBEDDING_MODELS = (
    "nomic-embed",  # nomic-embed-text-v2-moe (multilingual, 768), nomic-embed-text
    "paraphrase-multilingual",
    "all-MiniLM-L6-v2",
    "text-embedding-3-small",
)
_EMBEDDING_API_URL = _env_config.get_embedding_api_url()
_EMBEDDING_API_KEY = _env_config.get_embedding_api_key()
_EMBEDDING_DIMENSION = _env_config.get_embedding_dimension_env()


def _is_safe_embedding_url(url: str) -> bool:
    """Allow only http/https to prevent file:/ or custom scheme SSRF."""
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _embedding_timeout() -> int:
    return _env_config.get_embedding_timeout()


def _embedding_batch_timeout(batch_size: int) -> int:
    """Timeout for batch request. EMBEDDING_BATCH_TIMEOUT overrides formula when set."""
    v = _env_config.get_embedding_batch_timeout_raw()
    if v:
        try:
            return max(10, int(v))
        except ValueError:
            pass
    return max(_embedding_timeout(), 30 + batch_size // 10)


def _embedding_force_batch() -> bool:
    return _env_config.get_embedding_force_batch()


def _embedding_batch_size() -> int:
    if _embedding_force_batch():
        return MAX_EMBEDDING_BATCH_SIZE
    return _env_config.get_embedding_batch_size_default()


def _embedding_workers() -> int:
    if _embedding_force_batch():
        return MAX_EMBEDDING_WORKERS
    return _env_config.get_embedding_workers_default()


def _embedding_max_concurrent() -> int | None:
    """Max concurrent API batch requests (global). None = no limit. Use to avoid overloading LM Studio."""
    v = _env_config.get_embedding_max_concurrent_raw()
    if not v:
        return None
    try:
        n = int(v)
        return max(1, n) if n > 0 else None
    except ValueError:
        return None


_api_semaphore: threading.Semaphore | None = None
_api_semaphore_lock = threading.Lock()

# Таймаут ожидания слота (секунды). При зависании одного запроса остальные не блокируются вечно.
_ACQUIRE_SLOT_TIMEOUT = 300


def _acquire_api_slot() -> None:
    """Acquire a slot for API request if EMBEDDING_MAX_CONCURRENT is set.
    Raises TimeoutError if slot not available within _ACQUIRE_SLOT_TIMEOUT (avoid deadlock)."""
    global _api_semaphore
    max_c = _embedding_max_concurrent()
    if max_c is None:
        return
    with _api_semaphore_lock:
        if _api_semaphore is None:
            _api_semaphore = threading.Semaphore(max_c)
    if not _api_semaphore.acquire(timeout=_ACQUIRE_SLOT_TIMEOUT):
        raise TimeoutError(
            f"embedding API slot not available within {_ACQUIRE_SLOT_TIMEOUT}s "
            "(another request may be stuck)"
        )


def _release_api_slot() -> None:
    """Release API slot after request."""
    if _api_semaphore is not None:
        _api_semaphore.release()


_resolved_api_model_id: str | None = None
_cached_api_dimension: int | None = None
_cached_local_dimension: int | None = None
_cached_qdrant_dimension: int | None = None
_dimension_detecting: bool = False
_last_api_embedding_was_placeholder: bool = False
_embedding_api_available: bool | None = None
_fallback_log_count = 0

# In-memory cache for embedding vectors keyed by hash(sanitized+truncated text) to avoid repeated API calls.
_embedding_cache: dict[str, list[float]] = {}
_embedding_cache_order: list[str] = []  # FIFO eviction
_embedding_cache_lock = threading.Lock()
_EMBEDDING_CACHE_MAX: int | None = None  # None = not yet read; 0 = disabled


def _embedding_cache_max_size() -> int:
    """Max cache entries (EMBEDDING_CACHE_SIZE). 0 = disabled."""
    global _EMBEDDING_CACHE_MAX
    if _EMBEDDING_CACHE_MAX is None:
        try:
            v = _env_config.get_embedding_cache_size()
            _EMBEDDING_CACHE_MAX = max(0, int(v)) if v else 10000
        except ValueError:
            _EMBEDDING_CACHE_MAX = 10000
    return _EMBEDDING_CACHE_MAX


def _embedding_cache_key(text: str) -> str:
    """Cache key from sanitized and truncated text (same as sent to backend)."""
    t = sanitize_text_for_embedding(text)[:MAX_EMBEDDING_INPUT_CHARS]
    return hashlib.sha256(t.encode("utf-8", errors="replace")).hexdigest()


def _embedding_cache_get(key: str) -> list[float] | None:
    with _embedding_cache_lock:
        return _embedding_cache.get(key)


def _embedding_cache_set(key: str, vec: list[float]) -> None:
    max_sz = _embedding_cache_max_size()
    if max_sz <= 0:
        return
    with _embedding_cache_lock:
        if key in _embedding_cache:
            return
        while len(_embedding_cache) >= max_sz and _embedding_cache_order:
            old = _embedding_cache_order.pop(0)
            _embedding_cache.pop(old, None)
        _embedding_cache[key] = vec
        _embedding_cache_order.append(key)


def _retry_after_delay(err: BaseException) -> float | None:
    """For HTTP 429, return seconds to wait from Retry-After header, or None."""
    # urllib path
    if isinstance(err, urllib.error.HTTPError) and err.code == 429:
        ra = err.headers.get("Retry-After") if err.headers else None
        if not ra:
            return 60.0
        try:
            return min(120, max(1, int(ra)))
        except (ValueError, TypeError):
            return 60.0
    # httpx path
    if _HTTPX_AVAILABLE and _httpx is not None:
        try:
            if isinstance(err, _httpx.HTTPStatusError) and err.response.status_code == 429:
                ra = err.response.headers.get("Retry-After")
                if not ra:
                    return 60.0
                try:
                    return min(120, max(1, int(ra)))
                except (ValueError, TypeError):
                    return 60.0
        except Exception:
            pass
    return None


def _mask_url_for_log(url: str) -> str:
    """Return scheme+host for logging (avoid leaking full path/query)."""
    if not url:
        return "<not set>"
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        host = p.netloc or p.path.split("/")[0] or "?"
        return f"{p.scheme or 'http'}://{host}/..."
    except Exception:
        return "<url>"


def _log_fallback(reason: str) -> None:
    """Log once per 100 fallbacks to avoid spam."""
    global _fallback_log_count
    _fallback_log_count += 1
    if _fallback_log_count <= 1 or _fallback_log_count % 100 == 0:
        msg = f"[embedding] {reason}"
        if _fallback_log_count > 1:
            msg += f" (fallback count={_fallback_log_count})"
        print(msg, file=sys.stderr, flush=True)


_local_fallback_warned = False


def _warn_local_fallback_once() -> None:
    """Warn once when EMBEDDING_BACKEND=local but sentence-transformers is not installed; we use API (Ollama) instead."""
    global _local_fallback_warned
    if _local_fallback_warned:
        return
    _local_fallback_warned = True
    # Show actual env value so user can see where "local" comes from (e.g. .env overrides compose default)
    actual = _env_config.get_embedding_backend()
    print(
        f"[embedding] EMBEDDING_BACKEND is '{actual}' (from env) but sentence-transformers not installed; using API (Ollama) instead. "
        "For Docker/Ollama set EMBEDDING_BACKEND=openai_api in .env or remove it to use compose default.",
        file=sys.stderr,
        flush=True,
    )


def is_embedding_available() -> bool:
    """True if we can get meaningful embedding (not placeholder). Used for memory long-term storage."""
    if _EMBEDDING_BACKEND in ("none", "null", "off"):
        return False
    if _EMBEDDING_BACKEND == "openai_api":
        return _check_embedding_api_available()
    if _EMBEDDING_BACKEND == "local":
        # Даже если sentence-transformers не установлен, _get_embedding_local/_get_embedding_local_batch
        # сами перейдут на детерминированные векторы. Для памяти и стандартов это приемлемо, поэтому
        # считаем backend доступным по умолчанию.
        return True
    if _EMBEDDING_BACKEND == "deterministic":
        return True
    return False


def _check_embedding_api_available() -> bool:
    """Проверить доступность внешнего API эмбеддингов; при недоступности пишет в stderr и возвращает False."""
    global _embedding_api_available
    if _embedding_api_available is not None:
        return _embedding_api_available
    if _EMBEDDING_BACKEND != "openai_api" or not _EMBEDDING_API_URL:
        _embedding_api_available = True
        return True
    if not _is_safe_embedding_url(_EMBEDDING_API_URL):
        _embedding_api_available = False
        print(
            "[embedding] EMBEDDING_API_URL must use http:// or https:// (security).",
            file=sys.stderr,
            flush=True,
        )
        return False
    try:
        _headers: dict[str, str] = {"Content-Type": "application/json"}
        if _EMBEDDING_API_KEY:
            _headers["Authorization"] = f"Bearer {_EMBEDDING_API_KEY}"
        _client = _get_http_client()
        if _client is not None:
            _client.get(f"{_EMBEDDING_API_URL}/models", headers=_headers, timeout=5.0)
        else:
            req = urllib.request.Request(
                f"{_EMBEDDING_API_URL}/models", headers=_headers, method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        _embedding_api_available = True
        return True
    except Exception as e:
        _embedding_api_available = False
        print(
            f"[embedding] Внешний сервис эмбеддингов недоступен ({_mask_url_for_log(_EMBEDDING_API_URL)}): {type(e).__name__}",
            file=sys.stderr,
            flush=True,
        )
        print(
            "[embedding] Продолжаю индексирование с плейсхолдер-векторами (семантический поиск ограничен).",
            file=sys.stderr,
            flush=True,
        )
        return False


def _get_dimension_from_qdrant(collection: str | None = None) -> int | None:
    """Get vector size from Qdrant collection. Tries given collection, then onec_help, then onec_help_memory.
    Cached for default collection to avoid repeated Qdrant calls."""
    global _cached_qdrant_dimension
    main_coll = collection or _env_config.get_qdrant_collection()
    if collection is None and _cached_qdrant_dimension is not None:
        return _cached_qdrant_dimension
    try:
        from . import indexer

        for coll in (main_coll, "onec_help", "onec_help_memory"):
            dim = indexer.get_collection_vector_size(collection=coll)
            if dim and dim > 0:
                if collection is None:
                    _cached_qdrant_dimension = dim
                return dim
    except Exception as e:
        logging.getLogger(__name__).debug("get_dimension_from_qdrant failed: %s", e)
    return None


def _get_fallback_dim_from_qdrant() -> int | None:
    """When API is unavailable, get vector size from Qdrant for correct-dim placeholder. See _get_dimension_from_qdrant."""
    return _get_dimension_from_qdrant()


def get_embedding_dimension() -> int:
    """Return vector size for the current embedding backend (for collection creation).
    On startup: from model (local/openai_api) or from DB/env (deterministic/none).
    When already running: prefer dimension from Qdrant if collection exists, then EMBEDDING_DIMENSION."""
    global _cached_api_dimension, _cached_local_dimension, _dimension_detecting

    def _from_db_or_env() -> int:
        dim = _get_dimension_from_qdrant()
        if dim is not None:
            return dim
        if _EMBEDDING_DIMENSION:
            try:
                return int(_EMBEDDING_DIMENSION)
            except ValueError:
                pass
        return _DIMENSION_LAST_RESORT

    if _EMBEDDING_BACKEND == "deterministic":
        return _from_db_or_env()
    if _EMBEDDING_BACKEND == "local":
        if _cached_local_dimension is not None:
            return _cached_local_dimension
        try:
            vec = _get_embedding_local(".")
            _cached_local_dimension = len(vec)
            return _cached_local_dimension
        except Exception as e:
            logging.getLogger(__name__).debug("local embedding dimension detect failed: %s", e)
        return _from_db_or_env()
    if _EMBEDDING_BACKEND == "openai_api":
        if _cached_api_dimension is not None:
            return _cached_api_dimension
        if _EMBEDDING_API_URL:
            _dimension_detecting = True
            try:
                vec = _get_embedding_api_single(".")
                if not _last_api_embedding_was_placeholder:
                    _cached_api_dimension = len(vec)
                    return _cached_api_dimension
            except Exception as e:
                logging.getLogger(__name__).debug("embedding dimension detect failed: %s", e)
            finally:
                _dimension_detecting = False
        # When API URL is empty or API failed: use env at call time (so tests can patch and reload)
        env_dim = _env_config.get_embedding_dimension_env()
        if env_dim:
            try:
                return int(env_dim)
            except ValueError:
                pass
        if _EMBEDDING_DIMENSION:
            try:
                return int(_EMBEDDING_DIMENSION)
            except ValueError:
                pass
        dim = _get_fallback_dim_from_qdrant()
        if dim is not None:
            return dim
        return _DIMENSION_LAST_RESORT
    return _from_db_or_env()


def _resolve_openai_api_model() -> str:
    """Для openai_api: вернуть id модели — из списка на сервере (предпочтительная или первая)."""
    global _resolved_api_model_id
    if _resolved_api_model_id is not None:
        return _resolved_api_model_id
    model_ids: list[str] = []
    try:
        _headers2: dict[str, str] = {"Content-Type": "application/json"}
        if _EMBEDDING_API_KEY:
            _headers2["Authorization"] = f"Bearer {_EMBEDDING_API_KEY}"
        _client2 = _get_http_client()
        if _client2 is not None:
            _resp2 = _client2.get(f"{_EMBEDDING_API_URL}/models", headers=_headers2, timeout=10.0)
            data = _resp2.json()
        else:
            req = urllib.request.Request(
                f"{_EMBEDDING_API_URL}/models", headers=_headers2, method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                model_ids.append(str(item["id"]))
        for item in data.get("models") or []:
            if isinstance(item, dict) and item.get("key"):
                model_ids.append(str(item["key"]))
    except Exception as e:
        logging.getLogger(__name__).debug("models list fetch failed: %s", e)
    if _EMBEDDING_MODEL in model_ids:
        _resolved_api_model_id = _EMBEDDING_MODEL
        return _resolved_api_model_id
    for preferred in _LMSTUDIO_PREFERRED_EMBEDDING_MODELS:
        for mid in model_ids:
            if preferred in mid or mid in preferred:
                _resolved_api_model_id = mid
                return _resolved_api_model_id
    if model_ids:
        _resolved_api_model_id = model_ids[0]
        return _resolved_api_model_id
    base_url = _EMBEDDING_API_URL.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    try:
        _headers3: dict[str, str] = {"Content-Type": "application/json"}
        if _EMBEDDING_API_KEY:
            _headers3["Authorization"] = f"Bearer {_EMBEDDING_API_KEY}"
        _client3 = _get_http_client()
        if _client3 is not None:
            _resp3 = _client3.get(f"{base_url}/api/v1/models", headers=_headers3, timeout=10.0)
            native = _resp3.json()
        else:
            load_req = urllib.request.Request(
                f"{base_url}/api/v1/models", method="GET", headers=_headers3
            )
            with urllib.request.urlopen(load_req, timeout=10) as resp:
                native = json.loads(resp.read().decode("utf-8"))
        for item in native.get("models") or []:
            if isinstance(item, dict) and item.get("type") == "embedding" and item.get("key"):
                key = str(item["key"])
                if _client3 is not None:
                    _client3.post(
                        f"{base_url}/api/v1/models/load",
                        json={"model": key},
                        headers=_headers3,
                        timeout=120.0,
                    )
                else:
                    load_body = json.dumps({"model": key}).encode("utf-8")
                    post = urllib.request.Request(
                        f"{base_url}/api/v1/models/load",
                        data=load_body,
                        headers=_headers3,
                        method="POST",
                    )
                    urllib.request.urlopen(post, timeout=120)
                _resolved_api_model_id = key
                return _resolved_api_model_id
    except Exception as e:
        logging.getLogger(__name__).debug("model load API failed: %s", e)
    _resolved_api_model_id = _EMBEDDING_MODEL
    return _resolved_api_model_id


def _embedding_fallback_dim() -> int:
    """Dimension when API/model fails: use DB (Qdrant) so placeholder/deterministic matches collection."""
    if _dimension_detecting:
        dim = _get_fallback_dim_from_qdrant()
        return dim if dim is not None else _DIMENSION_LAST_RESORT
    dim = _get_fallback_dim_from_qdrant()
    if dim is not None:
        return dim
    env_dim = _env_config.get_embedding_dimension_env()
    if env_dim:
        try:
            return int(env_dim)
        except ValueError:
            pass
    return get_embedding_dimension()


def _get_embedding_placeholder(text: str, dimension: int | None = None) -> list[float]:
    """Deterministic placeholder vector (no model, no API). Dimension from DB or _embedding_fallback_dim."""
    if dimension is None:
        dimension = _embedding_fallback_dim()
    h = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    return [(h[i % len(h)] - 128) / 128.0 for i in range(dimension)]


def _get_embedding_deterministic(text: str, dimension: int | None = None) -> list[float]:
    """Deterministic embedding (NFC, tokens, hash) for 'only DB' scenario. Dimension from DB or get_embedding_dimension."""
    if dimension is None:
        dimension = get_embedding_dimension()
    text = unicodedata.normalize("NFC", sanitize_text_for_embedding(text))
    tokens = re.findall(r"\w+|[^\w\s]", text.lower())
    vec = [0.0] * dimension
    for i, t in enumerate(tokens):
        h = int(hashlib.sha256(t.encode("utf-8", errors="replace")).hexdigest()[:8], 16)
        vec[i % dimension] += (h % 256 - 128) / 128.0
    n = max(len(tokens), 1)
    return [v / n for v in vec]


def _get_embedding_local(text: str) -> list[float]:
    """Embedding via sentence-transformers (cached); if not installed, use API (Ollama) so it works by default in Docker."""
    global _embedding_model
    try:
        from sentence_transformers import SentenceTransformer

        if _embedding_model is None:
            _embedding_model = SentenceTransformer(_EMBEDDING_MODEL)
        return _embedding_model.encode(text, convert_to_numpy=True).tolist()
    except ImportError:
        _warn_local_fallback_once()
        return _get_embedding_api_single(text)


def _get_embedding_local_batch(texts: list[str]) -> list[list[float]]:
    """Batch embedding via sentence-transformers; if not installed, use API (Ollama) so it works by default in Docker."""
    global _embedding_model
    if not texts:
        return []
    try:
        from sentence_transformers import SentenceTransformer

        if _embedding_model is None:
            _embedding_model = SentenceTransformer(_EMBEDDING_MODEL)
        truncated = [t[:MAX_EMBEDDING_INPUT_CHARS] for t in texts]
        matrix = _embedding_model.encode(truncated, convert_to_numpy=True)
        return [row.tolist() for row in matrix]
    except ImportError:
        _warn_local_fallback_once()
        return _get_embedding_api_batch(texts)


def _get_embedding_api_single(text: str) -> list[float]:
    """Single request to OpenAI-compatible API with retry and configurable timeout."""
    global _last_api_embedding_was_placeholder
    if not _EMBEDDING_API_URL:
        _last_api_embedding_was_placeholder = True
        return _get_embedding_deterministic(text, _embedding_fallback_dim())
    if not _check_embedding_api_available():
        _last_api_embedding_was_placeholder = True
        return _get_embedding_deterministic(text, _embedding_fallback_dim())
    model_id = _resolve_openai_api_model()
    url = f"{_EMBEDDING_API_URL}/embeddings"
    body = json.dumps(
        {
            "model": model_id,
            "input": text[:MAX_EMBEDDING_INPUT_CHARS],
        }
    ).encode("utf-8")
    timeout = _embedding_timeout()
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        _acquire_api_slot()
        try:
            _emb_headers: dict[str, str] = {"Content-Type": "application/json"}
            if _EMBEDDING_API_KEY:
                _emb_headers["Authorization"] = f"Bearer {_EMBEDDING_API_KEY}"
            _emb_client = _get_http_client()
            if _emb_client is not None:
                _emb_resp = _emb_client.post(
                    url, content=body, headers=_emb_headers, timeout=float(timeout)
                )
                _emb_resp.raise_for_status()
                data = _emb_resp.json()
            else:
                req = urllib.request.Request(url, data=body, headers=_emb_headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            out = data.get("data") or []
            first = out[0] if out else None
            if isinstance(first, dict) and "embedding" in first:
                _last_api_embedding_was_placeholder = False
                return list(first["embedding"])
            break
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                delay = _retry_after_delay(e) or RETRY_BASE_DELAY * (2**attempt)
                time.sleep(delay)
        finally:
            _release_api_slot()
    global _resolved_api_model_id
    _resolved_api_model_id = None
    _last_api_embedding_was_placeholder = True
    _log_fallback(f"embedding API error/timeout, using deterministic: {type(last_err).__name__}")
    return _get_embedding_deterministic(text, _embedding_fallback_dim())


def _get_embedding_api_batch(texts: list[str]) -> list[list[float]]:
    """Batch request to OpenAI-compatible API (input array). Fallback to single requests on error."""
    if not texts:
        return []
    if not _EMBEDDING_API_URL:
        dim = _embedding_fallback_dim()
        return [_get_embedding_deterministic(t, dim) for t in texts]
    if not _check_embedding_api_available():
        dim = _embedding_fallback_dim()
        return [_get_embedding_deterministic(t, dim) for t in texts]
    model_id = _resolve_openai_api_model()
    truncated = [t[:MAX_EMBEDDING_INPUT_CHARS] for t in texts]
    url = f"{_EMBEDDING_API_URL}/embeddings"
    body = json.dumps({"model": model_id, "input": truncated}).encode("utf-8")
    batch_timeout = _embedding_batch_timeout(len(texts))
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        _acquire_api_slot()
        try:
            _batch_headers: dict[str, str] = {"Content-Type": "application/json"}
            if _EMBEDDING_API_KEY:
                _batch_headers["Authorization"] = f"Bearer {_EMBEDDING_API_KEY}"
            _batch_client = _get_http_client()
            if _batch_client is not None:
                _batch_resp = _batch_client.post(
                    url, content=body, headers=_batch_headers, timeout=float(batch_timeout)
                )
                _batch_resp.raise_for_status()
                data = _batch_resp.json()
            else:
                req = urllib.request.Request(url, data=body, headers=_batch_headers, method="POST")
                with urllib.request.urlopen(req, timeout=batch_timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            out = data.get("data") or []
            if len(out) >= len(texts):
                result = []
                for i, item in enumerate(out[: len(texts)]):
                    if isinstance(item, dict) and "embedding" in item:
                        result.append(list(item["embedding"]))
                    else:
                        result.append(
                            _get_embedding_deterministic(truncated[i], _embedding_fallback_dim())
                        )
                return result
            break
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                delay = _retry_after_delay(e) or RETRY_BASE_DELAY * (2**attempt)
                time.sleep(delay)
        finally:
            _release_api_slot()
    global _resolved_api_model_id
    _resolved_api_model_id = None
    # Retry with smaller batches before falling back to N single requests
    if len(texts) > 1:
        _log_fallback(
            f"embedding API batch error ({len(texts)} texts), retrying with smaller batches: {type(last_err).__name__}"
        )
        mid = len(texts) // 2
        return _get_embedding_api_batch(texts[:mid]) + _get_embedding_api_batch(texts[mid:])
    _log_fallback(
        f"embedding API batch error, falling back to single request: {type(last_err).__name__}"
    )
    dim = _embedding_fallback_dim()
    return [_get_embedding_deterministic(t, dim) for t in texts]


def _get_embedding_api_batch_parallel(
    texts: list[str],
    batch_size: int,
    workers: int,
    on_batch_done: Any = None,
) -> list[list[float]]:
    """Split texts into batches and call API in parallel (ThreadPool).
    on_batch_done(done, total): optional per-batch progress callback (thread-safe)."""
    if not texts:
        return []
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    total = len(texts)
    done_lock = threading.Lock()
    done_count = [0]

    def _call_and_report(batch: list[str]) -> list[list[float]]:
        vecs = _get_embedding_api_batch(batch)
        if on_batch_done is not None:
            with done_lock:
                done_count[0] += len(vecs)
                d = done_count[0]
            try:
                on_batch_done(d, total)
            except Exception:
                pass
        return vecs

    if workers <= 1 or len(batches) <= 1:
        results: list[list[float]] = []
        for batch in batches:
            results.extend(_call_and_report(batch))
        return results
    batch_results: list[list[list[float]]] = [None] * len(batches)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as executor:
        future_to_idx = {
            executor.submit(_call_and_report, b): i for i, b in enumerate(batches)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            batch_results[idx] = future.result()
    results = []
    for vecs in batch_results:
        results.extend(vecs)
    return results


def get_embedding(text: str, target_dimension: int | None = None) -> list[float]:
    """Produce embedding for one text; backend from env: local, openai_api, deterministic, or none (placeholder).
    If target_dimension is set and the backend returns a vector of different length, a placeholder vector
    of target_dimension is returned so the caller (e.g. search) can use the collection's vector size.
    When EMBEDDING_CACHE_SIZE > 0, results for local/openai_api are cached by text hash to avoid repeated API calls."""
    text = sanitize_text_for_embedding(text)
    dim_fallback = target_dimension if target_dimension is not None else None
    if _EMBEDDING_BACKEND in ("none", "null", "off"):
        dim = dim_fallback or get_embedding_dimension()
        return _get_embedding_placeholder(text, dim)
    if _EMBEDDING_BACKEND == "deterministic":
        vec = _get_embedding_deterministic(text)
    else:
        use_cache = _embedding_cache_max_size() > 0 and _EMBEDDING_BACKEND in (
            "local",
            "openai_api",
        )
        if use_cache:
            key = _embedding_cache_key(text)
            cached = _embedding_cache_get(key)
            if cached is not None:
                return list(cached)
        if _EMBEDDING_BACKEND == "openai_api":
            vec = _get_embedding_api_single(text)
        else:
            vec = _get_embedding_local(text)
        if use_cache:
            _embedding_cache_set(key, vec)
    if target_dimension is not None and len(vec) != target_dimension:
        return _get_embedding_placeholder(text, target_dimension)
    return vec


def get_embedding_batch(
    texts: list[str],
    batch_size: int | None = None,
    workers: int | None = None,
    progress_callback=None,
    target_dimension: int | None = None,
) -> list[list[float]]:
    """
    Produce embeddings for a list of texts. Uses batch API where supported;
    for openai_api, workers > 1 runs batches in parallel.
    When EMBEDDING_CACHE_SIZE > 0, results for local/openai_api are cached by text hash.
    progress_callback(done_in_batch, total_in_batch): optional, called after each chunk.
    """
    if not texts:
        return []
    texts = [sanitize_text_for_embedding(t) for t in texts]
    size = batch_size if batch_size is not None else _embedding_batch_size()
    w = workers if workers is not None else _embedding_workers()
    total_count = len(texts)

    def _report(done: int, total: int) -> None:
        if progress_callback and callable(progress_callback):
            try:
                progress_callback(done, total)
            except Exception:
                pass

    if _EMBEDDING_BACKEND in ("none", "null", "off"):
        dim = target_dimension if target_dimension is not None else get_embedding_dimension()
        return [_get_embedding_placeholder(t, dim) for t in texts]

    if _EMBEDDING_BACKEND == "deterministic":
        _report(0, total_count)
        out = [_get_embedding_deterministic(t) for t in texts]
        if target_dimension is not None:
            out = [
                vec if len(vec) == target_dimension else _get_embedding_placeholder(text, target_dimension)
                for text, vec in zip(texts, out, strict=True)
            ]
        _report(total_count, total_count)
        return out

    use_cache = _embedding_cache_max_size() > 0 and _EMBEDDING_BACKEND in ("local", "openai_api")
    if use_cache:
        keys = [_embedding_cache_key(t) for t in texts]
        cached = [_embedding_cache_get(k) for k in keys]
        uncached_idx = [i for i in range(len(texts)) if cached[i] is None]
        if not uncached_idx:
            result = [list(cached[i]) for i in range(len(texts))]
            if target_dimension is not None:
                return [
                    vec if len(vec) == target_dimension else _get_embedding_placeholder(text, target_dimension)
                    for text, vec in zip(texts, result, strict=True)
                ]
            return result
        uncached_texts = [texts[i] for i in uncached_idx]
    else:
        uncached_idx = list(range(len(texts)))
        uncached_texts = texts

    embed_total = len(uncached_texts)
    _report(0, embed_total)

    if _EMBEDDING_BACKEND == "openai_api":
        uncached_vecs = _get_embedding_api_batch_parallel(
            uncached_texts, size, w,
            on_batch_done=lambda done, total: _report(done, total),
        )
        _report(embed_total, embed_total)
    else:
        uncached_vecs = []
        for i in range(0, len(uncached_texts), size):
            chunk = uncached_texts[i : i + size]
            uncached_vecs.extend(_get_embedding_local_batch(chunk))
            _report(len(uncached_vecs), embed_total)

    if use_cache:
        for j, i in enumerate(uncached_idx):
            _embedding_cache_set(keys[i], uncached_vecs[j])
        result = []
        j = 0
        for i in range(len(texts)):
            if cached[i] is not None:
                result.append(list(cached[i]))
            else:
                result.append(uncached_vecs[j])
                j += 1
        if target_dimension is not None:
            return [
                vec if len(vec) == target_dimension else _get_embedding_placeholder(text, target_dimension)
                for text, vec in zip(texts, result, strict=True)
            ]
        return result
    if target_dimension is not None:
        return [
            vec if len(vec) == target_dimension else _get_embedding_placeholder(text, target_dimension)
            for text, vec in zip(texts, uncached_vecs, strict=True)
        ]
    return uncached_vecs
