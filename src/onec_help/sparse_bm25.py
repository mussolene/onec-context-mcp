"""BM25 sparse vectors for keyword search. Cyrillic and Latin aware, optional stemming."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

_BM25_K1 = 1.5
_BM25_B = 0.75
_MIN_TOKEN_LEN = 2
_MAX_VOCAB_SIZE = 200_000

# Cyrillic + Latin + digits
_TOKEN_RE = re.compile(r"[а-яёА-ЯЁa-zA-Z0-9]+")

_USE_STEMMING: bool | None = None
_STEMMER: Any = None


def _stemmer():
    """Lazy Snowball stemmer (Russian). Latin tokens pass through unchanged."""
    global _USE_STEMMING, _STEMMER
    if _USE_STEMMING is None:
        from . import env_config

        _USE_STEMMING = env_config.get_bm25_stemming()
    if _USE_STEMMING and _STEMMER is None:
        try:
            import snowballstemmer

            _STEMMER = snowballstemmer.stemmer("russian")  # type: ignore[union-attr]
        except Exception:
            _STEMMER = False
    return _STEMMER if _STEMMER else None


def tokenize_bm25(text: str) -> list[str]:
    """Extract tokens (Cyrillic, Latin, digits, min 2 chars). Optionally stem (BM25_STEMMING=1)."""
    if not text or not isinstance(text, str):
        return []
    raw = [t for t in _TOKEN_RE.findall(text) if len(t) >= _MIN_TOKEN_LEN]
    stem = _stemmer()
    if stem:
        return [stem.stemWord(t) for t in raw]  # type: ignore[union-attr]
    return raw


def _bm25_build_vocab_and_stats(
    corpus_texts: list[str],
) -> tuple[dict[str, int], list[list[str]], list[int], float]:
    """Build vocabulary and stats. Returns (vocab, doc_tokens, doc_lens, avgdl)."""
    vocab: dict[str, int] = {}
    doc_tokens: list[list[str]] = []
    doc_lens: list[int] = []
    for text in corpus_texts:
        toks = tokenize_bm25((text or "").lower())
        doc_tokens.append(toks)
        doc_lens.append(len(toks))
        for t in set(toks):
            if t not in vocab and len(vocab) < _MAX_VOCAB_SIZE:
                vocab[t] = len(vocab)
    avgdl = sum(doc_lens) / len(doc_lens) if doc_lens else 0.0
    return vocab, doc_tokens, doc_lens, avgdl


def _bm25_idf(df: int, N: int) -> float:
    """BM25 IDF component."""
    if N <= 0 or df <= 0:
        return 0.0
    return max(0.0, math.log((N - df + 0.5) / (df + 0.5) + 1.0))


def build_bm25_vectors(
    corpus_texts: list[str],
    k1: float = _BM25_K1,
    b: float = _BM25_B,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    """Build BM25 sparse vectors for documents.

    Returns (vectors, vocab, doc_freq).
    Each vector: {"indices": [...], "values": [...]} for SparseVector.
    vocab: term -> index. doc_freq: term -> document frequency (for query).
    """
    if not corpus_texts:
        return [], {}, {}

    vocab, doc_tokens, doc_lens, avgdl = _bm25_build_vocab_and_stats(corpus_texts)
    df: dict[str, int] = Counter()
    for toks in doc_tokens:
        for t in set(toks):
            df[t] += 1

    vectors: list[dict[str, Any]] = []
    for i, toks in enumerate(doc_tokens):
        c = Counter(toks)
        dl = doc_lens[i]
        indices, values = [], []
        for term, tf in c.items():
            if term not in vocab:
                continue
            idx = vocab[term]
            # Doc component only (IDF in query); dot product = BM25 score
            w = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
            indices.append(idx)
            values.append(round(w, 6))
        vectors.append({"indices": indices, "values": values})
    return vectors, vocab, dict(df)


def query_vector(
    query: str,
    vocab: dict[str, int],
    doc_freq: dict[str, int],
    N: int,
) -> dict[str, Any]:
    """Build BM25 sparse vector for query (IDF-weighted).

    Returns {"indices": [...], "values": [...]} for SparseVector.
    Dot product with doc vector yields BM25 score.
    """
    toks = tokenize_bm25((query or "").lower())
    if not toks or not vocab or N <= 0:
        return {"indices": [], "values": []}
    seen: set[int] = set()
    indices, values = [], []
    for term in toks:
        if term not in vocab:
            continue
        idx = vocab[term]
        if idx in seen:
            continue
        seen.add(idx)
        df = doc_freq.get(term, 0)
        idf = _bm25_idf(df, N)
        indices.append(idx)
        values.append(round(idf, 6))
    return {"indices": indices, "values": values}


def save_vocab(path: str | Path, vocab: dict[str, int], doc_freq: dict[str, int], N: int) -> None:
    """Save vocab, doc_freq, and N to JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"vocab": vocab, "doc_freq": doc_freq, "N": N}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_vocab(
    path: str | Path,
) -> tuple[dict[str, int], dict[str, int], int]:
    """Load vocab, doc_freq, N from JSON. Returns (vocab, doc_freq, N)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return (
        data.get("vocab") or {},
        data.get("doc_freq") or {},
        int(data.get("N") or 0),
    )


def bm25_vocab_path(collection: str = "onec_help") -> Path:
    """Default path for BM25 vocab file."""
    from . import env_config

    base = Path(env_config.get_data_dir())
    if not base.is_absolute():
        base = Path.cwd() / base
    return base.resolve() / "bm25_vocab" / f"{collection}.json"
