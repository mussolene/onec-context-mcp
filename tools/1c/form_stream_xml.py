#!/usr/bin/env python3
"""Lossless tokenization of 1C ordinary form ``Form.stream.txt`` (brace tree) ↔ XML.

The stream is *not* the same schema as managed ``Form.xml`` (lf:logform). This tool only
preserves the platform's internal serialization so you can edit in XML-aware tools and
round-trip without changing semantics at the parser level.

Special case: ``{#base64:...}`` blocks can contain ``/`` runs and stray characters that would
break naive comma-separated parsing; the tokenizer treats each such block as one atomic token.

Usage::

  python form_stream_xml.py to-xml Form.stream.txt Form.stream.xml
  python form_stream_xml.py from-xml Form.stream.xml Form.stream.out.txt
  python form_stream_xml.py check Form.stream.txt   # tokenize+detokenize, exit 1 if mismatch

Requires Python 3.10+.
"""

from __future__ import annotations

import argparse
import base64
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

def tokenize(s: str) -> list[str]:
    """Split stream into losslessly joinable tokens."""
    n = len(s)
    i = 0
    out: list[str] = []

    def consume_base64_block(start: int) -> tuple[str, int]:
        """From ``start`` at ``{``, return (full text including braces, index after)."""
        depth = 0
        j = start
        assert s[j] == "{"
        depth = 1
        j += 1
        while j < n and depth:
            c = s[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        return s[start:j], j

    while i < n:
        c = s[i]
        if c in "{},":  # noqa: PLR6201
            if c == "{" and s.startswith("{#base64:", i):
                blob, j = consume_base64_block(i)
                out.append(blob)
                i = j
                continue
            out.append(c)
            i += 1
            continue
        if c in " \t\r\n":
            j = i
            while j < n and s[j] in " \t\r\n":
                j += 1
            out.append(s[i:j])
            i = j
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if s[j] == '"' and s[j - 1] != "\\":
                    j += 1
                    break
                j += 1
            out.append(s[i:j])
            i = j
            continue
        j = i
        while j < n and s[j] not in "{},\r\n\t ":
            j += 1
        out.append(s[i:j])
        i = j
    return out


def detokenize(tokens: list[str]) -> str:
    return "".join(tokens)


def tokens_to_xml(tokens: list[str], root_tag: str = "FormStream") -> str:
    """Serialize tokens to XML (one element per token).

    Non-punct tokens use a ``b64`` attribute (UTF-8 base64) so ``\\r\\n`` survives parsing:
    ElementTree normalizes newlines in element text and CDATA.
    """
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<{root_tag} xmlns="urn:1c:form-stream:tokens">',
    ]
    for i, tok in enumerate(tokens):
        tid = f"t{i}"
        if tok in "{},":  # noqa: PLR6201
            parts.append(f'<punct id="{tid}">{escape(tok, {"'": "&apos;"})}</punct>')
        else:
            b64 = base64.b64encode(tok.encode("utf-8")).decode("ascii")
            kind = "ws" if tok.isspace() else "tok"
            parts.append(f'<{kind} id="{tid}" b64="{b64}"/>')
    parts.append(f"</{root_tag}>")
    return "\n".join(parts) + "\n"


def xml_to_tokens(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    base = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if base != "FormStream":
        raise ValueError(f"unexpected root {root.tag!r}")
    tokens: list[str] = []
    for el in root:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "punct":
            tokens.append(el.text or "")
        elif tag in ("ws", "tok"):
            b64 = el.attrib.get("b64")
            if not b64:
                raise ValueError(f"missing b64 on {tag} id={el.attrib.get('id')!r}")
            tokens.append(base64.b64decode(b64).decode("utf-8"))
        else:
            raise ValueError(f"unknown element {el.tag!r}")
    return tokens


def _read_utf8_exact(path: Path) -> str:
    """Read UTF-8 without newline translation (preserve ``\\r\\n`` in Form.stream)."""
    return path.read_bytes().decode("utf-8")


def _write_utf8_exact(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def cmd_to_xml(src: Path, dest: Path) -> None:
    text = _read_utf8_exact(src)
    toks = tokenize(text)
    dest.write_bytes(tokens_to_xml(toks).encode("utf-8"))
    print(f"{len(toks)} tokens → {dest}")


def cmd_from_xml(src: Path, dest: Path) -> None:
    xml_text = _read_utf8_exact(src)
    toks = xml_to_tokens(xml_text)
    out = detokenize(toks)
    _write_utf8_exact(dest, out)
    print(f"wrote {dest} ({len(out.encode('utf-8'))} UTF-8 bytes)")


def cmd_check(path: Path) -> int:
    text = _read_utf8_exact(path)
    toks = tokenize(text)
    back = detokenize(toks)
    if back != text:
        print("MISMATCH", len(text), len(back), file=sys.stderr)
        for k in range(min(len(back), len(text))):
            if back[k] != text[k]:
                print("at", k, repr(text[k : k + 40]), repr(back[k : k + 40]), file=sys.stderr)
                break
        return 1
    print(f"OK {len(toks)} tokens, {len(text.encode('utf-8'))} UTF-8 bytes")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Form.stream.txt ↔ lossless token XML")
    sub = ap.add_subparsers(dest="cmd", required=True)
    tx = sub.add_parser("to-xml", help="text → XML")
    tx.add_argument("src", type=Path)
    tx.add_argument("dest", type=Path)
    fx = sub.add_parser("from-xml", help="XML → text")
    fx.add_argument("src", type=Path)
    fx.add_argument("dest", type=Path)
    ck = sub.add_parser("check", help="verify tokenize round-trip")
    ck.add_argument("path", type=Path)
    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(cmd_check(args.path))
    if args.cmd == "to-xml":
        cmd_to_xml(args.src, args.dest)
    else:
        cmd_from_xml(args.src, args.dest)


if __name__ == "__main__":
    main()
