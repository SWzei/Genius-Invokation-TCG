"""Compare subjects that were run under different tags of the same suite.

    python -m bench.compare --tags lite_glm53 lite_refs --reference "llm:glm-53-plan" \\
        --subjects "llm:glm-53-plan" "llm:glm-53-plan#kb=rules" heuristic "expert:<deck>" --out lite_all

Every subject of a suite plays the same cells on the same seeds, so runs made at
different times (a model today, the scripted references last week) are still
paired game for game. Tags whose ``meta.json`` carries a different suite
fingerprint are refused: their cells are not the same games. The paired tables
only use cells both subjects played (a model run with ``--replicates 1`` covers
half the cells of a full reference run).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from bench.report import build_report, render_markdown
from bench.suite import load_suite
from common.paths import data_dir, ensure_dir, reports_dir


def load_tags(tags: list[str]) -> tuple[Any, list[dict[str, Any]], dict[str, list[str]]]:
    suite, rows, subjects_by_tag = None, [], {}
    fingerprint = None
    for tag in tags:
        root = data_dir() / "bench" / tag
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
        if fingerprint is None:
            fingerprint = meta["fingerprint"]
            suite = load_suite(meta["suite"]["name"])
            if suite.fingerprint != fingerprint:
                raise SystemExit(f"tag {tag!r} was run on suite fingerprint {fingerprint}, the suite on disk is "
                                 f"{suite.fingerprint}")
        elif meta["fingerprint"] != fingerprint:
            raise SystemExit(f"tag {tag!r} has suite fingerprint {meta['fingerprint']}, expected {fingerprint}: "
                             "different cells, not comparable game for game")
        tag_rows = [json.loads(line) for line in (root / "games.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        rows.extend(tag_rows)
        subjects_by_tag[tag] = sorted({r["subject"] for r in tag_rows})
    return suite, rows, subjects_by_tag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tags", nargs="+", required=True)
    parser.add_argument("--subjects", nargs="*", default=None, help="default: every subject found, in tag order")
    parser.add_argument("--reference", default=None, help="paired tables are relative to this subject")
    parser.add_argument("--common-cells", action="store_true",
                        help="restrict every table to the cells the reference played (same games for all)")
    parser.add_argument("--out", required=True, help="report name under reports/bench/")
    args = parser.parse_args(argv)

    suite, rows, subjects_by_tag = load_tags(args.tags)
    found = [s for tag in args.tags for s in subjects_by_tag[tag]]
    subjects = list(dict.fromkeys(args.subjects or found))
    missing = [s for s in subjects if s not in found]
    if missing:
        raise SystemExit(f"no rows for {missing}; found {found}")
    reference = args.reference or subjects[0]
    if args.common_cells:
        ref_cells = {r["cell"] for r in rows if r["subject"] == reference}
        rows = [r for r in rows if r["cell"] in ref_cells]
    report = build_report(suite, rows, subjects, reference=reference)
    report.update({"tags": list(args.tags), "common_cells_only": bool(args.common_cells),
                   "generated": _dt.datetime.now().isoformat(timespec="seconds")})
    out_dir = Path(ensure_dir(reports_dir() / "bench"))
    (out_dir / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8")
    text = render_markdown({**report, "tag": args.out})
    (out_dir / f"{args.out}.md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
