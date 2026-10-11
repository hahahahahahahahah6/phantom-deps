"""Human-readable and JSON report rendering."""
from __future__ import annotations

import json
import os

from .registry import Check, Verdict

_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _colors(enabled: bool):
    if not enabled:
        return {"red": "", "yellow": "", "green": "", "dim": "", "reset": ""}
    return {"red": _RED, "yellow": _YELLOW, "green": _GREEN, "dim": _DIM,
            "reset": _RESET}


def render_text(checks: list[Check], sources: dict[str, str],
                color: bool = True) -> str:
    """Render a human-readable report."""
    c = _colors(color)
    lines: list[str] = []
    phantoms = [k for k in checks if k.verdict == Verdict.PHANTOM]
    news = [k for k in checks if k.verdict == Verdict.NEW]
    oks = [k for k in checks if k.verdict == Verdict.OK]

    if phantoms:
        lines.append(f"{c['red']}PHANTOM — does not exist on the registry "
                     f"({len(phantoms)}):{c['reset']}")
        for k in phantoms:
            src = sources.get(k.name.lower(), "?")
            lines.append(f"  {c['red']}✗{c['reset']} {k.name} "
                         f"{c['dim']}[{k.ecosystem}, from {src}]{c['reset']}")
            if k.error:
                lines.append(f"      {c['dim']}{k.error}{c['reset']}")
        lines.append("")
    if news:
        lines.append(f"{c['yellow']}NEW — published recently, high risk "
                     f"({len(news)}):{c['reset']}")
        for k in news:
            src = sources.get(k.name.lower(), "?")
            age = f"{k.age_days}d old" if k.age_days is not None else "age unknown"
            lines.append(f"  {c['yellow']}!{c['reset']} {k.name} ({age}) "
                         f"{c['dim']}[{k.ecosystem}, from {src}]{c['reset']}")
        lines.append("")
    if not phantoms and not news:
        lines.append(f"{c['green']}No phantom or high-risk dependencies "
                     f"found ({len(oks)} checked).{c['reset']}")
    else:
        lines.append(f"{c['dim']}{len(oks)} known-good packages checked, "
                     f"{len(checks)} total.{c['reset']}")
    return "\n".join(lines)


def render_json(checks: list[Check], sources: dict[str, str]) -> str:
    payload = []
    for k in checks:
        d = k.to_dict()
        d["source"] = sources.get(k.name.lower())
        d["registry_url"] = k.registry_url()
        payload.append(d)
    return json.dumps(payload, indent=2)
