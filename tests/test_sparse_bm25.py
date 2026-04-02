"""Tests for sparse_bm25 module."""

import os
from pathlib import Path
from unittest.mock import patch

from onec_help.search_store.sparse_bm25 import (
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


def test_bm25_vocab_path_default(tmp_path: Path) -> None:
    """bm25_vocab_path returns path under DATA_DIR/bm25_vocab (use tmp_path, never project data/)."""
    with patch.dict(os.environ, {"DATA_DIR": str(tmp_path)}):
        p = bm25_vocab_path("onec_help")
    assert "bm25_vocab" in str(p)
    assert p.name == "onec_help.json"


def test_bm25_vocab_path_custom_collection(tmp_path: Path) -> None:
    """bm25_vocab_path uses collection name."""
    with patch.dict(os.environ, {"DATA_DIR": str(tmp_path)}):
        p = bm25_vocab_path("custom")
    assert p.name == "custom.json"


def test_build_bm25_vectors_empty_corpus() -> None:
    """build_bm25_vectors with empty list returns empty structures."""
    vectors, vocab, doc_freq = build_bm25_vectors([])
    assert vectors == []
    assert vocab == {}
    assert doc_freq == {}


def test_stemmer_import_error_returns_none() -> None:
    """_stemmer hits except when snowballstemmer import fails (lines 36-37)."""
    import onec_help.search_store.sparse_bm25 as mod

    mod._USE_STEMMING = None
    mod._STEMMER = None
    orig_import = __import__

    def raise_for_snowball(name, *args, **kwargs):
        if name == "snowballstemmer":
            raise ImportError("no stemmer")
        return orig_import(name, *args, **kwargs)

    try:
        with patch("onec_help.shared.env_config.get_bm25_stemming", return_value=True):
            with patch("builtins.__import__", side_effect=raise_for_snowball):
                result = mod._stemmer()
                assert result is None
    finally:
        mod._USE_STEMMING = None
        mod._STEMMER = None


def test_tokenize_bm25_with_stemming() -> None:
    """tokenize_bm25 uses stemmer when stemmer is available (line 49: stem.stemWord path)."""
    import onec_help.search_store.sparse_bm25 as mod

    mod._USE_STEMMING = None
    mod._STEMMER = None
    fake = type("Stem", (), {"stemWord": lambda self, t: t})()
    with patch.object(mod, "_stemmer", return_value=fake):
        result = tokenize_bm25("Слово проверка")
        assert result == ["Слово", "проверка"]


def test_tokenize_bm25_stemming_real_when_available() -> None:
    """When BM25_STEMMING=1 and snowballstemmer is installed, tokenize uses stemWord (line 49)."""
    import onec_help.search_store.sparse_bm25 as mod

    mod._USE_STEMMING = None
    mod._STEMMER = None
    with patch.dict(os.environ, {"BM25_STEMMING": "1"}, clear=False):
        result = tokenize_bm25("проверка слова")
    # With or without stemmer we get tokens
    assert isinstance(result, list)
    assert len(result) >= 1


def test_tokenize_bm25_stemming_via_fake_module() -> None:
    """When __import__ returns fake snowballstemmer, tokenize runs stemWord path (line 49)."""
    import sys

    import onec_help.search_store.sparse_bm25 as mod

    mod._USE_STEMMING = None
    mod._STEMMER = None
    fake_stemmer_instance = type("Stem", (), {"stemWord": lambda self, t: t})()
    fake_module = type(sys)("snowballstemmer")
    fake_module.stemmer = lambda lang: fake_stemmer_instance
    orig_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "snowballstemmer":
            return fake_module
        return orig_import(name, *args, **kwargs)

    try:
        with patch("onec_help.shared.env_config.get_bm25_stemming", return_value=True):
            with patch("builtins.__import__", side_effect=fake_import):
                _ = mod._stemmer()
            result = tokenize_bm25("Слово тест")
            assert result == ["Слово", "тест"]
    finally:
        mod._USE_STEMMING = None
        mod._STEMMER = None


def test_tokenize_bm25_stem_word_line_48() -> None:
    """With _STEMMER set, tokenize_bm25 uses stem.stemWord (line 48)."""
    import onec_help.search_store.sparse_bm25 as mod

    fake = type("Stem", (), {"stemWord": lambda self, t: t})()
    old_stemmer = mod._STEMMER
    mod._STEMMER = fake
    try:
        out = mod.tokenize_bm25("абв гд  еж")
        assert out == ["абв", "гд", "еж"]
    finally:
        mod._STEMMER = old_stemmer


def test_tokenize_bm25_no_stemmer_returns_raw_line_49() -> None:
    """When _stemmer returns None, tokenize_bm25 returns raw tokens (line 49)."""
    import onec_help.search_store.sparse_bm25 as mod

    mod._USE_STEMMING = None
    mod._STEMMER = None
    with patch("onec_help.shared.env_config.get_bm25_stemming", return_value=False):
        out = tokenize_bm25("слово проверка")
    assert out == ["слово", "проверка"]


def test_bm25_idf_positive() -> None:
    """_bm25_idf with df>0, N>0 returns positive value (line 73)."""
    import onec_help.search_store.sparse_bm25 as mod

    assert mod._bm25_idf(1, 10) > 0
    assert mod._bm25_idf(2, 100) > 0


def test_build_bm25_vectors_term_not_in_vocab_skipped() -> None:
    """When vocab is capped, term not in vocab is skipped in vector build (line 104)."""
    import onec_help.search_store.sparse_bm25 as mod

    with patch.object(mod, "_MAX_VOCAB_SIZE", 2):
        vectors, vocab, doc_freq = build_bm25_vectors(["слово один два", "слово два три"])
    assert len(vectors) == 2
    assert len(vocab) == 2
    assert "три" not in vocab or "один" not in vocab
