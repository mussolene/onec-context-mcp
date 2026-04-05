#!/usr/bin/env python3
"""Split/stitch 1C ordinary form ``Ext/Form.bin`` (module BSL + brace-tree form in one container).

Layout (observed on MetadataExport EPF XML dump, 8.3.2x): after magic ``FFFF FF7F 0002...``
comes a chain of segments. Most use::

    \\r\\n<8-hex> <8-hex> 7fffffff \\r\\n
    <payload>

If both hex fields are equal, that value is the payload byte length. The first segment is
special: the fields differ; the second hex is the total byte span from the end of the header
line to the start of the next header (e.g. 0x200).

UTF-8 chunks with BOM embed the form module (BSL) and the textual form description ``{...}``.

Usage::

  python form_bin_tool.py split <Form.bin> <out_dir>
  python form_bin_tool.py join <out_dir> <Form.bin>

Edit ``out_dir/Module.bsl`` and/or ``out_dir/Form.stream.txt``, then ``join``. Other
``segment_XX.bin`` and ``preamble.bin`` must stay unchanged unless you know the binary layout.

Other platform builds may use a different layout — if ``join`` fails, compare manifests.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HDR_RE = re.compile(rb"\r\n([0-9a-f]{8}) ([0-9a-f]{8}) 7fffffff \r\n", re.IGNORECASE)
UTF8_BOM = b"\xef\xbb\xbf"


def _parse_segments(data: bytes) -> list[dict]:
    segs: list[dict] = []
    pos = 0
    if len(data) >= 4 and data[:4] == b"\xff\xff\xff\x7f":
        pos = 16
    while pos < len(data):
        m = HDR_RE.match(data, pos)
        if not m:
            raise ValueError(f"No chunk header at offset {pos}")
        a = int(m.group(1), 16)
        b = int(m.group(2), 16)
        h_start, h_end = m.start(), m.end()
        if a == b:
            p_end = h_end + a
            if p_end > len(data):
                raise ValueError(f"Payload overflow at {h_end}: need {a} bytes")
            payload = data[h_end:p_end]
            kind = "paired"
            nxt = p_end
        else:
            p_end = h_end + b
            if p_end > len(data):
                raise ValueError(f"Span overflow at {h_end}: need {b} bytes")
            payload = data[h_end:p_end]
            kind = "span"
            nxt = p_end
        segs.append(
            {
                "kind": kind,
                "header_at": h_start,
                "header_end": h_end,
                "hex_a": a,
                "hex_b": b,
                "payload_start": h_end,
                "payload_end": p_end,
                "next_offset": nxt,
                "payload": payload,
            }
        )
        pos = nxt
    return segs


def _classify_payload(payload: bytes) -> str:
    if not payload.startswith(UTF8_BOM):
        return "binary"
    head = payload[:2048]
    if head.startswith(UTF8_BOM + b"{") or (len(head) > 3 and head[3:20].lstrip().startswith(b"{")):
        return "form_utf8"
    proc_ru = "\u041f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u0430".encode()
    func_ru = "\u0424\u0443\u043d\u043a\u0446\u0438\u044f".encode()
    if proc_ru in head or func_ru in head or b"Procedure" in head or b"Function" in head:
        return "module_bsl"
    return "utf8_unknown"


def _fmt_header_paired(length: int) -> bytes:
    h = f"{length:08x}"
    return f"\r\n{h} {h} 7fffffff \r\n".encode("ascii")


def _fmt_header_span(a: int, b: int) -> bytes:
    return f"\r\n{a:08x} {b:08x} 7fffffff \r\n".encode("ascii")


def cmd_split(form_bin: Path, out_dir: Path) -> None:
    data = form_bin.read_bytes()
    segs = _parse_segments(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    first_hdr = segs[0]["header_at"]
    (out_dir / "preamble.bin").write_bytes(data[:first_hdr])
    manifest: dict = {
        "source": str(form_bin),
        "size": len(data),
        "preamble_len": first_hdr,
        "module_segment": None,
        "form_segment": None,
        "segments": [],
    }
    for i, s in enumerate(segs):
        pl = s["payload"]
        cls = _classify_payload(pl) if s["kind"] == "paired" else "binary_span"
        manifest["segments"].append(
            {
                "index": i,
                "kind": s["kind"],
                "hex_a": s["hex_a"],
                "hex_b": s["hex_b"],
                "class": cls,
            }
        )
        if cls == "module_bsl":
            manifest["module_segment"] = i
            (out_dir / "Module.bsl").write_bytes(pl[len(UTF8_BOM) :])
        elif cls == "form_utf8":
            manifest["form_segment"] = i
            (out_dir / "Form.stream.txt").write_bytes(pl[len(UTF8_BOM) :])
        else:
            (out_dir / f"segment_{i:02d}.bin").write_bytes(pl)
    if manifest["module_segment"] is None or manifest["form_segment"] is None:
        raise SystemExit(
            f"Could not classify module ({manifest['module_segment']!r}) "
            f"or form ({manifest['form_segment']!r}). Inspect segment files."
        )
    (out_dir / "form.bin.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_dir} (preamble.bin, Module.bsl, Form.stream.txt, segment_*.bin, manifest)")


def cmd_join(out_dir: Path, dest: Path) -> None:
    man = json.loads((out_dir / "form.bin.manifest.json").read_text(encoding="utf-8"))
    preamble = (out_dir / "preamble.bin").read_bytes()
    mod = UTF8_BOM + (out_dir / "Module.bsl").read_bytes()
    form = UTF8_BOM + (out_dir / "Form.stream.txt").read_bytes()
    out = bytearray(preamble)
    for i, ent in enumerate(man["segments"]):
        cls = ent["class"]
        if cls == "module_bsl":
            out.extend(_fmt_header_paired(len(mod)))
            out.extend(mod)
        elif cls == "form_utf8":
            out.extend(_fmt_header_paired(len(form)))
            out.extend(form)
        else:
            raw = (out_dir / f"segment_{i:02d}.bin").read_bytes()
            if ent["kind"] == "paired":
                out.extend(_fmt_header_paired(len(raw)))
            else:
                out.extend(_fmt_header_span(ent["hex_a"], ent["hex_b"]))
            out.extend(raw)
    dest.write_bytes(out)
    _parse_segments(bytes(out))
    print(f"Wrote {dest} ({len(out)} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Split/join 1C ordinary Form.bin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("split", help="Form.bin -> directory")
    sp.add_argument("form_bin", type=Path)
    sp.add_argument("out_dir", type=Path)
    sp.set_defaults(func=lambda a: cmd_split(a.form_bin, a.out_dir))
    jp = sub.add_parser("join", help="directory -> Form.bin")
    jp.add_argument("out_dir", type=Path)
    jp.add_argument("dest", type=Path)
    jp.set_defaults(func=lambda a: cmd_join(a.out_dir, a.dest))
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
