"""Tests for web module."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onec_help.web import _allowed_base_dirs, _directory_allowed, app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["BASE_DIR"] = None
    return app.test_client()


def test_ready(client) -> None:
    r = client.get("/ready")
    assert r.status_code == 200
    assert b"ok" in r.data


def test_index_get(client) -> None:
    r = client.get("/")
    assert r.status_code == 200


def test_content_no_dir(client) -> None:
    r = client.get("/content/some.html")
    assert r.status_code == 400


def test_content_with_dir(client, help_sample_dir: Path) -> None:
    from onec_help.web import app

    app.config["BASE_DIR"] = str(help_sample_dir)
    r = client.get("/content/field626.html")
    assert r.status_code == 200
    data = r.get_json()
    assert "content" in data


def test_content_exception_returns_500(client, help_sample_dir: Path) -> None:
    from onec_help.web import app

    app.config["BASE_DIR"] = str(help_sample_dir)
    with patch("onec_help.web.get_html_content") as mock_get:
        mock_get.side_effect = OSError("file not found")
        r = client.get("/content/missing.html")
    assert r.status_code == 500
    data = r.get_json()
    assert "error" in data


def test_index_post_success(client, help_sample_dir: Path) -> None:
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(help_sample_dir.parent)}):
        r = client.post("/", data={"directory": str(help_sample_dir)})
    assert r.status_code == 200
    assert b"tree_elements" in r.data or b"tree" in r.data


def test_index_post_invalid_dir(client, tmp_path: Path) -> None:
    r = client.post("/", data={"directory": str(tmp_path / "nonexistent")})
    assert r.status_code == 200
    assert b"Invalid" in r.data or b"error" in r.data.lower()


def test_download_no_dir(client) -> None:
    r = client.get("/download/some.html")
    assert r.status_code == 400


def test_download_with_dir(client, help_sample_dir: Path) -> None:
    from onec_help.web import app

    app.config["BASE_DIR"] = str(help_sample_dir)
    r = client.get("/download/field626.html")
    assert r.status_code == 200


def test_security_headers_present(client) -> None:
    """Response includes security headers from after_request."""
    r = client.get("/ready")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers


def test_allowed_base_dirs_empty() -> None:
    """When HELP_SERVE_ALLOWED_DIRS is unset or empty, _allowed_base_dirs returns empty list."""
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": ""}, clear=False):
        assert _allowed_base_dirs() == []


def test_allowed_base_dirs_from_env(tmp_path: Path) -> None:
    """When HELP_SERVE_ALLOWED_DIRS is set, returns resolved paths."""
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(tmp_path)}):
        result = _allowed_base_dirs()
    assert len(result) == 1
    assert result[0] == tmp_path.resolve()


def test_directory_allowed_empty_allowlist_blocks(tmp_path: Path) -> None:
    """When no allowed dirs set, any directory is rejected (security: require allowlist)."""
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": ""}, clear=False):
        assert _directory_allowed(str(tmp_path)) is False


def test_directory_allowed_inside_list(tmp_path: Path, help_sample_dir: Path) -> None:
    """Directory under allowed base is allowed."""
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(tmp_path)}):
        assert _directory_allowed(str(help_sample_dir)) is False
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(help_sample_dir.parent)}):
        assert _directory_allowed(str(help_sample_dir)) is True


def test_directory_allowed_resolve_error(tmp_path: Path) -> None:
    """When Path(directory).resolve() raises, _directory_allowed returns False."""
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(allowed_dir)}):
        with patch("onec_help.web.Path") as MockPath:
            from pathlib import Path as RealPath

            def path_side_effect(p):
                if p == "/nonexistent_bad_path":
                    m = MagicMock()
                    m.resolve.side_effect = OSError("resolve failed")
                    return m
                return RealPath(p)

            MockPath.side_effect = path_side_effect
            assert _directory_allowed("/nonexistent_bad_path") is False


def test_index_post_directory_not_in_allowed_list(
    client, help_sample_dir: Path, tmp_path: Path
) -> None:
    """POST with directory outside HELP_SERVE_ALLOWED_DIRS returns error."""
    other = tmp_path / "other"
    other.mkdir()
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(other)}):
        r = client.post("/", data={"directory": str(help_sample_dir)})
    assert r.status_code == 200
    assert b"allowed" in r.data or b"HELP_SERVE" in r.data


def test_index_post_directory_in_allowed_list(client, help_sample_dir: Path) -> None:
    """POST with directory inside HELP_SERVE_ALLOWED_DIRS succeeds."""
    with patch.dict(os.environ, {"HELP_SERVE_ALLOWED_DIRS": str(help_sample_dir.parent)}):
        r = client.post("/", data={"directory": str(help_sample_dir)})
    assert r.status_code == 200
    assert b"Invalid" not in r.data or b"tree" in r.data


def test_api_search_empty_query(client) -> None:
    """GET /api/search with no q returns empty results."""
    r = client.get("/api/search")
    assert r.status_code == 200
    data = r.get_json()
    assert data["results"] == []
    assert data.get("error") is None


def test_api_search_empty_q_param(client) -> None:
    """GET /api/search?q= returns empty results."""
    r = client.get("/api/search?q=")
    assert r.status_code == 200
    assert r.get_json()["results"] == []


def test_api_search_success(client) -> None:
    """GET /api/search?q=... calls search_hybrid and returns results."""
    mock_results = [{"path": "obj/method.html", "title": "Метод.Вызвать", "text": "snippet"}]
    with patch("onec_help.indexer.search_hybrid", return_value=mock_results):
        r = client.get("/api/search?q=Вызвать")
    assert r.status_code == 200
    data = r.get_json()
    assert data["error"] is None
    assert len(data["results"]) == 1
    assert data["results"][0]["title"] == "Метод.Вызвать"
    assert data["results"][0]["path"] == "obj/method.html"


def test_api_search_exception(client) -> None:
    """GET /api/search on exception returns 500."""
    with patch("onec_help.indexer.search_hybrid", side_effect=RuntimeError("Qdrant down")):
        r = client.get("/api/search?q=test")
    assert r.status_code == 500
    data = r.get_json()
    assert "error" in data
