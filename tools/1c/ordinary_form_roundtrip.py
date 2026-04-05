#!/usr/bin/env python3
"""Ordinary form: ``Form.bin`` ↔ editable text (module + form stream) for teams and CI.

Intent (аналогично идее дизайнера с сохранением документа): снять **текстовый снимок**
модуля и внутреннего потока формы, править в Git/diff, собрать контейнер обратно.

Слои:
  * ``form_bin_tool`` — контейнер (сегменты, BOM, длины);
  * ``form_stream_xml`` (опционально) — поток → lossless token XML для IDE/агентов.

Examples::

  python3 ordinary_form_roundtrip.py extract Forms/MyForm/Ext ./out/myform_text
  python3 ordinary_form_roundtrip.py extract Forms/MyForm/Ext ./out/myform_text --token-xml
  python3 ordinary_form_roundtrip.py pack ./out/myform_text Forms/MyForm/Ext/Form.bin
  python3 ordinary_form_roundtrip.py verify Forms/MyForm/Ext/Form.bin
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent


def _load_helpers():
    """Import sibling scripts as modules (no installed package)."""
    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))
    import form_bin_tool as form_bin_tool  # noqa: PLC0415
    import form_stream_xml as form_stream_xml  # noqa: PLC0415

    return form_bin_tool, form_stream_xml


def resolve_form_bin(path: Path) -> Path:
    """``Form.bin`` or directory ``Ext`` containing it."""
    if path.is_file() and path.name == "Form.bin":
        return path
    if path.is_dir():
        cand = path / "Form.bin"
        if cand.is_file():
            return cand
    raise SystemExit(f"Not found: Form.bin at {path} or {path}/Form.bin")


def cmd_extract(args: argparse.Namespace) -> None:
    fbt, fsx = _load_helpers()
    form_bin = resolve_form_bin(args.source)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    fbt.cmd_split(form_bin, out_dir)
    if args.copy_original:
        shutil.copy2(form_bin, out_dir / "Form.bin.original")
    if args.token_xml:
        st = out_dir / "Form.stream.txt"
        xml_path = out_dir / "Form.stream.tokens.xml"
        text = st.read_bytes().decode("utf-8")
        toks = fsx.tokenize(text)
        xml_path.write_bytes(fsx.tokens_to_xml(toks).encode("utf-8"))
        print(f"Wrote {xml_path} ({len(toks)} tokens)")
    marker = out_dir / ".ordinary_form_export.txt"
    marker.write_text(
        "Exported by tools/1c/ordinary_form_roundtrip.py extract.\n"
        "Edit Module.bsl and Form.stream.txt; then: pack this dir → Form.bin\n"
        "Docs: docs/reference/ordinary-form-text-roundtrip.md\n",
        encoding="utf-8",
    )
    print(f"Marker {marker}")


def cmd_pack(args: argparse.Namespace) -> None:
    fbt, fsx = _load_helpers()
    d = args.dir
    if not (d / "form.bin.manifest.json").is_file():
        raise SystemExit(f"Missing {d / 'form.bin.manifest.json'} — not an extract directory?")
    dest: Path = args.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if args.from_token_xml:
        xml_path = d / "Form.stream.tokens.xml"
        out_stream = d / "Form.stream.txt"
        if not xml_path.is_file():
            raise SystemExit(f"--from-token-xml requires {xml_path}")
        fsx.cmd_from_xml(xml_path, out_stream)
        print(f"Regenerated {out_stream} from {xml_path}")
    fbt.cmd_join(d, dest)


def cmd_verify(args: argparse.Namespace) -> int:
    fbt, fsx = _load_helpers()
    form_bin = resolve_form_bin(args.source)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        fbt.cmd_split(form_bin, tdp)
        rebuilt = tdp / "rebuilt.bin"
        fbt.cmd_join(tdp, rebuilt)
        a = form_bin.read_bytes()
        b = rebuilt.read_bytes()
        if a != b:
            print(
                f"VERIFY FAIL: {form_bin} != round-trip ({len(a)} vs {len(b)} bytes)",
                file=sys.stderr,
            )
            return 1
        if args.with_stream_tokens:
            rc = fsx.cmd_check(tdp / "Form.stream.txt")
            if rc != 0:
                print("VERIFY FAIL: Form.stream token round-trip", file=sys.stderr)
                return rc
    print(f"VERIFY OK {form_bin}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ordinary Form.bin ↔ text (module + stream) for team workflow",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="Form.bin or Ext/ → directory with text + binary segments")
    ex.add_argument("source", type=Path, help="Path to Form.bin or to Ext/ containing it")
    ex.add_argument("out_dir", type=Path, help="Output directory (created)")
    ex.add_argument(
        "--token-xml",
        action="store_true",
        help="Also write Form.stream.tokens.xml (lossless; edit via from-xml workflow)",
    )
    ex.add_argument(
        "--copy-original",
        action="store_true",
        help="Copy source Form.bin to Form.bin.original in out_dir",
    )
    ex.set_defaults(func=cmd_extract)

    pk = sub.add_parser("pack", help="Extract directory → Form.bin")
    pk.add_argument("dir", type=Path, help="Directory from extract (has form.bin.manifest.json)")
    pk.add_argument("dest", type=Path, help="Output Form.bin path")
    pk.add_argument(
        "--from-token-xml",
        action="store_true",
        help="Rebuild Form.stream.txt from Form.stream.tokens.xml before join",
    )
    pk.set_defaults(func=cmd_pack)

    vf = sub.add_parser("verify", help="split→join byte identity (+ optional stream token check)")
    vf.add_argument("source", type=Path, help="Form.bin or Ext/")
    vf.add_argument(
        "--with-stream-tokens",
        action="store_true",
        help="Also run form_stream_xml check on extracted stream",
    )
    vf.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    if args.cmd == "verify":
        sys.exit(args.func(args))
    args.func(args)


if __name__ == "__main__":
    main()
