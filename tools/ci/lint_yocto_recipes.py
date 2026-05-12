#!/usr/bin/env python3
"""Static lint for the Petalinux/Yocto recipe tree (C1).

We cannot bitbake from CI (no toolchain license + 30+ min runtime), but we
*can* statically check that each .bb / .bbappend in
``sw/petalinux/project-spec/meta-user/`` carries the minimum mandatory
metadata + sane ``inherit`` chain + variable references.

Emits ``runs/yocto_recipe_lint.json`` and exits non-zero on any FAIL.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RECIPE_ROOT = ROOT / "sw" / "petalinux" / "project-spec" / "meta-user"
OUT = ROOT / "runs" / "yocto_recipe_lint.json"

# Required keys per recipe kind. .bb = full recipe, .bbappend = additive.
REQUIRED_BB = ("SUMMARY", "LICENSE")
REQUIRED_APP_BB = REQUIRED_BB + ("SRC_URI", "FILES:${PN}")
KNOWN_INHERITS = {"cmake", "autotools", "pkgconfig", "module", "kernel-module-split"}
VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_:]*)\}")


def lint_one(p: Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace")
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    out = {"file": rel, "status": "pass", "warnings": [], "errors": []}
    is_app = p.suffix == ".bb"
    is_apps_dir = "recipes-apps" in rel
    required = REQUIRED_APP_BB if (is_app and is_apps_dir) else REQUIRED_BB if is_app else ()
    for key in required:
        if key not in text:
            out["errors"].append(f"missing required field {key!r}")
    # SRC_URI sanity: if declared with file:// the referenced path or sibling
    # files/ directory should exist relative to the recipe.
    for m in re.finditer(r"file://([A-Za-z0-9_.\-/]+)", text):
        rel_src = m.group(1).rstrip("/")
        sibling = p.parent / "files" / rel_src
        local = p.parent / rel_src
        if not sibling.exists() and not local.exists() and rel_src not in ("CMakeLists.txt",):
            # CMakeLists is fetched by fetch_app_sources.sh; soft-warn.
            out["warnings"].append(f"SRC_URI file:// path not resolvable yet: {rel_src}")
    # inherit chain sanity
    for m in re.finditer(r"^inherit\s+(.+)$", text, re.MULTILINE):
        for cls in m.group(1).split():
            if cls not in KNOWN_INHERITS:
                out["warnings"].append(f"uncommon inherit class {cls!r}")
    # ${PN} / ${THISDIR} should be used not as bare PN/THISDIR
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if re.search(r"(?<![A-Z_$\{])\b(THISDIR|PN|D|S|WORKDIR)\b(?!\})", stripped):
            # allow `PN = "x"` LHS, only flag RHS bare refs after `=`
            rhs = stripped.split("=", 1)[1]
            if re.search(r"(?<![A-Z_$\{])\b(THISDIR|PN)\b(?!\})", rhs):
                out["warnings"].append(f"bare bitbake var (use ${{...}}): {stripped!r}")
    if out["errors"]:
        out["status"] = "fail"
    elif out["warnings"]:
        out["status"] = "warn"
    return out


def main() -> int:
    recipes = sorted(list(RECIPE_ROOT.rglob("*.bb")) + list(RECIPE_ROOT.rglob("*.bbappend")))
    results = [lint_one(p) for p in recipes]
    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "warn": sum(1 for r in results if r["status"] == "warn"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for r in results:
        tag = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}[r["status"]]
        print(f"[{tag}] {r['file']}")
        for w in r["warnings"]:
            print(f"        warn: {w}")
        for e in r["errors"]:
            print(f"        err : {e}")
    print(f"---- {summary['pass']} pass, {summary['warn']} warn, {summary['fail']} fail")
    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
