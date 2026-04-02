"""Tests for onec_help.shared._http (SSL/HTTP helpers)."""

import importlib
import ssl
import sys
from unittest.mock import MagicMock, patch

import onec_help.shared._http as _http


def test_get_ssl_context() -> None:
    ctx = _http.get_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)


def test_create_opener_default_context() -> None:
    opener = _http.create_opener()
    assert opener is not None


def test_create_opener_explicit_context() -> None:
    ctx = ssl.create_default_context()
    opener = _http.create_opener(ssl_context=ctx)
    assert opener is not None


def test_create_opener_unverified() -> None:
    opener = _http.create_opener_unverified()
    assert opener is not None


def test_get_opener_for_base_url_success() -> None:
    """When open succeeds, returns the default opener."""
    fake_resp = MagicMock()
    fake_resp.read.return_value = b"ok"
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    mock_opener = MagicMock(open=MagicMock(return_value=fake_resp))
    with patch.object(_http, "create_opener", return_value=mock_opener):
        with patch.object(_http, "create_opener_unverified") as unver:
            opener = _http.get_opener_for_base_url("https://example.com", path="/", timeout=1)
            assert opener is mock_opener
            unver.assert_not_called()


def test_get_opener_for_base_url_ssl_fallback() -> None:
    """When open raises SSL error, returns unverified opener."""

    def raise_ssl(*args, **kwargs):
        raise OSError("SSL: CERTIFICATE_VERIFY_FAILED")

    with patch.object(_http, "create_opener") as create:
        with patch.object(_http, "create_opener_unverified") as unver:
            unver.return_value = MagicMock()
            create.return_value = MagicMock(open=raise_ssl)
            opener = _http.get_opener_for_base_url("https://example.com", path="/", timeout=1)
            assert opener is unver.return_value
            unver.assert_called_once()


def test_get_opener_for_base_url_non_ssl_error_reraise() -> None:
    """When open raises non-SSL error, re-raise."""

    def raise_other(*args, **kwargs):
        raise OSError("Connection refused")

    with patch.object(_http, "create_opener") as create:
        create.return_value = MagicMock(open=raise_other)
        try:
            _http.get_opener_for_base_url("https://example.com", path="/", timeout=1)
            raise AssertionError("Expected OSError")
        except OSError as e:
            assert "Connection" in str(e)


def test_get_ssl_context_without_certifi() -> None:
    """When certifi is not installed, get_ssl_context uses system default (ImportError branch)."""
    had_certifi = "certifi" in sys.modules
    if had_certifi:
        certifi_mod = sys.modules.pop("certifi")
    try:
        # Reload so the try/except runs again without certifi
        importlib.reload(_http)
        ctx = _http.get_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
    finally:
        if had_certifi:
            sys.modules["certifi"] = certifi_mod
            importlib.reload(_http)


def test_fetch_url() -> None:
    body = "привет".encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    opener = MagicMock()
    opener.open.return_value = resp
    text = _http.fetch_url("https://example.com/page", opener, timeout=5)
    assert text == "привет"
