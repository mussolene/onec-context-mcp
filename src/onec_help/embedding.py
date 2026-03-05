"""
Embedding backend: local (sentence-transformers), openai_api, or none (placeholder).
Retry, timeout and batch support for indexing. Lazy import of sentence-transformers.
"""

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def sanitize_text_for_embedding(text: str) -> str:
    """Replace control chars (0x00-0x1F except \\n, \\r, \\t) with space before embedding."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


# Last resort when no model, no Qdrant collection, no EMBEDDING_DIMENSION (e.g. first run).
# Dimension is otherwise taken from model (startup) or from DB (when already running).
_DIMENSION_LAST_RESORT = 384
MAX_EMBEDDING_INPUT_CHARS = 2000
DEFAULT_EMBEDDING_BATCH_SIZE = 64
DEFAULT_EMBEDDING_WORKERS = 4
# When EMBEDDING_FORCE_BATCH=1: use max batch and workers for maximum throughput (any backend)
MAX_EMBEDDING_BATCH_SIZE = 256
MAX_EMBEDDING_WORKERS = 16
DEFAULT_EMBEDDING_TIMEOUT = 60
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0

_embedding_model = None

_EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "local").strip().lower()
# Должна совпадать при индексации (ingest) и при поиске (MCP/search_index), иначе семантика ломается
_EMBEDDING_MODEL = (
    os.environ.get("EMBEDDING_MODEL") or "paraphrase-multilingual-MiniLM-L12-v2"
).strip()
_LMSTUDIO_PREFERRED_EMBEDDING_MODELS = (
    "paraphrase-multilingual",
    "all-MiniLM-L6-v2",
    "text-embedding-3-small",
)
_EMBEDDING_API_URL = (
    (os.environ.get("EMBEDDING_API_URL") or "http://localhost:1234/v1").strip().rstrip("/")
)


def _is_safe_embedding_url(url: str) -> bool:
    """Allow only http/https to prevent file:/ or custom scheme SSRF."""
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


_EMBEDDING_API_KEY = (os.environ.get("EMBEDDING_API_KEY") or "").strip()
_EMBEDDING_DIMENSION = (os.environ.get("EMBEDDING_DIMENSION") or "").strip()


def _embedding_timeout() -> int:
    try:
        return max(5, int(os.environ.get("EMBEDDING_TIMEOUT", DEFAULT_EMBEDDING_TIMEOUT)))
    except ValueError:
        return DEFAULT_EMBEDDING_TIMEOUT


def _embedding_batch_timeout(batch_size: int) -> int:
    """Timeout for batch request. EMBEDDING_BATCH_TIMEOUT overrides formula when set."""
    v = (os.environ.get("EMBEDDING_BATCH_TIMEOUT") or "").strip()
    if v:
        try:
            return max(10, int(v))
        except ValueError:
            pass
    return max(_embedding_timeout(), 30 + batch_size // 10)


def _embedding_force_batch() -> bool:
    """True if EMBEDDING_FORCE_BATCH is set (1, true, yes) — use max batch size and workers."""
    v = (os.environ.get("EMBEDDING_FORCE_BATCH") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _embedding_batch_size() -> int:
    if _embedding_force_batch():
        return MAX_EMBEDDING_BATCH_SIZE
    try:
        return max(
            1,
            min(
                MAX_EMBEDDING_BATCH_SIZE,
                int(os.environ.get("EMBEDDING_BATCH_SIZE", DEFAULT_EMBEDDING_BATCH_SIZE)),
            ),
        )
    except ValueError:
        return DEFAULT_EMBEDDING_BATCH_SIZE


def _embedding_workers() -> int:
    if _embedding_force_batch():
        return MAX_EMBEDDING_WORKERS
    try:
        return max(
            1,
            min(
                MAX_EMBEDDING_WORKERS,
                int(os.environ.get("EMBEDDING_WORKERS", DEFAULT_EMBEDDING_WORKERS)),
            ),
        )
    except ValueError:
        return DEFAULT_EMBEDDING_WORKERS


def _embedding_max_concurrent() -> int | None:
    """Max concurrent API batch requests (global). None = no limit. Use to avoid overloading LM Studio."""
    v = (os.environ.get("EMBEDDING_MAX_CONCURRENT") or "").strip()
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


def _retry_after_delay(err: BaseException) -> float | None:
    """For HTTP 429, return seconds to wait from Retry-After header, or None."""
    if not isinstance(err, urllib.error.HTTPError) or err.code != 429:
        return None
    ra = err.headers.get("Retry-After") if err.headers else None
    if not ra:
        return 60.0  # default for 429 when no Retry-After
    try:
        return min(120, max(1, int(ra)))
    except (ValueError, TypeError):
        return 60.0


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


def is_embedding_available() -> bool:
    """True if we can get meaningful embedding (not placeholder). Used for memory long-term storage."""
    if _EMBEDDING_BACKEND in ("none", "null", "off"):
        return False
    if _EMBEDDING_BACKEND == "openai_api":
        return _check_embedding_api_available()
    if _EMBEDDING_BACKEND == "local":
        try:
            global _embedding_model
            if _embedding_model is None:
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(_EMBEDDING_MODEL)
            return True
        except Exception:
            return False
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
        req = urllib.request.Request(
            f"{_EMBEDDING_API_URL}/models",
            headers={"Content-Type": "application/json"}
            | ({"Authorization": f"Bearer {_EMBEDDING_API_KEY}"} if _EMBEDDING_API_KEY else {}),
            method="GET",
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
    main_coll = collection or os.environ.get("QDRANT_COLLECTION", "onec_help")
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
        req = urllib.request.Request(
            f"{_EMBEDDING_API_URL}/models",
            headers={"Content-Type": "application/json"}
            | ({"Authorization": f"Bearer {_EMBEDDING_API_KEY}"} if _EMBEDDING_API_KEY else {}),
            method="GET",
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
        load_req = urllib.request.Request(
            f"{base_url}/api/v1/models",
            method="GET",
            headers={"Content-Type": "application/json"}
            | ({"Authorization": f"Bearer {_EMBEDDING_API_KEY}"} if _EMBEDDING_API_KEY else {}),
        )
        with urllib.request.urlopen(load_req, timeout=10) as resp:
            native = json.loads(resp.read().decode("utf-8"))
        for item in native.get("models") or []:
            if isinstance(item, dict) and item.get("type") == "embedding" and item.get("key"):
                key = str(item["key"])
                load_body = json.dumps({"model": key}).encode("utf-8")
                post = urllib.request.Request(
                    f"{base_url}/api/v1/models/load",
                    data=load_body,
                    headers={"Content-Type": "application/json"}
                    | (
                        {"Authorization": f"Bearer {_EMBEDDING_API_KEY}"}
                        if _EMBEDDING_API_KEY
                        else {}
                    ),
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
    env_dim = (os.environ.get("EMBEDDING_DIMENSION") or "").strip()
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
    """Embedding via sentence-transformers (cached); fallback to deterministic with DB dimension if unavailable."""
    global _embedding_model
    try:
        from sentence_transformers import SentenceTransformer

        if _embedding_model is None:
            _embedding_model = SentenceTransformer(_EMBEDDING_MODEL)
        return _embedding_model.encode(text, convert_to_numpy=True).tolist()
    except ImportError:
        return _get_embedding_deterministic(text, _embedding_fallback_dim())


def _get_embedding_local_batch(texts: list[str]) -> list[list[float]]:
    """Batch embedding via sentence-transformers."""
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
        dim = _embedding_fallback_dim()
        return [_get_embedding_deterministic(t, dim) for t in texts]


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
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    **(
                        {"Authorization": f"Bearer {_EMBEDDING_API_KEY}"}
                        if _EMBEDDING_API_KEY
                        else {}
                    ),
                },
                method="POST",
            )
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
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    **(
                        {"Authorization": f"Bearer {_EMBEDDING_API_KEY}"}
                        if _EMBEDDING_API_KEY
                        else {}
                    ),
                },
                method="POST",
            )
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
) -> list[list[float]]:
    """Split texts into batches and call API in parallel (ThreadPool)."""
    if not texts:
        return []
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    if workers <= 1 or len(batches) <= 1:
        results: list[list[float]] = []
        for batch in batches:
            results.extend(_get_embedding_api_batch(batch))
        return results
    batch_results: list[list[list[float]]] = [None] * len(batches)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as executor:
        future_to_idx = {
            executor.submit(_get_embedding_api_batch, b): i for i, b in enumerate(batches)
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
    of target_dimension is returned so the caller (e.g. search) can use the collection's vector size."""
    text = sanitize_text_for_embedding(text)
    dim_fallback = target_dimension if target_dimension is not None else None
    if _EMBEDDING_BACKEND in ("none", "null", "off"):
        dim = dim_fallback or get_embedding_dimension()
        return _get_embedding_placeholder(text, dim)
    if _EMBEDDING_BACKEND == "deterministic":
        vec = _get_embedding_deterministic(text)
    elif _EMBEDDING_BACKEND == "openai_api":
        vec = _get_embedding_api_single(text)
    else:
        vec = _get_embedding_local(text)
    if target_dimension is not None and len(vec) != target_dimension:
        return _get_embedding_placeholder(text, target_dimension)
    return vec


def get_embedding_batch(
    texts: list[str],
    batch_size: int | None = None,
    workers: int | None = None,
) -> list[list[float]]:
    """
    Produce embeddings for a list of texts. Uses batch API where supported;
    for openai_api, workers > 1 runs batches in parallel.
    """
    if not texts:
        return []
    texts = [sanitize_text_for_embedding(t) for t in texts]
    size = batch_size if batch_size is not None else _embedding_batch_size()
    w = workers if workers is not None else _embedding_workers()

    if _EMBEDDING_BACKEND in ("none", "null", "off"):
        dim = get_embedding_dimension()
        return [_get_embedding_placeholder(t, dim) for t in texts]

    if _EMBEDDING_BACKEND == "deterministic":
        return [_get_embedding_deterministic(t) for t in texts]

    if _EMBEDDING_BACKEND == "openai_api":
        return _get_embedding_api_batch_parallel(texts, size, w)

    results = []
    for i in range(0, len(texts), size):
        chunk = texts[i : i + size]
        results.extend(_get_embedding_local_batch(chunk))
    return results
