"""Build and query Qdrant index from Markdown help."""

import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchAny,
        MatchValue,
        Modifier,
        OptimizersConfigDiff,
        PointStruct,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )
except ImportError:
    QdrantClient = None  # type: ignore
    PointStruct = None  # type: ignore
    VectorParams = None  # type: ignore
    Distance = None  # type: ignore
    FieldCondition = None  # type: ignore
    Filter = None  # type: ignore
    MatchAny = None  # type: ignore
    MatchValue = None  # type: ignore
    OptimizersConfigDiff = None  # type: ignore
    SparseVector = None  # type: ignore
    SparseVectorParams = None  # type: ignore
    Modifier = None  # type: ignore

from ..help_core.toc_parser import (
    load_toc_json,
    path_to_section_and_title_from_toc,
)
from ..shared import env_config
from ..shared._utils import path_inside_base, safe_error_message

COLLECTION_NAME = "onec_help_api_members"
SNIPPET_MAX_CHARS = 850

# Shared QdrantClient for the default host/port (read hot-path: search, get_topic, etc.).
# QdrantClient (httpx-based) is documented thread-safe for concurrent reads.
# Write/ingest functions that use custom host/port or long timeouts create their own client.
_default_qdrant_client: "QdrantClient | None" = None
_default_qdrant_client_lock = threading.Lock()
_default_qdrant_client_key: tuple[str, int] | None = None


def _get_default_qdrant_client(host: str, port: int) -> "QdrantClient":
    """Return shared QdrantClient for given host/port (double-checked locking).
    Creates a new client if host/port changed (e.g. env reload or tests)."""
    global _default_qdrant_client, _default_qdrant_client_key
    key = (host, port)
    if _default_qdrant_client is not None and _default_qdrant_client_key == key:
        return _default_qdrant_client
    with _default_qdrant_client_lock:
        if _default_qdrant_client is None or _default_qdrant_client_key != key:
            _default_qdrant_client = QdrantClient(host=host, port=port, check_compatibility=False)
            _default_qdrant_client_key = key
        return _default_qdrant_client


# Regex for CamelCase and Cyrillic identifiers (min 3 chars) for keyword extraction
_KEYWORDS_PATTERN = re.compile(r"[А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9]{2,}")

# Segment patterns to infer entity_type from section_path or breadcrumb
_ENTITY_PATTERNS: dict[str, list[str]] = {
    "method": ["методы", "methods"],
    "property": ["свойства", "properties"],
    "type": ["типы", "types"],
    "function": ["функции", "functions"],
    "constructor": ["конструктор", "constructor"],
    "event": ["события", "events"],
}


def _infer_entity_type(section_path: str, breadcrumb: list[str] | None) -> str:
    """Infer entity_type from section_path or breadcrumb (last segments)."""
    segments: list[str] = []
    if section_path:
        segments.extend(s.strip().lower() for s in section_path.replace("\\", "/").split("/") if s)
    if breadcrumb:
        segments.extend(str(b).strip().lower() for b in breadcrumb if b)
    for ent, patterns in _ENTITY_PATTERNS.items():
        for p in patterns:
            if any(seg == p for seg in segments[-3:]):  # check last 3 segments
                return ent
    return "topic"


def _version_sort_key(version_str: str) -> tuple[int, ...]:
    """Parse version string (e.g. '8.3.27.1859') to comparable tuple for sorting (newest first)."""
    if not version_str or not isinstance(version_str, str):
        return (0,)
    parts: list[int] = []
    for s in version_str.strip().split("."):
        try:
            parts.append(int(s))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def _extract_keywords(text: str, max_tokens: int = 50) -> list[str]:
    """Extract CamelCase and Cyrillic identifiers from text for payload.keywords."""
    if not text:
        return []
    tokens = _KEYWORDS_PATTERN.findall(text)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        tl = t.lower()
        if tl not in seen and len(out) < max_tokens:
            seen.add(tl)
            out.append(t)
    return out


def get_embedding_dimension() -> int:
    """Return vector size for the current embedding backend (for collection creation). Lazy import."""
    from . import embedding

    return embedding.get_embedding_dimension()


def get_collection_vector_size(
    collection: str = COLLECTION_NAME,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> int | None:
    """Return vector dimension from Qdrant collection config, or None if unavailable.
    Used as fallback when embedding API is down to produce correct-dim placeholder vectors."""
    if QdrantClient is None:
        return None
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    try:
        client = _get_default_qdrant_client(host, port)
        if not client.collection_exists(collection):
            return None
        info = client.get_collection(collection)
        config = getattr(info, "config", None)
        if not config:
            return None
        params = getattr(config, "params", None)
        if not params:
            return None
        vectors = getattr(params, "vectors", None)
        if vectors is None:
            return None
        # VectorsConfig: VectorParams or Dict[str, VectorParams]
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if hasattr(first, "size"):
                return int(first.size)
        return None
    except Exception as e:
        logging.getLogger(__name__).debug("get_collection_vector_size failed: %s", e)
        return None


def _path_to_point_id(rel_path: str, version: str = "", language: str = "") -> int:
    """Stable integer id from path (and optional version/language) for incremental upsert."""
    import hashlib

    key = f"{version}|{language}|{rel_path}"
    h = hashlib.sha256(key.encode()).hexdigest()[:14]
    return int(h, 16) % (2**63)


def _build_path_to_section(
    nodes: list, base_path: str = "", breadcrumb: list[str] | None = None
) -> dict[str, tuple[str, list[str]]]:
    """Traverse tree from build_tree; return {rel_path_or_stem: (section_path, breadcrumb)}."""
    result: dict[str, tuple[str, list[str]]] = {}
    breadcrumb = breadcrumb or []
    for node in nodes or []:
        title = node.get("title", "")
        path = node.get("path", "")
        children = node.get("children", [])
        if path:
            stem = Path(path).stem
            result[path.replace("\\", "/")] = (base_path, list(breadcrumb))
            result[stem] = (base_path, list(breadcrumb))
        section_path = (base_path + "/" + title) if base_path and title else (title or base_path)
        child_breadcrumb = breadcrumb + ([title] if title else [])
        result.update(_build_path_to_section(children, section_path, child_breadcrumb))
    return result


def _bm25_enabled() -> bool:
    """BM25 enabled by default (env_config)."""
    return env_config.get_bm25_enabled()


def _is_qdrant_500(err: BaseException) -> bool:
    """True if exception looks like Qdrant 500 (transient or batch too large)."""
    msg = str(err).lower()
    name = type(err).__name__.lower()
    return "500" in msg or "internal server error" in msg or "unexpectedresponse" in name


def _upsert_batch_with_retry(client: Any, collection_name: str, points: list[Any]) -> None:
    """Upsert points with retry on 500; on repeated failure try half-batch."""
    try:
        client.upsert(collection_name=collection_name, points=points)
    except Exception as e:
        if not _is_qdrant_500(e):
            raise
        time.sleep(2.0)  # backoff before retry
        try:
            client.upsert(collection_name=collection_name, points=points)
        except Exception as e2:
            if not _is_qdrant_500(e2) or len(points) <= 1:
                raise
            mid = len(points) // 2
            _upsert_batch_with_retry(client, collection_name, points[:mid])
            _upsert_batch_with_retry(client, collection_name, points[mid:])


def build_index(
    docs_dir,
    qdrant_host="localhost",
    qdrant_port=6333,
    collection=COLLECTION_NAME,
    incremental=False,
    extra_payload: dict[str, Any] | None = None,
    batch_size: int = 500,
    embedding_batch_size: int | None = None,
    embedding_workers: int | None = None,
    source_dir: str | None = None,
    progress_callback=None,
    bm25: bool | None = None,
    path_prefix: str | None = None,
) -> int:
    """Index .md (and optionally .html) files from docs_dir into Qdrant in batches. Returns total points.
    progress_callback(pts_done, phase, total_estimated): optional; total_estimated = len(paths_to_index).
    extra_payload: merged into each point (e.g. {"version": "8.3", "language": "ru"}).
    incremental: if True, do not recreate collection; upsert by path (add new, update changed).
    source_dir: optional path to unpacked HTML with __categories__ for section_path/breadcrumb in payload.
    embedding_batch_size: texts per embedding batch (env EMBEDDING_BATCH_SIZE).
    embedding_workers: parallel API requests for openai_api (env EMBEDDING_WORKERS).
    bm25: add BM25 sparse vectors (default: BM25_ENABLED env, 1). Ignored when incremental.
    path_prefix: if set, prepend to path in payload (e.g. "8.3/1cv8_ru" for version/platform_lang)."""
    from ..help_core.categories import build_tree, find_categories_root, parse_content_file
    from ..help_core.html2md import (
        _ENCODINGS_UTF8_FIRST,
        _looks_like_html,
        _normalize_md_text,
        extract_links_from_markdown,
        extract_outgoing_links,
        html_to_md_content,
        read_file_with_encoding_fallback,
    )
    from . import embedding

    if QdrantClient is None:
        raise RuntimeError("qdrant-client is required. pip install qdrant-client")
    client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
    docs_dir = Path(docs_dir)
    extra = dict(extra_payload or {})
    version = extra.get("version", "")
    language = extra.get("language", "")
    max_input_chars = embedding.MAX_EMBEDDING_INPUT_CHARS

    def _read_one_item(p: Path) -> tuple[str, str, str, list[dict[str, Any]]] | None:
        """Read one file for indexing. Returns (rel_str, text, title, outgoing_links) or None to skip."""
        base_for_links = Path(source_dir) if source_dir else docs_dir
        try:
            outgoing_links: list[dict[str, Any]] = []
            if p.suffix == ".md":
                text = read_file_with_encoding_fallback(p, encodings=_ENCODINGS_UTF8_FIRST)
                if source_dir:
                    html_path = Path(source_dir) / p.relative_to(docs_dir).with_suffix(".html")
                    if html_path.exists():
                        outgoing_links = extract_outgoing_links(html_path, Path(source_dir))
                if not outgoing_links and text:
                    md_links = extract_links_from_markdown(text, p, docs_dir)
                    if md_links:
                        outgoing_links = md_links
            else:
                text = html_to_md_content(p) if p.suffix in (".html", "") or not p.suffix else ""
                if not text or not text.strip():
                    try:
                        text = read_file_with_encoding_fallback(p)[:50000]
                    except Exception:
                        return None
                if p.suffix in (".html", "") or not p.suffix:
                    outgoing_links = extract_outgoing_links(p, base_for_links)
            if not text or not text.strip():
                return None
            rel = p.relative_to(docs_dir)
            rel_str = str(rel).replace("\\", "/")
            title = text.split("\n")[0].strip().lstrip("#").strip() or (
                p.stem if p.suffix else p.name
            )
            return (rel_str, text, title, outgoing_links)
        except Exception:
            return None

    path_to_section: dict[str, tuple[str, list[str]]] = {}
    path_to_title: dict[str, str] = {}
    if source_dir:
        src = Path(source_dir)
        toc_path = src / ".toc.json"
        flat = load_toc_json(toc_path)
        if flat:
            try:
                path_to_section, path_to_title = path_to_section_and_title_from_toc(flat)
            except Exception as e:
                logging.getLogger(__name__).debug("load .toc.json failed: %s", e)
        if not path_to_section:
            root = find_categories_root(src)
            if root:
                try:
                    struct = parse_content_file(root / "__categories__")
                    tree = build_tree(root, struct)
                    path_to_section = _build_path_to_section(tree)
                except Exception as e:
                    logging.getLogger(__name__).debug("build path_to_section failed: %s", e)

    paths_to_index: list[Path] = []
    for path in docs_dir.rglob("*.md"):
        if path.is_file():
            paths_to_index.append(path)
    if not paths_to_index:
        html_paths = list(docs_dir.rglob("*.html"))
        for p in docs_dir.rglob("*"):
            if not p.is_file():
                continue
            if "." in p.name or p.name == ".gitkeep":
                continue
            if _looks_like_html(p) and p not in html_paths:
                html_paths.append(p)
        paths_to_index = html_paths

    if not paths_to_index:
        return 0

    total_estimated = len(paths_to_index)
    if embedding_batch_size is None:
        embedding_batch_size = embedding._embedding_batch_size()
    if embedding_workers is None:
        embedding_workers = embedding._embedding_workers()

    # BM25 requires full corpus (vocab/IDF); with incremental we add folder-by-folder, so skip here.
    # Use add-bm25 command after ingest to build BM25 on existing collection, or run ingest with --recreate once.
    use_bm25 = (bm25 if bm25 is not None else _bm25_enabled()) and not incremental
    vectors_bm25: list[dict[str, Any]] = []
    vocab_bm25: dict[str, int] = {}
    doc_freq_bm25: dict[str, int] = {}
    all_items: list[tuple[str, str, str, int, list[dict[str, Any]]]] = []

    if use_bm25 and SparseVector is not None and SparseVectorParams is not None:
        if sys.stderr:
            print(
                "[indexer] BM25 enabled: collecting all texts for sparse vectors...",
                file=sys.stderr,
                flush=True,
            )
        for path in paths_to_index:
            item = _read_one_item(path)
            if item is None:
                continue
            rel_str, text, title, outgoing_links = item
            all_items.append((rel_str, text, title, len(all_items), outgoing_links))
        if all_items:
            from .sparse_bm25 import bm25_vocab_path, build_bm25_vectors, save_vocab

            texts_bm25 = [it[1] for it in all_items]
            vectors_bm25, vocab_bm25, doc_freq_bm25 = build_bm25_vectors(texts_bm25)
            save_vocab(
                bm25_vocab_path(collection),
                vocab_bm25,
                doc_freq_bm25,
                len(texts_bm25),
            )
            if sys.stderr:
                print(
                    f"[indexer] BM25 vocab built for {len(all_items)} docs",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            use_bm25 = False

    collection_created = False
    total = 0
    batch_num = 0
    iter_size = len(all_items) if (use_bm25 and all_items) else len(paths_to_index)
    if progress_callback and callable(progress_callback):
        try:
            progress_callback(0, "indexing", total_estimated)
        except (TypeError, Exception):
            pass
    for batch_start in range(0, iter_size, batch_size):
        batch_num += 1
        batch_end = min(batch_start + batch_size, iter_size)
        print(
            f"[indexer] batch {batch_num}: files {batch_start + 1}-{batch_end} of {iter_size}",
            file=sys.stderr,
            flush=True,
        )
        items: list[tuple[str, str, str, int, list[dict[str, Any]]]] = []
        if use_bm25 and all_items:
            items = [
                (it[0], it[1], it[2], batch_start + i, it[4])
                for i, it in enumerate(all_items[batch_start:batch_end])
            ]
        else:
            batch_paths = paths_to_index[batch_start : batch_start + batch_size]
            for path in batch_paths:
                item = _read_one_item(path)
                if item is None:
                    continue
                rel_str, text, title, outgoing_links = item
                point_index = total + len(items)
                items.append((rel_str, text, title, point_index, outgoing_links))
        if not items:
            continue

        def _embed_progress(
            done_in_batch: int,
            total_in_batch: int,  # used by get_embedding_batch callback signature
            _total: int = total,
            _est: int = total_estimated,
        ) -> None:
            if progress_callback and callable(progress_callback):
                try:
                    progress_callback(_total + done_in_batch, "embedding", _est)
                except (TypeError, Exception):
                    pass

        texts_for_embedding = [it[1][:max_input_chars] for it in items]
        _t0 = time.monotonic()
        vectors = embedding.get_embedding_batch(
            texts_for_embedding,
            batch_size=embedding_batch_size,
            workers=embedding_workers,
            progress_callback=_embed_progress,
        )
        _batch_sec = round(time.monotonic() - _t0, 2)
        if progress_callback and callable(progress_callback):
            try:
                progress_callback(
                    total + len(items),
                    "embedding",
                    total_estimated,
                    batch_sec=_batch_sec,
                )
            except (TypeError, Exception):
                pass
        if len(vectors) != len(items):
            # Retry once with same batch (transient API/parsing issue); same batch is sent twice to API
            logging.getLogger(__name__).debug(
                "embedding batch count mismatch (%s != %s), retrying same batch (duplicate API send)",
                len(vectors),
                len(items),
            )
            vectors_retry = embedding.get_embedding_batch(
                texts_for_embedding,
                batch_size=embedding_batch_size,
                workers=embedding_workers,
            )
            if len(vectors_retry) != len(items):
                print(
                    f"[indexer] WARN: embedding count mismatch ({len(vectors_retry)} != {len(items)}), "
                    f"skipping batch of {len(items)} files",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            vectors = vectors_retry
        points = []
        batch_bm25_start = batch_start if use_bm25 else 0
        for idx_in_items, (rel_str, text, title, point_index, outgoing_links) in enumerate(items):
            vector = vectors[idx_in_items]
            # Normalize HTML entities (&nbsp;, &amp;, &#160; etc.) in stored text/title so payload is clean
            text_norm = _normalize_md_text(text)
            path_for_payload = f"{path_prefix}/{rel_str}" if path_prefix else rel_str
            point_id = (
                _path_to_point_id(path_for_payload, version=version, language=language)
                if incremental
                else point_index
            )
            stem = Path(rel_str).stem
            title_from_toc = None
            if path_to_title:
                for key in (rel_str, stem, rel_str.replace(".md", ".html")):
                    if key in path_to_title:
                        title_from_toc = path_to_title[key]
                        break
            title_effective = _normalize_md_text(title_from_toc if title_from_toc else title)
            payload = {
                "path": path_for_payload,
                "text": text_norm[:50000],
                "title": title_effective,
            }
            payload.update(extra)
            if outgoing_links:
                prefix = (path_prefix or "").strip().rstrip("/")
                links_with_prefix = []
                for lnk in outgoing_links:
                    rp = (lnk.get("resolved_path") or "").strip()
                    if prefix and rp and not rp.startswith(prefix + "/"):
                        links_with_prefix.append({**lnk, "resolved_path": f"{prefix}/{rp}"})
                    else:
                        links_with_prefix.append(dict(lnk))
                payload["outgoing_links"] = links_with_prefix
            first_para = text_norm.split("\n\n")[0] if text_norm else ""
            kw = list(
                dict.fromkeys(
                    _extract_keywords(title_effective) + _extract_keywords(first_para[:800])
                )
            )[:50]
            if kw:
                payload["keywords"] = kw
            if path_to_section:
                for key in (rel_str, stem, rel_str.replace(".md", ".html")):
                    if key in path_to_section:
                        section_path, breadcrumb = path_to_section[key]
                        payload["section_path"] = _normalize_md_text(section_path)
                        payload["breadcrumb"] = [_normalize_md_text(b) for b in (breadcrumb or [])]
                        break
            entity_type = _infer_entity_type(
                payload.get("section_path", ""), payload.get("breadcrumb", [])
            )
            payload["entity_type"] = entity_type
            vec_for_point: Any = vector
            if use_bm25 and vectors_bm25:
                bm25_idx = batch_bm25_start + idx_in_items
                if bm25_idx < len(vectors_bm25):
                    sv = SparseVector(
                        indices=vectors_bm25[bm25_idx].get("indices", []),
                        values=vectors_bm25[bm25_idx].get("values", []),
                    )
                    vec_for_point = {"": vector, SPARSE_VECTOR_NAME: sv}
            points.append(PointStruct(id=point_id, vector=vec_for_point, payload=payload))
        if not collection_created:
            dim = embedding.get_embedding_dimension()
            sparse_config = (
                {SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)}
                if (use_bm25 and SparseVectorParams is not None and Modifier is not None)
                else None
            )
            if incremental:
                if not client.collection_exists(collection):
                    client.create_collection(
                        collection_name=collection,
                        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                        sparse_vectors_config=sparse_config,
                    )
            else:
                client.recreate_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                    sparse_vectors_config=sparse_config,
                )
            collection_created = True
        _upsert_batch_with_retry(client, collection, points)
        total += len(points)
        if progress_callback and callable(progress_callback):
            try:
                progress_callback(total, "writing", total_estimated)
            except TypeError:
                try:
                    progress_callback(total, "writing")
                except Exception as e:
                    logging.getLogger(__name__).debug("progress_callback failed: %s", e)
            except Exception as e:
                logging.getLogger(__name__).debug("progress_callback failed: %s", e)
    return total


def _index_status_sample_size() -> int:
    """Sample size for version/language sampling in get_index_status. From env_config."""
    return env_config.get_index_status_sample_size()


def get_index_status(
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Return index status: exists, points_count, and optional version/language breakdown from payload."""
    if sample_size is None:
        sample_size = _index_status_sample_size()
    if QdrantClient is None:
        return {"error": "qdrant-client not available", "exists": False, "points_count": 0}
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    try:
        client = _get_default_qdrant_client(host, port)
    except Exception as e:
        return {"error": safe_error_message(e), "exists": False, "points_count": 0}
    if not client.collection_exists(collection):
        return {"exists": False, "points_count": 0, "collection": collection}
    try:
        info = client.get_collection(collection)
        points_count = _collection_info_int(info, "points_count", "pointsCount")
    except Exception as e:
        return {
            "exists": True,
            "points_count": None,
            "error": safe_error_message(e),
            "collection": collection,
        }
    out: dict[str, Any] = {
        "exists": True,
        "points_count": points_count,
        "collection": collection,
    }
    try:
        res, _ = client.scroll(
            collection_name=collection,
            limit=min(sample_size, points_count or 0),
            with_payload=True,
            with_vectors=False,
        )
        versions: set = set()
        languages: set = set()
        for point in res or []:
            p = getattr(point, "payload", None) or {}
            if p.get("version"):
                versions.add(p["version"])
            if p.get("language"):
                languages.add(p["language"])
        if versions:
            out["versions"] = sorted(versions)
        if languages:
            out["languages"] = sorted(languages)
    except Exception as e:
        logging.getLogger(__name__).debug("get_index_status payload scan failed: %s", e)
    return out


def _collection_info_int(info: Any, *keys: str) -> int:
    """Get first available int from collection info (Pydantic/dict), for points_count, indexed_vectors_count, segments_count."""
    for key in keys:
        v = getattr(info, key, None)
        if v is None and isinstance(info, dict):
            v = info.get(key)
        if v is not None and isinstance(v, int):
            return v
    return 0


def _collection_status_str(info: Any) -> str | None:
    """Get collection status (green/yellow/grey/red) for dashboard."""
    v = getattr(info, "status", None)
    if v is None and isinstance(info, dict):
        v = info.get("status")
    if v is not None and isinstance(v, str):
        return v
    return None


def get_all_collections_status(
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Return status for all Qdrant collections: name, points_count, indexed_vectors_count, segments_count.
    Always reads current state from Qdrant API (no cache)."""
    if QdrantClient is None:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    try:
        client = _get_default_qdrant_client(host, port)
    except Exception as e:
        logging.getLogger(__name__).debug("get_all_collections QdrantClient failed: %s", e)
        return []
    result: list[dict[str, Any]] = []
    try:
        resp = client.get_collections()
        raw_list = getattr(resp, "collections", None) or []
        for c in raw_list:
            name = getattr(c, "name", None)
            if name is None and isinstance(c, dict):
                name = c.get("name")
            if not name:
                name = str(c) if c else ""
            if not name:
                continue
            try:
                info = client.get_collection(name)
                pts = _collection_info_int(info, "points_count", "pointsCount")
                vecs = (
                    _collection_info_int(info, "indexed_vectors_count", "indexedVectorsCount")
                    or pts
                )
                segs = _collection_info_int(info, "segments_count", "segmentsCount")
                has_bm25 = _collection_has_sparse(client, name)
                status_str = _collection_status_str(info)
                result.append(
                    {
                        "name": name,
                        "points_count": pts,
                        "indexed_vectors_count": vecs,
                        "segments_count": segs,
                        "bm25": has_bm25,
                        "status": status_str,
                    }
                )
            except Exception:
                result.append(
                    {
                        "name": name,
                        "points_count": None,
                        "indexed_vectors_count": None,
                        "segments_count": None,
                        "bm25": False,
                        "status": None,
                    }
                )
    except Exception as e:
        logging.getLogger(__name__).debug("get_all_collections iterate failed: %s", e)
    return result


SPARSE_VECTOR_NAME = "text-bm25"


_CAMEL_SPLIT_RE = re.compile(r"[А-ЯЁ][а-яё]+|[A-Z][a-z]+")


def _expand_camel_names(*names: str) -> str:
    """Extract individual CamelCase parts from compound API identifiers.
    E.g. 'ВызватьИсключение' → 'Вызвать Исключение', enabling BM25 to match on parts."""
    parts: list[str] = []
    for name in names:
        for segment in re.split(r"[.\s]+", name or ""):
            words = _CAMEL_SPLIT_RE.findall(segment)
            if len(words) > 1:  # only add if actually split (compound word)
                parts.extend(words)
    return " ".join(parts)


def _bm25_text_from_payload(collection: str, payload: dict[str, Any]) -> str:
    """Extract text for BM25 from point payload. onec_help: title+text; onec_help_memory: title, summary, ...; onec_config_metadata: text (config_name, object_type, name, full_name)."""
    if collection == "onec_help_memory":
        parts = [
            payload.get("title") or "",
            payload.get("summary") or "",
            payload.get("description") or "",
            payload.get("code_snippet") or "",
            payload.get("instruction") or "",
        ]
        return "\n".join(p for p in parts if p)
    if collection == "onec_config_metadata":
        text = (payload.get("text") or "").strip()
        if text:
            return text
        return " ".join(
            filter(
                None, [payload.get("config_name"), payload.get("name"), payload.get("full_name")]
            )
        )
    if collection in (
        "onec_help_api",
        "onec_help_api_members",
        "onec_help_api_objects",
        "onec_help_examples",
    ):
        fn = payload.get("full_name") or payload.get("name") or ""
        title = payload.get("title") or ""
        summary = payload.get("summary") or ""
        text = (payload.get("text") or "").strip()
        base = "\n".join(p for p in (title, text) if p)
        # Expand CamelCase compound names so individual parts are BM25-searchable.
        # e.g. "ВызватьИсключение" → adds "Вызвать Исключение" as separate tokens.
        camel_expanded = _expand_camel_names(fn, title, summary)
        return (base + ("\n" + camel_expanded if camel_expanded else "")).strip()
    # onec_help and any other: title + text
    return ((payload.get("title") or "") + "\n" + (payload.get("text") or "")).strip() or ""


def _collection_has_sparse(
    client: Any,
    collection: str,
) -> bool:
    """Return True if collection has sparse vector 'text-bm25'."""
    try:
        info = client.get_collection(collection)
        params = getattr(info, "config", None) and getattr(
            getattr(info, "config", None), "params", None
        )
        if not params:
            return False
        sparse = getattr(params, "sparse_vectors", None) or {}
        if isinstance(sparse, dict):
            return SPARSE_VECTOR_NAME in sparse
        return False
    except Exception:
        return False


def add_bm25_to_collection(
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    batch_size: int = 200,
    verbose: bool = True,
    force_rebuild: bool = False,
) -> int:
    """Add BM25 sparse vectors to existing collection. No re-ingest, no re-embedding.

    Uses a temporary collection to avoid data loss on timeout/crash: writes to
    {collection}_bm25_tmp first, then swaps. Original collection is only dropped
    after the temp is fully written. On re-run, if tmp exists with marker, finishes
    the swap (recovery). Returns total points migrated.

    force_rebuild: if True, remove existing BM25 first and fully rebuild sparse vectors.
    Without this flag, collections that already have BM25 only get vocab refreshed on disk.
    """
    from . import embedding
    from .sparse_bm25 import bm25_build_stats, bm25_doc_vector, bm25_vocab_path, save_vocab

    if QdrantClient is None or SparseVector is None or SparseVectorParams is None:
        raise RuntimeError("qdrant-client required for add-bm25")
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    timeout = env_config.get_qdrant_timeout()
    client = QdrantClient(host=host, port=port, timeout=timeout, check_compatibility=False)
    if not client.collection_exists(collection):
        raise RuntimeError(f"Collection {collection} does not exist. Run ingest first.")

    if _collection_has_sparse(client, collection) and force_rebuild:
        if verbose:
            print(
                f"[add-bm25] {collection}: force_rebuild — removing existing BM25 first",
                file=sys.stderr,
            )
        _remove_bm25_from_collection(client, collection, batch_size, verbose)

    if _collection_has_sparse(client, collection):
        # Collection already has BM25; only save vocab to host
        # Streaming stats pass — no text/token lists kept in memory.
        def _scroll_texts() -> "Generator[str, None, None]":
            _off = None
            while True:
                _res, _next = client.scroll(
                    collection_name=collection,
                    limit=batch_size,
                    offset=_off,
                    with_payload=True,
                    with_vectors=False,
                )
                for _p in _res or []:
                    yield _bm25_text_from_payload(collection, getattr(_p, "payload", None) or {})
                if _next is None:
                    break
                _off = _next

        vocab, doc_freq, _, _, N_pts = bm25_build_stats(_scroll_texts())
        if N_pts:
            vocab_path = bm25_vocab_path(collection)
            save_vocab(vocab_path, vocab, doc_freq, N_pts)
            if verbose:
                print(
                    f"[add-bm25] Collection already has BM25. Vocab saved to {vocab_path}",
                    file=sys.stderr,
                )
        return getattr(client.get_collection(collection), "points_count", 0) or 0

    tmp_collection = f"{collection}_bm25_tmp"
    vocab_dir = bm25_vocab_path(collection).parent
    marker_path = vocab_dir / f".tmp_{collection}.complete"

    # Recovery: previous run wrote to tmp then crashed during swap. Copy tmp -> collection.
    if client.collection_exists(tmp_collection):
        if marker_path.exists():
            if verbose:
                print(f"[add-bm25] Recovering from {tmp_collection}...", file=sys.stderr)
            try:
                _recover_add_bm25_swap(client, collection, tmp_collection, batch_size, verbose)
            finally:
                try:
                    marker_path.unlink()
                except OSError:
                    pass
                try:
                    if client.collection_exists(tmp_collection):
                        client.delete_collection(tmp_collection)
                except Exception:
                    pass
            return getattr(client.get_collection(collection), "points_count", 0) or 0
        try:
            client.delete_collection(tmp_collection)
        except Exception:
            pass

    # Phase 1: scroll WITHOUT vectors to collect texts/payloads/ids for BM25 computation.
    # This avoids loading all dense vectors (768-dim × N floats) into memory at once.
    # Phase 1: streaming stats — build vocab/df/doc_lens without storing any text/token lists.
    # Only meta_ids (ints) and doc_lens (ints) are kept; everything else is aggregate.
    meta_ids: list[Any] = []
    meta_dl: list[int] = []
    offset = None
    while True:
        res, next_offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in res or []:
            meta_ids.append(getattr(p, "id", 0))
            meta_dl.append(0)  # placeholder; filled by bm25_build_stats below
        if next_offset is None:
            break
        offset = next_offset

    if not meta_ids:
        if verbose:
            print("[add-bm25] No points to migrate.", file=sys.stderr)
        return 0

    N = len(meta_ids)
    if verbose:
        print(
            f"[add-bm25] Migrating {N} points (safe: tmp first)...",
            file=sys.stderr,
            flush=True,
        )

    # Re-scroll payloads (no vectors) for stats; build vocab/df/avgdl in one pass.
    def _texts_for_stats() -> "Generator[str, None, None]":
        _off = None
        while True:
            _res, _next = client.scroll(
                collection_name=collection,
                limit=batch_size,
                offset=_off,
                with_payload=True,
                with_vectors=False,
            )
            for _p in _res or []:
                yield _bm25_text_from_payload(collection, getattr(_p, "payload", None) or {})
            if _next is None:
                break
            _off = _next

    vocab, doc_freq, doc_lens, avgdl, _ = bm25_build_stats(_texts_for_stats())
    vocab_path = bm25_vocab_path(collection)
    save_vocab(vocab_path, vocab, doc_freq, N)

    # id → doc-length map so Phase 2 can compute BM25 without re-tokenising twice.
    # Both lists are O(N ints), small compared to token lists.
    id_to_dl: dict[Any, int] = {pid: dl for pid, dl in zip(meta_ids, doc_lens, strict=True)}
    del meta_ids, doc_lens  # free before dense-vector pass

    # Determine dense vector dimension from a single point sample.
    dim = embedding.get_embedding_dimension()
    sample_res, _ = client.scroll(
        collection_name=collection, limit=1, with_payload=False, with_vectors=True
    )
    if sample_res:
        sv_sample = getattr(sample_res[0], "vector", None)
        if isinstance(sv_sample, dict):
            sv_sample = sv_sample.get("") or sv_sample.get(None)
        if isinstance(sv_sample, list) and sv_sample:
            dim = len(sv_sample)

    sparse_config = {SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)}
    optimizers = (
        OptimizersConfigDiff(indexing_threshold=1) if OptimizersConfigDiff is not None else None
    )

    # Phase 2: scroll WITH dense vectors in batches; compute BM25 vector on-the-fly
    # and upsert immediately — never hold all sparse vectors in memory at once.
    client.create_collection(
        collection_name=tmp_collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        sparse_vectors_config=sparse_config,
        optimizers_config=optimizers,
    )
    upserted = 0
    offset = None
    while True:
        res, next_offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not res:
            if next_offset is None:
                break
            offset = next_offset
            continue
        batch_points = []
        for p in res:
            pid = getattr(p, "id", 0)
            pl = getattr(p, "payload", None) or {}
            vec = getattr(p, "vector", None)
            if isinstance(vec, dict):
                vec = vec.get("") or vec.get(None)
            dense = vec if isinstance(vec, list) else []
            text = _bm25_text_from_payload(collection, pl)
            dl = id_to_dl.get(pid, 0)
            sparse_vec = bm25_doc_vector(text, dl, vocab, avgdl)
            sv = SparseVector(
                indices=sparse_vec["indices"],
                values=sparse_vec["values"],
            )
            vec_dict: dict[str, Any] = {"": dense, SPARSE_VECTOR_NAME: sv}
            batch_points.append(PointStruct(id=pid, vector=vec_dict, payload=pl))
        client.upsert(collection_name=tmp_collection, points=batch_points)
        upserted += len(batch_points)
        if verbose and upserted % 1000 < batch_size:
            print(
                f"[add-bm25] Upserted {upserted}/{N} to tmp",
                file=sys.stderr,
                flush=True,
            )
        if next_offset is None:
            break
        offset = next_offset

    vocab_dir.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("", encoding="utf-8")

    # Swap: drop original, recreate, copy from tmp (if we crash here, re-run recovers from tmp)
    client.delete_collection(collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        sparse_vectors_config=sparse_config,
        optimizers_config=optimizers,
    )
    offset = None
    while True:
        res, next_offset = client.scroll(
            collection_name=tmp_collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if res:
            batch_points = []
            for p in res:
                vec = getattr(p, "vector", None)
                payload = getattr(p, "payload", None) or {}
                pid = getattr(p, "id", 0)
                batch_points.append(PointStruct(id=pid, vector=vec, payload=payload))
            client.upsert(collection_name=collection, points=batch_points)
        if next_offset is None:
            break
        offset = next_offset

    client.delete_collection(tmp_collection)
    try:
        marker_path.unlink()
    except OSError:
        pass

    if verbose:
        print(f"[add-bm25] Done. BM25 vocab saved to {vocab_path}", file=sys.stderr)
    return N


def _recover_add_bm25_swap(
    client: Any,
    collection: str,
    tmp_collection: str,
    batch_size: int,
    verbose: bool,
) -> None:
    """Copy tmp_collection (dense+sparse) into collection. Call after crash during swap."""
    res, _ = client.scroll(
        collection_name=tmp_collection,
        limit=1,
        with_payload=False,
        with_vectors=True,
    )
    dim = 768
    if res:
        vec = getattr(res[0], "vector", None)
        if isinstance(vec, dict):
            dense = vec.get("") or vec.get(None)
        else:
            dense = vec
        if isinstance(dense, list) and len(dense) > 0:
            dim = len(dense)
    sparse_config = {SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)}
    optimizers = (
        OptimizersConfigDiff(indexing_threshold=1) if OptimizersConfigDiff is not None else None
    )
    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        sparse_vectors_config=sparse_config,
        optimizers_config=optimizers,
    )
    offset = None
    while True:
        res, next_offset = client.scroll(
            collection_name=tmp_collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if res:
            batch_points = []
            for p in res:
                vec = getattr(p, "vector", None)
                payload = getattr(p, "payload", None) or {}
                pid = getattr(p, "id", 0)
                batch_points.append(PointStruct(id=pid, vector=vec, payload=payload))
            client.upsert(collection_name=collection, points=batch_points)
        if next_offset is None:
            break
        offset = next_offset


def _remove_bm25_from_collection(
    client: Any,
    collection: str,
    batch_size: int,
    verbose: bool,
) -> None:
    """Remove sparse (BM25) from collection: scroll all, recreate dense-only, upsert."""
    from . import embedding

    points = []
    offset = None
    while True:
        res, next_offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(res or [])
        if next_offset is None:
            break
        offset = next_offset
    if not points:
        return
    dim = embedding.get_embedding_dimension()
    for p in points:
        vec = getattr(p, "vector", None)
        if isinstance(vec, dict):
            vec = vec.get("") or vec.get(None)
        if isinstance(vec, list) and len(vec) > 0:
            dim = len(vec)
            break
    if client.collection_exists(collection):
        client.delete_collection(collection_name=collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        batch_struct = []
        for p in batch:
            vec = getattr(p, "vector", None)
            if isinstance(vec, dict):
                vec = vec.get("") or vec.get(None)
            dense = vec if isinstance(vec, list) else []
            batch_struct.append(
                PointStruct(
                    id=getattr(p, "id", 0),
                    vector=dense,
                    payload=getattr(p, "payload", None) or {},
                )
            )
        client.upsert(collection_name=collection, points=batch_struct)
    if verbose:
        print(f"[add-bm25] {collection}: removed BM25 ({len(points)} points)", file=sys.stderr)


def add_bm25_to_all_collections(
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    batch_size: int = 200,
    verbose: bool = True,
) -> dict[str, int]:
    """Add BM25 to all collections. Before run: deletes bm25_vocab and removes existing BM25
    from collections, then adds BM25 to every collection."""
    if QdrantClient is None:
        raise RuntimeError("qdrant-client required for add-bm25")
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    timeout = env_config.get_qdrant_timeout()
    client = QdrantClient(host=host, port=port, timeout=timeout, check_compatibility=False)

    # Delete bm25_vocab files and BM25 indexes (recreate dense-only) before adding
    base = Path(env_config.get_data_dir())
    if not base.is_absolute():
        base = Path.cwd() / base
    vocab_dir = base.resolve() / "bm25_vocab"
    if vocab_dir.is_dir():
        for f in vocab_dir.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass
        if verbose:
            print("[add-bm25] Cleared bm25_vocab", file=sys.stderr)

    resp = client.get_collections()
    raw_list = getattr(resp, "collections", None) or []
    names = []
    for c in raw_list:
        name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None) or ""
        if name:
            names.append(name)

    for name in names:
        if _collection_has_sparse(client, name):
            try:
                _remove_bm25_from_collection(client, name, batch_size, verbose)
            except Exception as e:
                if verbose:
                    print(f"[add-bm25] {name}: failed to remove BM25 — {e}", file=sys.stderr)

    result: dict[str, int] = {}
    for name in names:
        try:
            n = add_bm25_to_collection(
                qdrant_host=host,
                qdrant_port=port,
                collection=name,
                batch_size=batch_size,
                verbose=verbose,
            )
            result[name] = n
        except Exception as e:
            if verbose:
                print(f"[add-bm25] {name}: failed — {e}", file=sys.stderr)
    return result


def search_index(
    query,
    qdrant_host=None,
    qdrant_port=None,
    collection=COLLECTION_NAME,
    limit=10,
    version: str | None = None,
    language: str | None = None,
    entity_type: str | None = None,
    full_payload: bool = False,
):
    """Search Qdrant; return list of payloads with path, title, text snippet.
    version, language, entity_type: optional payload filters.
    full_payload=True: return full Qdrant payload (needed for structured API collections)."""
    from . import embedding

    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    if QdrantClient is None:
        return []
    client = _get_default_qdrant_client(host, port)
    coll_dim = get_collection_vector_size(collection=collection, qdrant_host=host, qdrant_port=port)
    vector = embedding.get_embedding(
        query, target_dimension=coll_dim if coll_dim is not None else None
    )

    must = []
    if version and Filter and FieldCondition and MatchValue:
        must.append(FieldCondition(key="version", match=MatchValue(value=version)))
    if language and Filter and FieldCondition and MatchValue:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))
    if entity_type and Filter and FieldCondition and MatchValue:
        must.append(FieldCondition(key="entity_type", match=MatchValue(value=entity_type)))
    qfilter = Filter(must=must) if must and Filter else None

    kwargs: dict[str, Any] = {"collection_name": collection, "limit": limit}
    if hasattr(client, "query_points"):
        kwargs["query"] = vector
        if qfilter is not None:
            kwargs["query_filter"] = qfilter
        response = client.query_points(**kwargs)
        hits = getattr(response, "points", [])
    else:
        kwargs["query_vector"] = vector
        if qfilter is not None:
            kwargs["query_filter"] = qfilter
        hits = client.search(**kwargs)
    _SNIPPET_LEN = 550
    raw = []
    for h in hits:
        payload = getattr(h, "payload", None) or {}
        if full_payload:
            rec = dict(payload)
            rec["score"] = getattr(h, "score", None)
        else:
            text = (payload.get("text") or "")[:_SNIPPET_LEN]
            links = payload.get("outgoing_links") or []
            if links:
                titles = [lnk.get("target_title") or lnk.get("link_text", "") for lnk in links[:5]]
                text = (text + "\nСвязанные: " + ", ".join(t for t in titles if t)).strip()
            rec = {
                "path": payload.get("path", ""),
                "title": payload.get("title", ""),
                "text": text,
                "score": getattr(h, "score", None),
                "version": payload.get("version", ""),
                "entity_type": payload.get("entity_type", ""),
                "breadcrumb": payload.get("breadcrumb") or [],
            }
        raw.append(rec)
    if not full_payload and not version and not language:
        # Deduplicate by path, preferring newest version then highest score.
        # Skipped for full_payload mode (structured API collections) — dedup is done in search_hybrid.
        by_path: dict[str, dict[str, Any]] = {}
        for r in raw:
            p = r.get("path", "")
            if not p:
                continue
            vkey = _version_sort_key(r.get("version", ""))
            score = r.get("score") or 0.0
            if p not in by_path:
                by_path[p] = r
            else:
                prev = by_path[p]
                prev_key = _version_sort_key(prev.get("version", ""))
                prev_score = prev.get("score") or 0.0
                if vkey > prev_key or (vkey == prev_key and score > prev_score):
                    by_path[p] = r
        deduped = list(by_path.values())
        deduped.sort(
            key=lambda x: (-(x.get("score") or 0.0), -len(_version_sort_key(x.get("version", ""))))
        )
        return deduped
    return raw


_RRF_K = 60


def _rrf_doc_key(r: dict[str, Any]) -> str:
    """Unique key for RRF dedup: full_name+version for structured API records, else path."""
    fn = r.get("full_name") or r.get("name") or ""
    if fn:
        return fn + "|" + str(r.get("version") or "")
    return (r.get("path") or "") + "|" + str(r.get("version") or "")


def search_hybrid(
    query: str,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    entity_type: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    full_payload: bool = False,
) -> list[dict[str, Any]]:
    """Semantic + keyword search merged with RRF (Reciprocal Rank Fusion).
    Used by MCP and can be reused elsewhere.
    full_payload=True: return full Qdrant payload (needed for structured API collections)."""
    semantic_list = search_index(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=collection,
        limit=limit * 2,
        version=version,
        language=language,
        entity_type=entity_type,
        full_payload=full_payload,
    )
    keyword_list = search_index_keyword(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=collection,
        limit=15,
        version=version,
        language=language,
        entity_type=entity_type,
        full_payload=full_payload,
    )
    rrf_scores: dict[str, float] = {}
    key_to_doc: dict[str, dict[str, Any]] = {}
    for rank, r in enumerate(semantic_list, 1):
        k = _rrf_doc_key(r)
        if k and k != "|":
            rrf_scores[k] = rrf_scores.get(k, 0) + 1 / (_RRF_K + rank)
            key_to_doc[k] = r
    for rank, r in enumerate(keyword_list, 1):
        k = _rrf_doc_key(r)
        if k and k != "|":
            rrf_scores[k] = rrf_scores.get(k, 0) + 1 / (_RRF_K + rank)
            key_to_doc[k] = r
    return sorted(
        key_to_doc.values(),
        key=lambda x: -rrf_scores.get(_rrf_doc_key(x), 0),
    )[:limit]


def get_topic_from_index(
    topic_path: str,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    version: str | None = None,
    language: str | None = None,
) -> str:
    """Return full topic text from Qdrant payload by path (when file is not on disk)."""
    if QdrantClient is None or Filter is None or FieldCondition is None or MatchValue is None:
        return ""
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    topic_path = topic_path.lstrip("/")
    path_variants = [topic_path]
    if not topic_path.endswith(".md") and not topic_path.endswith(".html"):
        path_variants.append(topic_path + ".md")
        path_variants.append(topic_path + ".html")
    client = _get_default_qdrant_client(host, port)
    for pv in path_variants:
        try:
            must_cond = [FieldCondition(key="path", match=MatchValue(value=pv))]
            if version:
                must_cond.append(FieldCondition(key="version", match=MatchValue(value=version)))
            if language:
                must_cond.append(FieldCondition(key="language", match=MatchValue(value=language)))
            res, _ = client.scroll(
                collection_name=collection,
                scroll_filter=Filter(must=must_cond),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if res and len(res) > 0:
                payload = getattr(res[0], "payload", None) or {}
                text = payload.get("text") or ""
                if text:
                    return _apply_outgoing_links(text, payload)
        except Exception:
            continue
    # Fallback: scroll and match path by suffix (handles version/language prefixes)
    try:
        res, _ = client.scroll(
            collection_name=collection,
            limit=200,
            with_payload=True,
            with_vectors=False,
        )
        topic_path_norm = topic_path.replace("\\", "/")
        for point in res or []:
            payload = getattr(point, "payload", None) or {}
            p = (payload.get("path") or "").replace("\\", "/")
            if (
                p == topic_path_norm
                or p.endswith("/" + topic_path_norm)
                or p.endswith(topic_path_norm)
            ):
                text = payload.get("text") or ""
                if text:
                    return _apply_outgoing_links(text, payload)
    except Exception:
        pass
    return ""


def search_index_keyword(
    query: str,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    limit: int = 15,
    batch_size: int = 500,
    version: str | None = None,
    language: str | None = None,
    entity_type: str | None = None,
    full_payload: bool = False,
) -> list[dict[str, Any]]:
    """Search by keyword. Uses BM25 sparse if available, else payload.keywords/substring.
    full_payload=True: return full Qdrant payload (needed for structured API collections)."""
    if QdrantClient is None:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = _get_default_qdrant_client(host, port)
    q_lower = query.strip().lower()
    if not q_lower:
        return []

    # BM25 path: when collection has sparse vectors and vocab exists
    if SparseVector is not None and _collection_has_sparse(client, collection):
        try:
            from .sparse_bm25 import bm25_vocab_path, load_vocab, query_vector

            vocab_path = bm25_vocab_path(collection)
            if vocab_path.exists():
                vocab, doc_freq, N = load_vocab(vocab_path)
                qv = query_vector(query, vocab, doc_freq, N)
                if qv.get("indices"):
                    sv = SparseVector(indices=qv["indices"], values=qv["values"])
                    must = []
                    if version and Filter and FieldCondition and MatchValue:
                        must.append(FieldCondition(key="version", match=MatchValue(value=version)))
                    if language and Filter and FieldCondition and MatchValue:
                        must.append(
                            FieldCondition(key="language", match=MatchValue(value=language))
                        )
                    if entity_type and Filter and FieldCondition and MatchValue:
                        must.append(
                            FieldCondition(key="entity_type", match=MatchValue(value=entity_type))
                        )
                    qfilter = Filter(must=must) if must and Filter else None
                    kwargs: dict[str, Any] = {
                        "collection_name": collection,
                        "limit": limit * 2,
                        "with_payload": True,
                        "query_filter": qfilter,
                    }
                    if hasattr(client, "query_points"):
                        kwargs["query"] = sv
                        kwargs["using"] = SPARSE_VECTOR_NAME
                        resp = client.query_points(**kwargs)
                    else:
                        kwargs["query_vector"] = sv
                        kwargs["using"] = SPARSE_VECTOR_NAME
                        resp = client.search(**kwargs)
                    hits = getattr(resp, "points", resp) if hasattr(resp, "points") else resp
                    raw = []
                    for h in hits:
                        payload = getattr(h, "payload", None) or {}
                        if full_payload:
                            rec = dict(payload)
                            rec["score"] = getattr(h, "score", None)
                        else:
                            snippet = (payload.get("text") or "")[:SNIPPET_MAX_CHARS]
                            links = payload.get("outgoing_links") or []
                            if links:
                                titles = [
                                    lnk.get("target_title") or lnk.get("link_text", "")
                                    for lnk in links[:5]
                                ]
                                snippet = (
                                    snippet + "\nСвязанные: " + ", ".join(t for t in titles if t)
                                ).strip()
                            rec = {
                                "path": payload.get("path", ""),
                                "title": payload.get("title", ""),
                                "name": payload.get("name", ""),
                                "kind": payload.get("kind", ""),
                                "text": snippet,
                                "score": getattr(h, "score", None),
                                "version": payload.get("version", ""),
                                "entity_type": payload.get("entity_type", ""),
                                "breadcrumb": payload.get("breadcrumb") or [],
                            }
                        raw.append(rec)
                    if raw:
                        by_path: dict[str, dict[str, Any]] = {}
                        for r in raw:
                            p = r.get("path", "")
                            if not p:
                                continue
                            sc = r.get("score") or 0.0
                            vkey = _version_sort_key(r.get("version", ""))
                            if p not in by_path:
                                by_path[p] = r
                            else:
                                prev = by_path[p]
                                prev_sc = prev.get("score") or 0.0
                                prev_key = _version_sort_key(prev.get("version", ""))
                                if sc > prev_sc or (sc == prev_sc and vkey > prev_key):
                                    by_path[p] = r
                        out = sorted(
                            by_path.values(),
                            key=lambda x: (
                                -(x.get("score") or 0.0),
                                -len(_version_sort_key(x.get("version", ""))),
                            ),
                        )[:limit]
                        # Boost: exact query in title → move to top (critical for API names)
                        if q_lower and out:
                            with_title = [
                                r for r in out if q_lower in (r.get("title") or "").lower()
                            ]
                            without = [r for r in out if r not in with_title]
                            out = with_title + without
                        return out
        except Exception as e:
            logging.getLogger(__name__).debug("search_index_keyword BM25 path failed: %s", e)

    # Fallback: payload.keywords or substring scroll
    use_type_method_mode = "." in query

    must: list[Any] = []
    if version and Filter and FieldCondition and MatchValue:
        must.append(FieldCondition(key="version", match=MatchValue(value=version)))
    if language and Filter and FieldCondition and MatchValue:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))
    if entity_type and Filter and FieldCondition and MatchValue:
        must.append(FieldCondition(key="entity_type", match=MatchValue(value=entity_type)))

    query_keywords = _extract_keywords(query, max_tokens=20)
    use_keyword_filter = (
        not use_type_method_mode and bool(query_keywords) and Filter and FieldCondition and MatchAny
    )
    if use_keyword_filter:
        must.append(FieldCondition(key="keywords", match=MatchAny(any=query_keywords)))
    scroll_filter = Filter(must=must) if must and Filter else None

    out_dict: dict[str, dict[str, Any]] = {}  # path -> best record (prefer newer version)
    offset = None
    scroll_kwargs: dict[str, Any] = {
        "collection_name": collection,
        "limit": batch_size,
        "with_payload": True,
        "with_vectors": False,
    }
    if scroll_filter is not None:
        scroll_kwargs["scroll_filter"] = scroll_filter

    def _matches(payload: dict[str, Any]) -> bool:
        title = (payload.get("title") or "").lower()
        text = (payload.get("text") or "").lower()
        return q_lower in title or q_lower in text

    def _collect(res: list) -> None:
        nonlocal out_dict
        for point in res:
            payload = getattr(point, "payload", None) or {}
            path = payload.get("path", "")
            if not path:
                continue
            if not use_keyword_filter and not _matches(payload):
                continue
            vkey = _version_sort_key(payload.get("version", ""))
            if full_payload:
                rec = dict(payload)
                rec["score"] = None
            else:
                snippet = (payload.get("text") or "")[:SNIPPET_MAX_CHARS]
                links = payload.get("outgoing_links") or []
                if links:
                    titles = [
                        lnk.get("target_title") or lnk.get("link_text", "") for lnk in links[:5]
                    ]
                    snippet = (
                        snippet + "\nСвязанные: " + ", ".join(t for t in titles if t)
                    ).strip()
                rec = {
                    "path": path,
                    "title": payload.get("title", ""),
                    "name": payload.get("name", ""),
                    "kind": payload.get("kind", ""),
                    "text": snippet,
                    "score": None,
                    "version": payload.get("version", ""),
                    "entity_type": payload.get("entity_type", ""),
                    "breadcrumb": payload.get("breadcrumb") or [],
                }
            if path not in out_dict:
                out_dict[path] = rec
            elif vkey > _version_sort_key(out_dict[path].get("version", "")):
                out_dict[path] = rec
            if len(out_dict) >= limit:
                break

    while len(out_dict) < limit:
        try:
            kwargs = dict(scroll_kwargs)
            if offset is not None:
                kwargs["offset"] = offset
            res, next_offset = client.scroll(**kwargs)
        except Exception:
            break
        if not res:
            break
        _collect(res)
        if next_offset is None:
            break
        offset = next_offset

    # Fallback: if keyword filter returned nothing, retry with substring search
    if not out_dict and use_keyword_filter:
        use_keyword_filter = False
        must.pop()  # remove keywords condition
        scroll_filter = Filter(must=must) if must and Filter else None
        scroll_kwargs["scroll_filter"] = scroll_filter
        if scroll_kwargs.get("scroll_filter") is None:
            scroll_kwargs.pop("scroll_filter", None)
        offset = None
        while len(out_dict) < limit:
            try:
                kwargs = dict(scroll_kwargs)
                if offset is not None:
                    kwargs["offset"] = offset
                res, next_offset = client.scroll(**kwargs)
            except Exception:
                break
            if not res:
                break
            _collect(res)
            if next_offset is None:
                break
            offset = next_offset

    out = list(out_dict.values())
    # Type.Method mode: rank title matches above text-only matches
    if use_type_method_mode and out:
        title_lower = q_lower
        out.sort(key=lambda r: (title_lower not in (r.get("title") or "").lower(),))
    elif not version and not language:
        # Prefer newest version first when no version filter
        out.sort(key=lambda r: _version_sort_key(r.get("version", "")), reverse=True)

    return out


def list_index_titles(
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    limit: int = 200,
    path_prefix: str = "",
) -> list[dict[str, Any]]:
    """List (title, path) from index for browsing. path_prefix filters by path start (e.g. 'zif').
    Deduplicates by path (one entry per path when multiple versions exist)."""
    if QdrantClient is None:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = _get_default_qdrant_client(host, port)
    out: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    offset = None
    prefix = (path_prefix or "").strip().lower()
    while len(out) < limit:
        try:
            res, next_offset = client.scroll(
                collection_name=collection,
                limit=min(500, limit - len(out) + 100),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            break
        if not res:
            break
        for point in res:
            if len(out) >= limit:
                break
            payload = getattr(point, "payload", None) or {}
            path = payload.get("path", "")
            if path in seen_paths:
                continue
            if prefix and not path.lower().startswith(prefix):
                continue
            seen_paths.add(path)
            out.append({"title": payload.get("title", ""), "path": path})
        if next_offset is None:
            break
        offset = next_offset
    return out[:limit]


def list_index_nav_items(
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """List (path, title, breadcrumb) from index for building nav tree. Deduplicates by path."""
    if QdrantClient is None:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = _get_default_qdrant_client(host, port)
    if not client.collection_exists(collection):
        return []
    out: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    offset = None
    while len(out) < limit:
        try:
            res, next_offset = client.scroll(
                collection_name=collection,
                limit=min(500, limit - len(out) + 100),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            break
        if not res:
            break
        for point in res:
            if len(out) >= limit:
                break
            payload = getattr(point, "payload", None) or {}
            path = (payload.get("path") or "").strip()
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            out.append(
                {
                    "path": path,
                    "title": payload.get("title", ""),
                    "breadcrumb": payload.get("breadcrumb") or [],
                }
            )
        if next_offset is None:
            break
        offset = next_offset
    return out[:limit]


def _apply_outgoing_links(text: str, payload: dict[str, Any]) -> str:
    """Substitute hrefs with resolved_path and append Связанные темы section."""
    import re

    links = payload.get("outgoing_links") or []
    for lnk in links:
        href = lnk.get("href", "")
        resolved = lnk.get("resolved_path")
        if not href or not resolved:
            continue
        # Substitute [anything](href) -> [anything](resolved_path)
        escaped_href = re.escape(href)
        text = re.sub(r"\[([^\]]*)\]\(\s*" + escaped_href + r"\s*\)", rf"[\1]({resolved})", text)
    # Append related section for links with resolved_path
    with_resolved = [lnk for lnk in links if lnk.get("resolved_path")]
    if with_resolved:
        lines = ["\n\n## Связанные темы\n"]
        for lnk in with_resolved[:20]:
            rp = lnk.get("resolved_path", "")
            title = lnk.get("target_title") or lnk.get("link_text", "")
            if rp:
                lines.append(f"- [{title}]({rp})")
        text = text + "\n".join(lines)
    return text


def get_topic_by_path(help_path, topic_path) -> str:
    """Read topic content: .md first, then .html converted to Markdown."""
    from ..help_core.html2md import (
        _ENCODINGS_UTF8_FIRST,
        html_to_md_content,
        read_file_with_encoding_fallback,
    )

    base = Path(help_path).resolve()
    topic_path = topic_path.lstrip("/")
    # Try as given, then .md, then .html
    candidates = [base / topic_path]
    stem = (base / topic_path).stem
    parent = (base / topic_path).parent
    if stem and str(parent) != ".":
        candidates.append(parent / f"{stem}.md")
        candidates.append(parent / f"{stem}.html")
    if not topic_path.endswith(".md") and not topic_path.endswith(".html"):
        candidates.append(base / f"{topic_path}.md")
        candidates.append(base / f"{topic_path}.html")
    for p in candidates:
        if not path_inside_base(p, base):
            continue
        if p.exists() and p.is_file():
            if p.suffix == ".md":
                return read_file_with_encoding_fallback(p, encodings=_ENCODINGS_UTF8_FIRST)
            if p.suffix == ".html":
                return html_to_md_content(p)
    return ""


def get_topic_content(
    help_path,
    topic_path: str,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    version: str | None = None,
    language: str | None = None,
    prefer_index: bool = False,
) -> str:
    """Get topic text: first from disk (help_path), then from Qdrant payload if not found.
    prefer_index: if True, skip disk and read only from Qdrant."""
    if not prefer_index:
        content = get_topic_by_path(help_path, topic_path)
        if content:
            return content
    return get_topic_from_index(
        topic_path,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=collection,
        version=version,
        language=language,
    )


def get_1c_help_related(
    topic_path: str,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Return list of related topics for a given path: [{path, title}] from outgoing_links.
    Aggregates links from all points with this path (multiple versions/chunks)."""
    if QdrantClient is None or Filter is None or FieldCondition is None or MatchValue is None:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    topic_path = topic_path.lstrip("/")
    path_variants = [topic_path]
    if not topic_path.endswith(".md") and not topic_path.endswith(".html"):
        path_variants.append(topic_path + ".md")
        path_variants.append(topic_path + ".html")
    client = _get_default_qdrant_client(host, port)
    seen_paths: set[str] = set()
    result: list[dict[str, Any]] = []
    for pv in path_variants:
        try:
            must_cond = [FieldCondition(key="path", match=MatchValue(value=pv))]
            if version:
                must_cond.append(FieldCondition(key="version", match=MatchValue(value=version)))
            if language:
                must_cond.append(FieldCondition(key="language", match=MatchValue(value=language)))
            next_offset = None
            scroll_limit = 50
            while True:
                res, next_offset = client.scroll(
                    collection_name=collection,
                    scroll_filter=Filter(must=must_cond),
                    limit=scroll_limit,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not res:
                    break
                for point in res:
                    payload = getattr(point, "payload", None) or {}
                    links = payload.get("outgoing_links") or []
                    for lnk in links:
                        rpath = lnk.get("resolved_path", "")
                        if not rpath or rpath in seen_paths:
                            continue
                        seen_paths.add(rpath)
                        result.append(
                            {
                                "path": rpath,
                                "title": lnk.get("target_title") or lnk.get("link_text", ""),
                            }
                        )
                if next_offset is None:
                    break
            if result:
                return result
        except Exception:
            continue
    return result


def get_1c_help_unresolved_links(
    topic_path: str,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Return outgoing links that have no resolved_path (e.g. v8help:// protocol links).
    Useful as a fallback when get_1c_help_related returns nothing."""
    if QdrantClient is None or Filter is None or FieldCondition is None or MatchValue is None:
        return []
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    topic_path = topic_path.lstrip("/")
    path_variants = [topic_path]
    if not topic_path.endswith(".md") and not topic_path.endswith(".html"):
        path_variants.append(topic_path + ".md")
        path_variants.append(topic_path + ".html")
    client = _get_default_qdrant_client(host, port)
    seen_titles: set[str] = set()
    result: list[dict[str, Any]] = []
    for pv in path_variants:
        try:
            must_cond = [FieldCondition(key="path", match=MatchValue(value=pv))]
            if version:
                must_cond.append(FieldCondition(key="version", match=MatchValue(value=version)))
            if language:
                must_cond.append(FieldCondition(key="language", match=MatchValue(value=language)))
            pts, _ = client.scroll(
                collection_name=collection,
                scroll_filter=Filter(must=must_cond),
                limit=10,
                with_payload=True,
                with_vectors=False,
            )
            for pt in pts:
                payload = getattr(pt, "payload", None) or {}
                for lnk in payload.get("outgoing_links") or []:
                    if lnk.get("resolved_path"):
                        continue  # already resolved — skip
                    title = lnk.get("target_title") or lnk.get("link_text", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        result.append({"target_title": title, "href": lnk.get("href", "")})
            if result:
                return result
        except Exception:
            continue
    return result


# Version prefix at start of path (e.g. 8.2.19.130 or 8.3.27.1859) as stored in index
_VERSION_PREFIX_RE = re.compile(r"^8\.\d+\.\d+\.\d+/")


def _path_without_version_prefix(path: str) -> str:
    """Strip leading version segment so path can be used with any version. E.g. 8.3.13.1513/shcntx_ru/... -> shcntx_ru/..."""
    return _VERSION_PREFIX_RE.sub("", path, count=1).lstrip("/") or path


def _pick_best_path_for_compare(
    results: list[dict[str, Any]], query: str | None = None
) -> str | None:
    """From search results, pick path of a topic with a meaningful title (not Untitled). Prefer exact name matches, then .html/.md."""
    if not results:
        return None
    untitled_lower = "untitled"
    query_lower = (query or "").strip().lower()

    # First priority: exact name match
    if query_lower:
        for r in results:
            name = (r.get("name") or "").strip().lower()
            if name == query_lower:
                p = (r.get("path") or "").strip()
                if p and ".html" in p or ".md" in p:
                    title = (r.get("title") or "").strip()
                    if title.lower() != untitled_lower:
                        return p

    # Second: any name match with .html/.md and meaningful title
    for r in results:
        p = (r.get("path") or "").strip()
        if not p:
            continue
        title = (r.get("title") or "").strip()
        if title.lower() == untitled_lower:
            continue
        if ".html" in p or ".md" in p:
            return p

    # Third: any with meaningful title
    for r in results:
        p = (r.get("path") or "").strip()
        if not p:
            continue
        title = (r.get("title") or "").strip()
        if title.lower() != untitled_lower:
            return p

    # Last resort: first result
    return (results[0].get("path") or "").strip() or None


def compare_1c_help(
    topic_path_or_query: str,
    version_left: str,
    version_right: str,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = COLLECTION_NAME,
    language: str | None = None,
    include_diff: bool = False,
) -> str:
    """Compare topic content between two versions. Returns formatted comparison or diff."""
    path = topic_path_or_query.strip()
    is_query = ".md" not in path and ".html" not in path

    def find_topic_path(version: str) -> str | None:
        if not is_query:
            # User provided exact path, use it directly for this version
            rel_path = _path_without_version_prefix(path)
            return f"{version}/{rel_path}" if rel_path else path

        # Search for topic in this specific version
        results = search_index_keyword(
            path,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            collection=collection,
            limit=5,
            version=version,
            language=language,
        )
        if not results:
            results = search_index(
                path,
                qdrant_host=qdrant_host,
                qdrant_port=qdrant_port,
                collection=collection,
                limit=5,
                version=version,
                language=language,
            )
        return _pick_best_path_for_compare(results, path) if results else None

    path_left = find_topic_path(version_left)
    path_right = find_topic_path(version_right)

    if not path_left and not path_right:
        return f"Topic not found for query: {path}"

    content_left = (
        get_topic_content(
            "",
            path_left,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            collection=collection,
            version=version_left,
            language=language,
            prefer_index=True,
        )
        if path_left
        else ""
    )

    content_right = (
        get_topic_content(
            "",
            path_right,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            collection=collection,
            version=version_right,
            language=language,
            prefer_index=True,
        )
        if path_right
        else ""
    )

    if not content_left and not content_right:
        return f"Topic not found in either version for query: {path} (versions {version_left}, {version_right})"
    out = f"## Версия {version_left}\n\n{content_left or '(нет контента)'}\n\n---\n\n## Версия {version_right}\n\n{content_right or '(нет контента)'}"
    if include_diff and content_left and content_right:
        import difflib

        lines_left = content_left.splitlines(keepends=True)
        lines_right = content_right.splitlines(keepends=True)
        diff = difflib.unified_diff(
            lines_left,
            lines_right,
            fromfile=f"v{version_left}",
            tofile=f"v{version_right}",
            lineterm="",
        )
        out += "\n\n---\n\n## Diff\n\n```\n" + "".join(diff) + "\n```"
    return out
