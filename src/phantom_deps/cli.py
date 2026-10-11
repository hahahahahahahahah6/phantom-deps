"""phantom-deps CLI: scan manifests and imports for hallucinated dependencies."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .collect import scan_path
from .registry import DEFAULT_NEW_DAYS, RegistryChecker, Verdict
from .report import render_json, render_text


def _use_color(args: argparse.Namespace) -> bool:
    if args.no_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="phantom-deps",
        description="Scan requirements.txt / pyproject.toml / package.json "
                    "and bare imports for hallucinated (nonexistent) or "
                    "brand-new high-risk dependencies, before you pip/npm install.",
    )
    ap.add_argument("targets", nargs="*", default=["."],
                    help="files or directories to scan (default: current dir)")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of text")
    ap.add_argument("--new-days", type=int, default=DEFAULT_NEW_DAYS, metavar="N",
                    help="flag packages first published less than N days ago "
                    f"(default: {DEFAULT_NEW_DAYS})")
    ap.add_argument("--no-cache", action="store_true",
                    help="skip the local registry-result cache")
    ap.add_argument("--timeout", type=float, default=15.0, metavar="SEC",
                    help="per-request timeout in seconds (default: 15)")
    ap.add_argument("--ignore-new", action="store_true",
                    help="don't treat recently-published packages as failures")
    ap.add_argument("--ignore-phantom", action="store_true",
                    help="don't treat nonexistent packages as failures")
    ap.add_argument("--no-color", action="store_true",
                    help="disable colored output")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    checker = RegistryChecker(timeout=args.timeout, new_days=args.new_days,
                              use_cache=not args.no_cache)

    checks = []
    sources: dict[str, str] = {}
    seen: set[str] = set()
    try:
        for target in args.targets:
            result = scan_path(target)
            pairs = ([("pypi", name, source) for name, source in result.pypi]
                     + [("npm", name, source) for name, source in result.npm])
            for ecosystem, name, source in pairs:
                key = f"{ecosystem}:{name.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                sources[name.lower()] = source
                checks.append(checker.check(name, ecosystem))
    except FileNotFoundError as exc:
        print(f"phantom-deps: error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(checks, sources))
    else:
        print(render_text(checks, sources, color=_use_color(args)))

    failures = [k for k in checks
                if (k.verdict == Verdict.PHANTOM and not args.ignore_phantom)
                or (k.verdict == Verdict.NEW and not args.ignore_new)]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
