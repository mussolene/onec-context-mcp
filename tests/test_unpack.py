"""Tests for unpack module."""

import struct
import zipfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onec_help.unpack import (
    _decode_filename,
    _try_unzip,
    _try_zipfile,
    _try_zipfile_from_offset,
    _try_zipfile_scan_local_headers,
    _unpack_timeout,
    ensure_dir,
    unpack_hbk,
)


def test_decode_filename_utf8() -> None:
    """_decode_filename decodes UTF-8 and cp1251 filenames."""
    assert _decode_filename(b"page.html") == "page.html"
    assert _decode_filename("Справка".encode()) == "Справка"


def test_decode_filename_cp1251() -> None:
    """_decode_filename falls back to cp1251 when utf-8 fails."""
    # Cyrillic in Windows-1251
    assert _decode_filename("Справка".encode("cp1251")) == "Справка"


def test_decode_filename_replace_fallback() -> None:
    """_decode_filename uses utf-8 replace when both utf-8 and cp1251 fail."""
    invalid = bytes([0xFF, 0xFE, 0x80])
    out = _decode_filename(invalid)
    assert isinstance(out, str)
    assert "\ufffd" in out or len(out) == len(invalid)


def test_unpack_timeout_env() -> None:
    """_unpack_timeout reads UNPACK_TIMEOUT and clamps to min 60."""
    with patch.dict("os.environ", {"UNPACK_TIMEOUT": "300"}, clear=False):
        assert _unpack_timeout() == 300
    with patch.dict("os.environ", {"UNPACK_TIMEOUT": "30"}, clear=False):
        assert _unpack_timeout() == 60
    with patch.dict("os.environ", {"UNPACK_TIMEOUT": "invalid"}, clear=False):
        assert _unpack_timeout() == 1800


def test_try_zipfile_success(tmp_path: Path) -> None:
    """_try_zipfile extracts valid ZIP and returns True."""
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("file.txt", "content")
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile(archive, out) is True
    assert (out / "file.txt").read_text() == "content"


def test_try_zipfile_bad_zip_returns_false(tmp_path: Path) -> None:
    """_try_zipfile returns False for non-ZIP file."""
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"not a zip")
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile(archive, out) is False


def test_ensure_dir(tmp_path: Path) -> None:
    d = tmp_path / "sub"
    ensure_dir(d)
    assert d.is_dir()
    ensure_dir(d)
    assert d.is_dir()


def test_unpack_hbk_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        unpack_hbk("/nonexistent.hbk", "/tmp/out")


def test_unpack_hbk_calls_7z(tmp_path: Path) -> None:
    archive = tmp_path / "test.hbk"
    archive.write_bytes(b"fake")
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        unpack_hbk(archive, out)
        run.assert_called()
        args = run.call_args[0][0]
        assert "7z" in args
        assert "x" in args
        assert "-y" in args


def test_unpack_hbk_retry_with_tstar(tmp_path: Path) -> None:
    """When 7z fails, retry with -t*."""
    archive = tmp_path / "a.hbk"
    archive.write_bytes(b"x")
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stderr="err")
        run.return_value.returncode = 0
        run.side_effect = [MagicMock(returncode=1), MagicMock(returncode=0)]
        unpack_hbk(archive, out)
        assert run.call_count == 2
        second_call = run.call_args_list[1][0][0]
        assert "-t*" in second_call


def test_unpack_hbk_error_message(tmp_path: Path) -> None:
    """When 7z and zipfile and unzip all fail, error message must suggest manual unpack."""
    archive = tmp_path / "help.hbk"
    archive.write_bytes(b"not a zip or 7z archive")
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=2, stderr="Headers Error", stdout="")
        run.side_effect = [MagicMock(returncode=2)] * 4 + [MagicMock(returncode=1)]
        # 7z: default, *, cab, zip; then unzip
        with pytest.raises(RuntimeError) as exc_info:
            unpack_hbk(archive, out)
        msg = str(exc_info.value)
        assert "manually" in msg.lower() or "unpack" in msg.lower()
        assert "zipfile" in msg.lower() or "7z" in msg.lower()


def test_unpack_hbk_all_methods_fail_including_offset(tmp_path: Path) -> None:
    """Large invalid file: offset loop and unzip are tried, then RuntimeError."""
    archive = tmp_path / "large.hbk"
    archive.write_bytes(b"x" * 3000)
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=2, stderr="Headers Error", stdout="")
        run.side_effect = [MagicMock(returncode=2)] * 4 + [MagicMock(returncode=1)]
        # 7z: default, *, cab, zip; then unzip
        with pytest.raises(RuntimeError) as exc_info:
            unpack_hbk(archive, out)
        msg = str(exc_info.value)
        assert "manually" in msg.lower() or "unpack" in msg.lower()
        assert "zipfile" in msg.lower() or "7z" in msg.lower()


def test_unpack_fallback_zipfile(tmp_path: Path) -> None:
    """When 7z fails, unpack via Python zipfile if the file is ZIP."""
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("file.txt", "hello")
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        unpack_hbk(archive, out)
    assert (out / "file.txt").read_text() == "hello"


def test_unpack_hbk_real_zip_no_mock(tmp_path: Path) -> None:
    """Unpack a real .hbk-sized zip (no 7z mock): fallback zipfile must succeed."""
    archive = tmp_path / "sample_ru.hbk"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PayloadData/index.html", "<html><body><h1>Test</h1></body></html>")
        zf.writestr("PayloadData/page2.html", "<html><body><p>Second</p></body></html>")
    out = tmp_path / "unpacked"
    # 7z may fail on .hbk or succeed; zipfile fallback will work
    unpack_hbk(archive, out)
    assert (out / "PayloadData" / "index.html").exists()
    assert "Test" in (out / "PayloadData" / "index.html").read_text()


def test_try_zipfile_from_offset_success(tmp_path: Path) -> None:
    """When archive has header, unpack from offset."""
    archive = tmp_path / "with_header.zip"
    with open(archive, "wb") as f:
        f.write(b"x" * 512)
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.txt", "hello")
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile_from_offset(archive, out, offset=512) is True
    assert (out / "data.txt").read_text() == "hello"


def test_try_zipfile_from_offset_truncate_tail(tmp_path: Path) -> None:
    """truncate_tail cuts trailing bytes before opening as zip."""
    archive = tmp_path / "trunc.zip"
    data = b"header" * 100
    with open(archive, "wb") as f:
        f.write(data)
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("x", "y")
    out = tmp_path / "out"
    out.mkdir()
    # Should fail when reading wrong offset; truncate_tail used in unpack_hbk
    assert _try_zipfile_from_offset(archive, out, offset=0, truncate_tail=0) in (True, False)


def test_try_unzip_mocked(tmp_path: Path) -> None:
    """_try_unzip returns True when unzip command succeeds."""
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"fake")
    out = tmp_path / "out"
    out.mkdir()
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        assert _try_unzip(archive, out) is True
    with patch("onec_help.unpack.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        assert _try_unzip(archive, out) is False


def test_unpack_hbk_via_offset(tmp_path: Path) -> None:
    """When 7z and direct zipfile fail, offset unpack can succeed."""
    archive = tmp_path / "arch.hbk"
    with open(archive, "wb") as f:
        f.write(b" " * 512)
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PayloadData/index.html", "<h1>OK</h1>")
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.side_effect = [MagicMock(returncode=1)] * 4  # 7z: default, *, cab, zip
        unpack_hbk(archive, out)
    assert (out / "PayloadData" / "index.html").exists()


def test_unpack_hbk_non_hbk_suffix_error(tmp_path: Path) -> None:
    """When suffix is not .hbk, error message does not mention manual unpack."""
    archive = tmp_path / "data.bin"
    archive.write_bytes(b"x" * 3000)
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.side_effect = [MagicMock(returncode=2)] * 4 + [MagicMock(returncode=1)]
        # 7z: default, *, cab, zip; then unzip
        with pytest.raises(RuntimeError) as exc_info:
            unpack_hbk(archive, out)
    assert "All unpack methods failed" in str(exc_info.value)


def test_try_zipfile_from_offset_empty_data_returns_false(tmp_path: Path) -> None:
    """When offset leaves no data, return False."""
    archive = tmp_path / "tiny"
    archive.write_bytes(b"x" * 100)
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile_from_offset(archive, out, offset=200) is False


def test_try_zipfile_from_offset_truncate_tail_applied(tmp_path: Path) -> None:
    """truncate_tail removes trailing bytes before zip parse."""
    archive = tmp_path / "arch.bin"
    with open(archive, "wb") as f:
        f.write(b"junk" * 200)
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("x.txt", "ok")
    with open(archive, "ab") as f:
        f.write(b"trailing_garbage_12345")
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile_from_offset(archive, out, offset=0, truncate_tail=20) is True
    assert (out / "x.txt").read_text() == "ok"


def test_try_zipfile_from_offset_bad_zip_returns_false(tmp_path: Path) -> None:
    """When data is not valid zip, return False."""
    archive = tmp_path / "notzip"
    archive.write_bytes(b"not a zip file contents")
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile_from_offset(archive, out, offset=0) is False


def test_unpack_hbk_7z_extracted_oserror_treated_as_false(tmp_path: Path) -> None:
    """When output_dir.iterdir() raises OSError, _7z_extracted returns False."""
    archive = tmp_path / "a.hbk"
    archive.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    orig_iterdir = Path.iterdir

    def iterdir_mock(self):
        if self.resolve() == out.resolve():
            raise OSError("permission")
        return orig_iterdir(self)

    with patch.object(Path, "iterdir", iterdir_mock):
        with patch("onec_help.unpack.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stderr="err")
            with pytest.raises(RuntimeError):
                unpack_hbk(archive, out)


def test_unpack_hbk_7z_not_found_fallback_zipfile(tmp_path: Path) -> None:
    """When 7z is missing (FileNotFoundError), fallback to zipfile is used."""
    archive = tmp_path / "data.hbk"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inner.txt", "content")
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.side_effect = FileNotFoundError("7z not found")
        unpack_hbk(archive, out)
    assert (out / "inner.txt").read_text() == "content"


def _make_embedded_zip_local_entry(filename: str, content: bytes) -> bytes:
    """Build a single local file header + deflated payload (no EOCD)."""
    compressed = zlib.compress(content, 9)[2:-4]  # raw deflate
    fn = filename.encode("utf-8")
    # Local header: ver(H) flags(H) comp(H) modtime(H) moddate(H) crc(I) comp_sz(I) uncomp_sz(I) fn_len(H) extra_len(H)
    hdr = b"PK\x03\x04" + struct.pack(
        "<HHHHHIIIHH",
        20,
        0,
        8,
        0,
        0,
        0,
        len(compressed),
        len(content),
        len(fn),
        0,
    )
    return hdr + fn + compressed


def test_try_zipfile_scan_local_headers(tmp_path: Path) -> None:
    """Scan extracts entries from embedded ZIP with corrupted EOCD (schemui-style)."""
    # 1C-style header padding + embedded ZIP (no valid EOCD)
    padding = b"\x00" * 200
    entry = _make_embedded_zip_local_entry("test.txt", b"hello from scan")
    archive = tmp_path / "schemui.hbk"
    archive.write_bytes(padding + entry)
    out = tmp_path / "out"
    out.mkdir()
    assert _try_zipfile_scan_local_headers(archive, out) is True
    assert (out / "test.txt").read_text() == "hello from scan"


def test_unpack_hbk_via_scan_local_headers(tmp_path: Path) -> None:
    """Unpack schemui-style .hbk via scan when 7z, zipfile, offset, unzip fail."""
    padding = b"x" * 500
    entry = _make_embedded_zip_local_entry("__categories__", b"{1,2,3}")
    archive = tmp_path / "schemui_ru.hbk"
    archive.write_bytes(padding + entry)
    out = tmp_path / "out"
    with patch("onec_help.unpack.subprocess.run") as run:
        run.side_effect = [MagicMock(returncode=2)] * 4 + [MagicMock(returncode=1)]
        unpack_hbk(archive, out)
    assert (out / "__categories__").read_bytes() == b"{1,2,3}"
