"""Tests for sparse_bm25 module."""

import os
from pathlib import Path
from unittest.mock import patch

from onec_help.sparse_bm25 import (
    bm25_vocab_path,
    build_bm25_vectors,
    load_vocab,
    query_vector,
    save_vocab,
    tokenize_bm25,
)


def test_tokenize_empty_or_invalid() -> None:
    """tokenize_bm25 returns [] for empty, None, or non-string."""
    assert tokenize_bm25("") == []
    assert tokenize_bm25(None) == []
    assert tokenize_bm25(123) == []


def test_query_vector_empty_toks_returns_empty() -> None:
    """query_vector with empty tokenization returns empty vector."""
    assert query_vector("", {"a": 0}, {"a": 1}, 10) == {"indices": [], "values": []}


def test_query_vector_empty_vocab_returns_empty() -> None:
    """query_vector with empty vocab returns empty vector."""
    assert query_vector("слово", {}, {}, 10) == {"indices": [], "values": []}


def test_query_vector_n_zero_returns_empty() -> None:
    """query_vector with N<=0 returns empty vector."""
    assert query_vector("слово", {"слово": 0}, {"слово": 1}, 0) == {"indices": [], "values": []}


def test_query_vector_term_not_in_vocab_skipped() -> None:
    """Terms not in vocab are skipped; only known terms included."""
    # Use Latin to avoid stemming affecting vocab match
    vocab = {"word": 0, "test": 1}
    doc_freq = {"word": 1, "test": 2}
    result = query_vector("word unknown test", vocab, doc_freq, 10)
    assert len(result["indices"]) == 2
    assert 0 in result["indices"]
    assert 1 in result["indices"]


def test_query_vector_duplicate_term_deduped() -> None:
    """Duplicate terms in query yield single index (seen set)."""
    vocab = {"word": 0}
    doc_freq = {"word": 1}
    result = query_vector("word word word", vocab, doc_freq, 10)
    assert result["indices"] == [0]
    assert len(result["values"]) == 1


def test_save_load_vocab_roundtrip(tmp_path: Path) -> None:
    """save_vocab and load_vocab roundtrip."""
    p = tmp_path / "bm25" / "test.json"
    vocab = {"a": 0, "b": 1}
    doc_freq = {"a": 2, "b": 1}
    N = 5
    save_vocab(p, vocab, doc_freq, N)
    v2, df2, n2 = load_vocab(p)
    assert v2 == vocab
    assert df2 == doc_freq
    assert n2 == N


def test_load_vocab_missing_keys_uses_defaults(tmp_path: Path) -> None:
    """load_vocab with partial JSON uses empty dicts and 0 for N."""
    p = tmp_path / "partial.json"
    p.write_text("{}", encoding="utf-8")
    v, df, n = load_vocab(p)
    assert v == {}
    assert df == {}
    assert n == 0


def test_bm25_vocab_path_default() -> None:
    """bm25_vocab_path returns path under data/bm25_vocab."""
    with patch.dict(os.environ, {"DATA_DIR": "data"}):
        p = bm25_vocab_path("onec_help")
    assert "bm25_vocab" in str(p)
    assert p.name == "onec_help.json"


def test_bm25_vocab_path_custom_collection() -> None:
    """bm25_vocab_path uses collection name."""
    with patch.dict(os.environ, {"DATA_DIR": "data"}):
        p = bm25_vocab_path("custom")
    assert p.name == "custom.json"


def test_build_bm25_vectors_empty_corpus() -> None:
    """build_bm25_vectors with empty list returns empty structures."""
    vectors, vocab, doc_freq = build_bm25_vectors([])
    assert vectors == []
    assert vocab == {}
    assert doc_freq == {}
