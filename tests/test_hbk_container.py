"""Tests for HBK binary container reader (source: alkoleft/hbk-viewer)."""

import struct
from pathlib import Path

import pytest

from onec_help.hbk_container import (
    read_block_chain,
    read_block_header,
    read_container,
    read_container_from_path,
    read_container_header,
)


def test_read_container_header() -> None:
    """Container header: 16 bytes, 4 x INT32 LE."""
    # free_block=0, default_size=256, unknown=3, reserved=0
    data = b"\x00\x00\x00\x00\x00\x01\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00"
    a, b, c, d = read_container_header(data)
    assert a == 0
    assert b == 256
    assert c == 3
    assert d == 0


def test_read_container_header_too_short() -> None:
    """Too short data raises ValueError."""
    with pytest.raises(ValueError, match="shorter than container header"):
        read_container_header(b"\x00" * 8)


def test_read_block_header() -> None:
    """Block header: CRLF + 8 hex payload + space + 8 hex block + space + 8 hex next + space + CRLF."""
    # payload=256, block=256, next=0xFFFFFFFF
    data = (
        b"\x0d\x0a"
        b"00000100"  # payload_size
        b" "
        b"00000100"  # block_size
        b" "
        b"FFFFFFFF"  # next_block
        b" \x0d\x0a"
    )
    payload, block, next_b, consumed = read_block_header(data, 0)
    assert payload == 256
    assert block == 256
    assert (next_b & 0xFFFFFFFF) == 0xFFFFFFFF
    assert consumed == 31


def test_read_block_chain_single_block() -> None:
    """Single block chain returns payload bytes."""
    # 31 bytes header (payload=10, block=10, next=FFFFFFFF) + 10 bytes content
    header = b"\x0d\x0a0000000a 0000000a FFFFFFFF \x0d\x0a"
    content = b"1234567890"
    data = header + content
    result = read_block_chain(data, 0)
    assert result == content


def test_read_container_empty_toc() -> None:
    """Container with empty TOC (no FileInfo entries) returns empty dict."""
    # 16 bytes container header
    header = struct.pack("<iiii", 0, 256, 0, 0)
    # TOC block: 31 bytes block header (payload=0, block=0, next=FFFFFFFF) + 0 bytes
    toc_header = b"\x0d\x0a00000000 00000000 FFFFFFFF \x0d\x0a"
    data = header + toc_header
    entities = read_container(data)
    assert entities == {}


def test_read_container_from_path_not_found(tmp_path: Path) -> None:
    """read_container_from_path raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError, match="not found"):
        read_container_from_path(tmp_path / "nonexistent.hbk")


def test_read_container_too_short() -> None:
    """read_container on too short data raises ValueError."""
    with pytest.raises(ValueError, match="too short"):
        read_container(b"\x00" * 10)
