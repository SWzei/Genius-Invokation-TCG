"""Versions of the external knowledge base (D34).

``GITCG_KB`` v1.0 (``$GITCG_KB_DIR``) is read-only. A later version is a chain of
patches kept in this repo under ``configs/knowledge/kb_versions/<version>/``::

    version.toml     parent, layer ("rules" | "strategy"), date, summary
    changes.patch    unified diff against the parent, paths relative to the KB root
    CHANGELOG.md     what changed, the evidence (games / engine checks), the session

``python -m reps.kb_versions build <version>`` copies v1.0, applies the chain, rebuilds
the KB's own exports with its ``tools/build_index.py`` and runs ``tools/validate_kb.py``
(needs ``$GITCG_DATA_RELEASE``). A version whose validation reports any issue is not
built. The result lives under ``$GITCG_DATA_DIR/kb_versions/<version>`` (not committed).

Layer discipline: a ``rules`` version may only touch ``rules/``; a ``strategy`` version
only ``strategy/``. Rule facts are never changed because of win rates -- only
technical fixes (boundary conditions, cross references), each checked by the engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python <=3.10
    import tomli as tomllib  # type: ignore

from common.paths import REPO_ROOT, data_dir

BASE_VERSION = "v1.0"
VERSIONS_DIR = REPO_ROOT / "configs" / "knowledge" / "kb_versions"
LAYER_PREFIX = {"rules": "rules/", "strategy": "strategy/"}
_NAME = re.compile(r"^v\d+\.\d+(-s\d+)?$")


def version_spec(version: str) -> dict[str, Any]:
    path = VERSIONS_DIR / version / "version.toml"
    if not path.exists():
        raise FileNotFoundError(f"KB version {version!r}: {path} not found")
    with path.open("rb") as handle:
        spec = tomllib.load(handle)
    if spec.get("layer") not in LAYER_PREFIX:
        raise ValueError(f"KB version {version!r}: layer must be one of {sorted(LAYER_PREFIX)}")
    return spec


def chain(version: str) -> list[str]:
    """Versions from the first patch on top of v1.0 up to ``version``."""
    out: list[str] = []
    current = version
    while current != BASE_VERSION:
        if not _NAME.match(current) or current in out:
            raise ValueError(f"KB version chain broken at {current!r}")
        out.append(current)
        current = str(version_spec(current).get("parent", BASE_VERSION))
    return out[::-1]


def patch_paths(patch_text: str) -> list[str]:
    paths = []
    for line in patch_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            p = line[4:].split("\t")[0].strip()
            if p != "/dev/null":
                paths.append(p.split("/", 1)[1] if p[:2] in ("a/", "b/") else p)
    return sorted(set(paths))


def check_layer(version: str) -> list[str]:
    spec = version_spec(version)
    text = (VERSIONS_DIR / version / "changes.patch").read_text(encoding="utf-8")
    prefix = LAYER_PREFIX[spec["layer"]]
    paths = patch_paths(text)
    bad = [p for p in paths if not p.startswith(prefix)]
    if bad:
        raise ValueError(f"KB version {version!r} ({spec['layer']} layer) touches {bad}")
    if not paths:
        raise ValueError(f"KB version {version!r}: empty patch")
    return paths


def built_dir(version: str) -> Path:
    return data_dir("kb_versions", version)


def resolve(version: str) -> Path:
    """Directory of a KB version usable as ``kb_root`` (v1.0 = ``$GITCG_KB_DIR``)."""
    if version in ("", BASE_VERSION):
        return Path(os.environ.get("GITCG_KB_DIR", ""))
    out = built_dir(version)
    if not (out / "data" / "derived" / "rule_sections.jsonl").exists():
        raise FileNotFoundError(f"KB version {version!r} is not built: python -m reps.kb_versions build {version}")
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build(version: str, *, base: str | None = None, release: str | None = None) -> dict[str, Any]:
    base_dir = Path(base or os.environ.get("GITCG_KB_DIR", ""))
    release_dir = release or os.environ.get("GITCG_DATA_RELEASE", "")
    if not (base_dir / "data" / "derived").exists():
        raise FileNotFoundError("set GITCG_KB_DIR to the KB v1.0 directory")
    if not release_dir:
        raise FileNotFoundError("set GITCG_DATA_RELEASE (validate_kb needs the data release)")
    readme = (base_dir / "README.md").read_text(encoding="utf-8")
    if not re.search(r"^version:\s*1\.0\s*$", readme, re.M):
        raise ValueError(f"{base_dir} is not KB v1.0")
    out = built_dir(version)
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(base_dir, tmp)
    applied = []
    for v in chain(version):
        paths = check_layer(v)
        patch = VERSIONS_DIR / v / "changes.patch"
        before = {p: (tmp / p).read_bytes() if (tmp / p).exists() else None for p in paths}
        # GIT_CEILING_DIRECTORIES: never let git find an enclosing repository (this repo's data/
        # is inside one), where `git apply` silently skips paths outside the current directory.
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp.parent)}
        proc = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=tmp,
                              capture_output=True, text=True, env=env)
        unchanged = [p for p in paths if (tmp / p).exists() and (tmp / p).read_bytes() == before[p]]
        if proc.returncode != 0 or unchanged:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"KB version {v}: patch does not apply ({proc.stderr.strip()[:300]}; "
                               f"unchanged: {unchanged})")
        applied.append({"version": v, "patch_sha": _sha(patch), "paths": paths})
    readme_path = tmp / "README.md"
    readme_path.write_text(re.sub(r"^version:\s*1\.0\s*$", f"version: {version.lstrip('v')}",
                                  readme_path.read_text(encoding="utf-8"), count=1, flags=re.M), encoding="utf-8")
    for tool, args in (("build_index.py", []), ("validate_kb.py", [release_dir])):
        proc = subprocess.run([sys.executable, f"tools/{tool}", *args], cwd=tmp, capture_output=True, text=True)
        if proc.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"KB version {version}: {tool} failed: {proc.stderr.strip()[-500:]}")
    report = json.loads((tmp / "data" / "derived" / "validation_report.json").read_text(encoding="utf-8"))
    issues = {k: v for k, v in (report.get("issue_counts") or {}).items() if v}
    if issues:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"KB version {version}: validate_kb reports issues {issues}")
    derived = tmp / "data" / "derived"
    manifest = {"version": version, "base": BASE_VERSION, "applied": applied,
                "validation": report.get("stats", {}),
                "derived": {p.name: _sha(p) for p in sorted(derived.glob("*.jsonl"))}}
    (tmp / "kb_version.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build / inspect KB versions (D34).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("versions", nargs="+")
    s = sub.add_parser("show")
    s.add_argument("versions", nargs="+")
    args = parser.parse_args(argv)
    for version in args.versions:
        if args.command == "build":
            print(json.dumps(build(version), ensure_ascii=False, indent=1))
        else:
            print(version, "chain:", chain(version), "paths:", check_layer(version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
