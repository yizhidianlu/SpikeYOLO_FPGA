#!/usr/bin/env python3
"""extract_api_signatures.py — parse spike_accel.h and emit a JSON ABI fence.

Why this exists
---------------
Real `abidiff` (libabigail) is not available on Windows / MinGW dev hosts and
the M3 sprint is when we'll finally have it wired into CI. Until then we want
*some* future-proof artefact that locks the v1.1.0 surface so any later
breaking edit (reordered struct field, deleted function, changed return type,
silently widened enum) shows up as a diff against this JSON.

Output schema (stable, do not break)
------------------------------------
{
  "version": "1.1.0",
  "source_header": "sw/sdk/include/spike_accel.h",
  "sha256": "<sha of the parsed header>",
  "macros":   [{"name": str, "value": str}],
  "enums":    [{"name": str, "values": [{"name": str, "value": str}]}],
  "structs":  [{"name": str, "fields": [{"type": str, "name": str}]}],
  "typedefs": [{"name": str, "underlying": str}],
  "functions":[{"name": str, "return": str, "args": [{"type": str, "name": str}],
                "doc": str}]
}

Usage
-----
    python extract_api_signatures.py \
        ../include/spike_accel.h \
        v1.1.0_api_signatures.json

To diff a future header against the locked baseline:
    python extract_api_signatures.py ../include/spike_accel.h /tmp/new.json
    diff -u v1.1.0_api_signatures.json /tmp/new.json

Any non-zero diff on a non-major release == policy violation.
"""

import hashlib
import json
import re
import sys
from pathlib import Path


_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_DOC_BLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)


def _strip_comments(src: str) -> str:
    src = _BLOCK_COMMENT.sub(" ", src)
    src = _LINE_COMMENT.sub(" ", src)
    return src


def _normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_macros(src: str):
    out = []
    for m in re.finditer(r"#\s*define\s+(SA_[A-Z0-9_]+)\s+([^\n]+)", src):
        name = m.group(1)
        value = m.group(2).strip()
        # drop trailing inline comments (already stripped by caller but safe)
        out.append({"name": name, "value": value})
    return out


def parse_enums(src: str):
    out = []
    for m in re.finditer(
        r"typedef\s+enum\s+(\w+)\s*\{([^}]+)\}\s*(\w+)\s*;", src, re.DOTALL
    ):
        body = m.group(2)
        values = []
        for line in body.split(","):
            line = line.strip()
            if not line:
                continue
            if "=" in line:
                n, v = [p.strip() for p in line.split("=", 1)]
            else:
                n, v = line, ""
            values.append({"name": n, "value": v})
        out.append({"name": m.group(3), "values": values})
    return out


def parse_structs(src: str):
    out = []
    for m in re.finditer(
        r"typedef\s+struct\s+\w*\s*\{([^}]+)\}\s*(\w+)\s*;", src, re.DOTALL
    ):
        body = m.group(1)
        fields = []
        for raw in body.split(";"):
            raw = _normalise_ws(raw)
            if not raw:
                continue
            # last token is the field name (handles `uint8_t _pad[3]` too)
            tokens = raw.split(" ")
            name = tokens[-1]
            ctype = " ".join(tokens[:-1])
            # handle arrays: pull the [N] off the name onto the type
            arr = re.match(r"(\w+)(\[[^\]]+\])$", name)
            if arr:
                name = arr.group(1)
                ctype = ctype + arr.group(2)
            fields.append({"type": ctype, "name": name})
        out.append({"name": m.group(2), "fields": fields})
    return out


def parse_typedefs(src: str):
    """Catch the simple opaque-handle typedef + callback typedef."""
    out = []
    # `typedef struct sa_handle_s *sa_handle_t;`
    for m in re.finditer(r"typedef\s+([^;{}]+?)\s+(\w+)\s*;", src):
        underlying = _normalise_ws(m.group(1))
        name = m.group(2)
        # skip the struct/enum typedef bodies (already covered above)
        if "{" in m.group(0):
            continue
        if underlying.startswith("struct ") and "{" not in underlying:
            out.append({"name": name, "underlying": underlying})
        elif underlying.startswith("enum "):
            continue  # covered by enums
        elif "(*" in underlying or "(*" in m.group(0):
            out.append({"name": name, "underlying": underlying + " (callback)"})
    return out


def parse_functions(raw_src: str, clean_src: str):
    """Pull every `sa_*` function declaration + its preceding /** doc */."""
    out = []
    # Find each declaration in the cleaned source so we get reliable bounds.
    decl_pat = re.compile(
        r"([A-Za-z_][\w\s\*]+?)\s+(sa_[a-z_]+)\s*\(([^;{}]*)\)\s*;",
        re.DOTALL,
    )
    # Map char offset in raw -> nearest preceding /** doc */
    doc_spans = [(m.start(), m.end(), m.group(1).strip())
                 for m in _DOC_BLOCK.finditer(raw_src)]

    for m in decl_pat.finditer(clean_src):
        ret = _normalise_ws(m.group(1))
        name = m.group(2)
        args_blob = _normalise_ws(m.group(3))
        # Skip typedef'd callback (`typedef void (*sa_callback_t)...`) — its
        # decl_pat shape happens to match; filter by ret prefix.
        if ret.startswith("typedef"):
            continue
        args = []
        if args_blob and args_blob != "void":
            for piece in args_blob.split(","):
                piece = _normalise_ws(piece)
                if not piece:
                    continue
                tokens = piece.rsplit(" ", 1)
                if len(tokens) == 1:
                    args.append({"type": tokens[0], "name": ""})
                else:
                    arg_type, arg_name = tokens
                    # Pointer / array trailing handling (`int8_t *img_in`):
                    while arg_name.startswith("*"):
                        arg_type += "*"
                        arg_name = arg_name[1:]
                    args.append({"type": arg_type, "name": arg_name})

        # Locate the function name in raw_src and look back for a /** ... */
        raw_idx = raw_src.find(name + "(")
        doc = ""
        if raw_idx >= 0:
            for start, end, body in doc_spans:
                if end <= raw_idx:
                    doc = _normalise_ws(body)
        out.append({"name": name, "return": ret, "args": args, "doc": doc})
    return out


def build(header_path: Path) -> dict:
    raw = header_path.read_text(encoding="utf-8")
    clean = _strip_comments(raw)
    return {
        "version": "1.1.0",
        "source_header": "sw/sdk/include/spike_accel.h",
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "macros":    parse_macros(clean),
        "enums":     parse_enums(clean),
        "structs":   parse_structs(clean),
        "typedefs":  parse_typedefs(clean),
        "functions": parse_functions(raw, clean),
    }


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    header = Path(sys.argv[1])
    out = Path(sys.argv[2])
    payload = build(header)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}  (functions={len(payload['functions'])}, "
          f"structs={len(payload['structs'])}, enums={len(payload['enums'])})")


if __name__ == "__main__":
    main()
