"""Classify a failed CI run against ``docs/RISK_RULES.yaml`` and open a
GitHub issue tagged with the matching ``risk:R<n>`` label.

Invoked from ``.github/workflows/risk_dispatcher.yml``. Designed to be
side-effect free unless ``--create-issue`` is passed, so it can be unit
tested with synthetic logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RULES_PATH = REPO_ROOT / "docs" / "RISK_RULES.yaml"


def load_rules(path: Path = RULES_PATH) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_text(text: str, rules: Dict) -> Optional[Dict]:
    """Return the first matching risk entry, or None.

    Rules are ranked by R-id ascending (R1, R2, …). Each rule's ``patterns``
    list is OR-joined — any one match wins.
    """
    risks = rules.get("risks", {})
    # iterate by sorted key (R1..R7) so behavior is deterministic
    for rid in sorted(risks.keys()):
        entry = risks[rid]
        for pat in entry.get("patterns", []):
            if re.search(pat, text, re.MULTILINE):
                return {**entry, "id": rid, "matched_pattern": pat}
    default = rules.get("default")
    if default is not None:
        return {**default, "id": "default"}
    return None


def collect_logs(logs_dir: Path) -> str:
    """Concatenate every ``*.log``/``*.xml``/``*.txt`` under logs_dir.

    Caps total size at 4 MB so a huge JUnit XML cannot wedge regex.
    """
    out = []
    total = 0
    cap = 4 * 1024 * 1024
    for p in sorted(logs_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".log", ".xml", ".txt", ".rpt", ".json", ".out"):
            continue
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append(f"\n=== {p.relative_to(logs_dir)} ===\n")
        out.append(data)
        total += len(data)
        if total > cap:
            out.append(f"\n... (truncated at {cap // (1024 * 1024)} MB)\n")
            break
    return "".join(out)


def build_issue_body(workflow_run_id: str, workflow_name: str,
                     hit: Dict, snippet: str) -> str:
    assignees = hit.get("assignees", [])
    handlers = hit.get("handlers", [])
    return (
        f"## Auto-classified failure\n\n"
        f"- **Workflow**: {workflow_name}\n"
        f"- **Run ID**: {workflow_run_id}\n"
        f"- **Risk**: {hit.get('id')} — {hit.get('title')}\n"
        f"- **Suggested assignees**: {', '.join(assignees) if assignees else 'D2'}\n"
        f"- **Matched pattern**: `{hit.get('matched_pattern', 'default-fallback')}`\n\n"
        f"### Recommended handlers (plan section {hit.get('plan_section', 'N/A')})\n"
        + ("\n".join(f"- {h}" for h in handlers) if handlers else "_(none configured)_")
        + "\n\n### Log excerpt (first 2 KB)\n```\n"
        + snippet[:2048]
        + "\n```\n"
    )


def create_github_issue(title: str, body: str, labels: List[str]) -> int:
    """Open issue via ``gh issue create``. Requires ``GH_TOKEN`` in env."""
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for lbl in labels:
        cmd.extend(["--label", lbl])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"gh issue create failed: {r.stderr}", file=sys.stderr)
    else:
        print(f"opened: {r.stdout.strip()}")
    return r.returncode


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workflow-run-id", required=True)
    p.add_argument("--workflow-name", required=True)
    p.add_argument("--logs-dir", required=True, type=Path)
    p.add_argument("--rule-set", default=str(RULES_PATH), type=Path)
    p.add_argument("--create-issue", action="store_true")
    p.add_argument("--dry-run-output", type=Path, default=None,
                   help="write classification JSON to this path instead of opening issue")
    args = p.parse_args(argv)

    rules = load_rules(args.rule_set)
    text = collect_logs(args.logs_dir)
    if not text.strip():
        print("[dispatch] no logs found — skipping", file=sys.stderr)
        return 0

    hit = classify_text(text, rules)
    if hit is None:
        print("[dispatch] no rule matched; default rule is also unset", file=sys.stderr)
        return 0

    report = {
        "workflow_run_id": args.workflow_run_id,
        "workflow_name": args.workflow_name,
        "classified": hit,
    }
    if args.dry_run_output:
        args.dry_run_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[dispatch] dry-run wrote {args.dry_run_output}")
        return 0

    print(json.dumps(report, indent=2))

    if args.create_issue:
        if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
            print("[dispatch] GH_TOKEN missing — skipping issue creation", file=sys.stderr)
            return 0
        title = f"[{hit.get('id', 'risk')}] {hit.get('title', 'CI failure')} " \
                f"(run #{args.workflow_run_id})"
        body = build_issue_body(args.workflow_run_id, args.workflow_name, hit, text)
        labels = [f"risk:{hit['id']}"] if hit.get("id", "").startswith("R") else []
        labels.append("nightly-failure")
        return create_github_issue(title, body, labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
