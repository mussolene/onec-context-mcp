"""
Triple memory: short (in-memory), medium (JSONL file), long (Qdrant onec_help_memory).
Triple-write on each event; long uses embedding or pending queue when unavailable.
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Optional

_MEMORY_COLLECTION = "onec_help_memory"
_store: Optional["MemoryStore"] = None
_store_lock = threading.Lock()

# Shared QdrantClient for memory operations (thread-safe, avoids new TCP conn per write/search).
_memory_qdrant_client: Optional[Any] = None
_memory_qdrant_client_lock = threading.Lock()


def _get_memory_qdrant_client() -> Any:
    """Return shared QdrantClient for onec_help_memory. Creates once, reuses thereafter."""
    global _memory_qdrant_client
    if _memory_qdrant_client is not None:
        return _memory_qdrant_client
    with _memory_qdrant_client_lock:
        if _memory_qdrant_client is None:
            from qdrant_client import QdrantClient as _QdrantClient

            from . import env_config

            _memory_qdrant_client = _QdrantClient(
                host=env_config.get_qdrant_host(),
                port=env_config.get_qdrant_port(),
                check_compatibility=False,
            )
        return _memory_qdrant_client


def get_memory_store(base_path: Path | None = None) -> "MemoryStore":
    """Return singleton MemoryStore. base_path from env MEMORY_BASE_PATH or ~/.onec_help."""
    global _store
    with _store_lock:
        if _store is None:
            from . import env_config

            path = base_path
            if path is None:
                p = env_config.get_memory_base_path()
                path = Path(p).expanduser() if p else Path.home() / ".onec_help"
            short = env_config.get_memory_short_limit()
            medium = env_config.get_memory_medium_limit()
            ttl = env_config.get_memory_medium_ttl_days()
            _store = MemoryStore(path, short_limit=short, medium_limit=medium, medium_ttl_days=ttl)
        return _store


def _is_memory_enabled() -> bool:
    from . import env_config

    return env_config.get_memory_enabled()


class MemoryStore:
    """Triple-write memory: short (deque), medium (JSONL), long (Qdrant or pending)."""

    def __init__(
        self,
        base_path: Path,
        short_limit: int = 50,
        medium_limit: int = 500,
        medium_ttl_days: int = 7,
    ) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._short: deque = deque(maxlen=short_limit)
        self._short_lock = threading.Lock()
        self.medium_limit = medium_limit
        self.medium_ttl_days = medium_ttl_days
        self.medium_path = self.base_path / "session_memory.jsonl"
        self.pending_path = self.base_path / "pending_memory.json"

    def write_event(
        self,
        event_type: Literal["get_topic", "save_snippet", "exchange"],
        payload: dict[str, Any],
        domain: str = "user",
    ) -> None:
        """Atomically write to short, medium; for long call _write_long_or_pending."""
        if not _is_memory_enabled():
            return
        ts = time.time()
        payload_copy = dict(payload)
        payload_copy["type"] = event_type
        payload_copy["ts"] = ts
        payload_copy["domain"] = domain

        with self._short_lock:
            self._short.append(payload_copy)

        summary_medium = self._format_medium_summary(event_type, payload_copy)
        self._append_medium(ts, summary_medium)

        self._write_long_or_pending(event_type, payload_copy, ts)

    def _format_medium_summary(self, event_type: str, payload: dict[str, Any]) -> str:
        query = payload.get("query", "")
        topic_path = payload.get("topic_path", "")
        paths = (
            topic_path
            if isinstance(topic_path, str)
            else ", ".join(topic_path)
            if topic_path
            else ""
        )
        desc = payload.get("description", "") or payload.get("response_snippet", "")[:200]
        return f"[{payload.get('ts', 0)}] Запрос: {query}. Топики: {paths}. Сниппет: {desc}."

    def _append_medium(self, ts: float, summary: str) -> None:
        try:
            with open(self.medium_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts, "summary": summary}, ensure_ascii=False) + "\n")
            self._trim_medium()
        except OSError:
            pass

    def _trim_medium(self) -> None:
        try:
            if not self.medium_path.exists():
                return
            lines = self.medium_path.read_text(encoding="utf-8").strip().split("\n")
            if not lines:
                return
            cutoff = time.time() - self.medium_ttl_days * 86400
            kept = []
            for ln in lines:
                try:
                    obj = json.loads(ln)
                    if obj.get("ts", 0) > cutoff:
                        kept.append(ln)
                except json.JSONDecodeError:
                    continue
            if len(kept) > self.medium_limit:
                kept = kept[-self.medium_limit :]
            self.medium_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except OSError:
            pass

    def _write_long_or_pending(self, event_type: str, payload: dict[str, Any], ts: float) -> None:
        from . import embedding

        if not embedding.is_embedding_available():
            self._append_pending(payload, ts)
            return
        summary = self._format_long_summary(payload)
        try:
            vec = embedding.get_embedding(summary)
            self._upsert_long(str(uuid.uuid4()), vec, {**payload, "summary": summary})
        except Exception:
            self._append_pending(payload, ts)

    def _format_long_summary(self, payload: dict[str, Any]) -> str:
        title = payload.get("title", "")
        query = payload.get("query", "")
        topic_path = payload.get("topic_path", "")
        tags = str(topic_path) if topic_path else ""
        if title or query or tags:
            return f"1C Help: {title} | {query} | {tags}"
        desc = payload.get("description", "") or ""
        code = (payload.get("code_snippet", "") or "")[:300]
        return f"1C snippet: {desc} | {code}"

    def _upsert_long(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
        numeric_id: int | None = None,
    ) -> None:
        try:
            from qdrant_client.models import Distance, PointStruct, VectorParams

            client = _get_memory_qdrant_client()
            if not client.collection_exists(_MEMORY_COLLECTION):
                client.create_collection(
                    collection_name=_MEMORY_COLLECTION,
                    vectors_config=VectorParams(size=len(vector), distance=Distance.COSINE),
                )
            if numeric_id is None:
                numeric_id = abs(hash(point_id)) % (2**63)
            client.upsert(
                collection_name=_MEMORY_COLLECTION,
                points=[PointStruct(id=numeric_id, vector=vector, payload=payload)],
            )
        except Exception as e:
            logging.getLogger(__name__).debug("memory _upsert_long failed: %s", e)

    def _append_pending(self, payload: dict[str, Any], ts: float) -> None:
        try:
            data: list[dict[str, Any]] = []
            if self.pending_path.exists():
                raw = self.pending_path.read_text(encoding="utf-8")
                if raw.strip():
                    data = json.loads(raw)
            data.append({"id": str(uuid.uuid4()), "payload": payload, "created_at": ts})
            self.pending_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError):
            pass

    def get_short(self) -> list[dict[str, Any]]:
        """Last N records (FIFO)."""
        with self._short_lock:
            return list(self._short)

    def get_medium(self) -> list[dict[str, Any]]:
        """Records with TTL; format [{ts, summary}]."""
        cutoff = time.time() - self.medium_ttl_days * 86400
        out: list[dict[str, Any]] = []
        try:
            if not self.medium_path.exists():
                return []
            for ln in self.medium_path.read_text(encoding="utf-8").strip().split("\n"):
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                    if obj.get("ts", 0) > cutoff:
                        out.append({"ts": obj.get("ts"), "summary": obj.get("summary", "")})
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        return out[-self.medium_limit :]

    def process_pending(self) -> int:
        """Process pending_memory.json: embed and upsert to onec_help_memory when embedding available.
        Returns number of processed items. Uses get_embedding_batch for throughput."""
        from . import embedding

        if not embedding.is_embedding_available():
            return 0
        try:
            if not self.pending_path.exists():
                return 0
            raw = self.pending_path.read_text(encoding="utf-8")
            if not raw.strip():
                return 0
            data = json.loads(raw)
            if not isinstance(data, list):
                return 0
            remaining: list[dict[str, Any]] = []
            to_process: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
            for item in data:
                if not isinstance(item, dict):
                    remaining.append(item)
                    continue
                payload = item.get("payload", {})
                if not payload:
                    continue
                summary = self._format_long_summary(payload)
                to_process.append((item, summary, {**payload, "summary": summary}))
            if not to_process:
                return 0
            texts = [s for _, s, _ in to_process]
            vectors = embedding.get_embedding_batch(texts)
            if len(vectors) != len(to_process):
                logging.getLogger(__name__).debug(
                    "process_pending embedding count mismatch (%s != %s), retrying batch",
                    len(vectors),
                    len(to_process),
                )
                vectors = embedding.get_embedding_batch(texts)
            if len(vectors) != len(to_process):
                remaining.extend(item for item, _, _ in to_process)
                self.pending_path.write_text(
                    json.dumps(remaining, ensure_ascii=False, indent=0), encoding="utf-8"
                )
                return 0
            processed = 0
            for (item, _, full_payload), vec in zip(to_process, vectors, strict=True):
                try:
                    self._upsert_long(item.get("id", str(uuid.uuid4())), vec, full_payload)
                    processed += 1
                except Exception:
                    remaining.append(item)
            if processed > 0:
                self.pending_path.write_text(
                    json.dumps(remaining, ensure_ascii=False, indent=0), encoding="utf-8"
                )
            return processed
        except (OSError, json.JSONDecodeError):
            return 0

    def upsert_curated_snippets(
        self,
        items: list[dict[str, Any]],
        progress_callback: Callable[[int, int, int], None] | None = None,
        domain: str = "snippets",
    ) -> int:
        """Bulk upsert curated items into long memory.
        items: [{title, description, code_snippet?, instruction?}, ...]. Returns count of upserted items.
        instruction: full text for references (community_help); used instead of code_snippet for embedding.
        progress_callback: optional (done, total, skipped) called periodically.
        domain: 'snippets' | 'community_help' | 'standards' — filter for search_long.
        Uses get_embedding_batch for throughput (same benefits as help indexer)."""
        from . import embedding

        if not embedding.is_embedding_available():
            return 0
        total = len(items)
        skipped = 0
        valid: list[tuple[str, dict[str, Any], str, int]] = []
        prefix = domain[:8]
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            title = item.get("title", "") or ""
            desc = item.get("description", "") or ""
            code = item.get("code_snippet", "") or ""
            instruction = item.get("instruction", "") or ""
            if not title and not code and not instruction:
                skipped += 1
                continue
            # References (community_help): use instruction (full text) for embedding
            if instruction:
                summary = f"{title} | {instruction[:2000]}"
            else:
                summary = f"{title} | {desc} | {code[:300]}"
            payload = {
                "title": title,
                "description": desc,
                "code_snippet": code,
                "domain": domain,
                "summary": summary,
            }
            if instruction:
                payload["instruction"] = instruction
            if item.get("detail_url"):
                payload["detail_url"] = item["detail_url"]
            if item.get("source_site"):
                payload["source_site"] = item["source_site"]
            if item.get("source"):
                payload["source"] = item["source"]
            point_id = f"{prefix}_{hashlib.sha256(title.encode()).hexdigest()[:12]}"
            numeric_id = int(hashlib.sha256(point_id.encode()).hexdigest()[:14], 16) % (2**63)
            valid.append((summary, payload, point_id, numeric_id))
        if not valid:
            if progress_callback:
                progress_callback(0, total, skipped)
            return 0
        # Process in chunks so progress_callback runs during embedding (dashboard shows loaded/total)
        chunk_size = max(32, min(256, len(valid) // 10 or 32))
        count = 0
        for start in range(0, len(valid), chunk_size):
            chunk = valid[start : start + chunk_size]
            texts = [s for s, _, _, _ in chunk]
            vectors = embedding.get_embedding_batch(texts)
            if len(vectors) != len(chunk):
                logging.getLogger(__name__).debug(
                    "upsert_curated_snippets embedding count mismatch (%s != %s), retrying chunk",
                    len(vectors),
                    len(chunk),
                )
                vectors = embedding.get_embedding_batch(texts)
            if len(vectors) != len(chunk):
                skipped += len(chunk)
                if progress_callback:
                    progress_callback(count, total, skipped)
                continue
            for (_, payload, point_id, numeric_id), vec in zip(chunk, vectors, strict=True):
                try:
                    self._upsert_long(point_id, vec, payload, numeric_id=numeric_id)
                    count += 1
                except Exception:
                    skipped += 1
            if progress_callback:
                progress_callback(count, total, skipped)
        return count

    def search_long(
        self,
        query: str,
        limit: int = 5,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search onec_help_memory by hybrid BM25+semantic with RRF fusion."""
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

            from . import embedding

            client = _get_memory_qdrant_client()
            if not client.collection_exists(_MEMORY_COLLECTION):
                return []

            query_filter = None
            if domain and Filter and FieldCondition and MatchValue:
                query_filter = Filter(
                    must=[FieldCondition(key="domain", match=MatchValue(value=domain))]
                )

            fetch_limit = limit * 3  # fetch more for RRF merging
            vec = embedding.get_embedding(query)
            semantic_res = client.query_points(
                collection_name=_MEMORY_COLLECTION,
                query=vec,
                limit=fetch_limit,
                with_payload=True,
                query_filter=query_filter,
            )
            semantic_pts = getattr(semantic_res, "points", [])

            # BM25 hybrid leg
            bm25_pts: list[Any] = []
            try:
                from . import env_config as _ec
                from .sparse_bm25 import bm25_vocab_path, load_vocab, query_vector

                vp = bm25_vocab_path(_MEMORY_COLLECTION)
                if vp.exists():
                    vocab, doc_freq, N = load_vocab(vp)
                    qv = query_vector(query, vocab, doc_freq, N)
                    if qv.get("indices"):
                        sv = SparseVector(indices=qv["indices"], values=qv["values"])
                        bm25_res = client.query_points(
                            collection_name=_MEMORY_COLLECTION,
                            query=sv,
                            using="text-bm25",
                            limit=fetch_limit,
                            with_payload=True,
                            query_filter=query_filter,
                        )
                        bm25_pts = getattr(bm25_res, "points", [])
            except Exception:
                pass

            # RRF merge
            _RRF_K = 60
            rrf: dict[Any, float] = {}
            id_to_pt: dict[Any, Any] = {}
            for rank, pt in enumerate(semantic_pts, 1):
                pid = getattr(pt, "id", None)
                if pid is not None:
                    rrf[pid] = rrf.get(pid, 0) + 1 / (_RRF_K + rank)
                    id_to_pt[pid] = pt
            for rank, pt in enumerate(bm25_pts, 1):
                pid = getattr(pt, "id", None)
                if pid is not None:
                    rrf[pid] = rrf.get(pid, 0) + 1 / (_RRF_K + rank)
                    if pid not in id_to_pt:
                        id_to_pt[pid] = pt

            merged = sorted(id_to_pt.values(), key=lambda p: -rrf.get(getattr(p, "id", None), 0))
            return [
                {"payload": getattr(p, "payload", {}), "score": rrf.get(getattr(p, "id", None), 0)}
                for p in merged[:limit]
            ]
        except Exception:
            return []
