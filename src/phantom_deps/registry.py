"""Registry lookups (PyPI / npm) with a local JSON cache.

For every name we ask: does it exist, and if so, how old is its first
release? Packages younger than ``new_days`` are flagged as high-risk
(slopsquatting / typosquat window).
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}"

DEFAULT_NEW_DAYS = 30
CACHE_TTL_DAYS = 7


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_iso(value: str) -> datetime.datetime | None:
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _http_json(url: str, timeout: float) -> dict | None:
    """GET url, return parsed JSON, or None on 404. Raises on other errors."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "phantom-deps/0.1.0", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _pypi_first_upload(payload: dict) -> datetime.datetime | None:
    releases = payload.get("releases") or {}
    earliest: datetime.datetime | None = None
    for files in releases.values():
        if not files:
            continue
        ts = files[0].get("upload_time_iso_8601") or files[0].get("upload_time")
        dt = _parse_iso(ts) if ts else None
        if dt and (earliest is None or dt < earliest):
            earliest = dt
    return earliest


def _npm_first_upload(payload: dict) -> datetime.datetime | None:
    created = (payload.get("time") or {}).get("created")
    return _parse_iso(created) if created else None


class Verdict:
    OK = "ok"            # exists, older than the risk window
    NEW = "new"          # exists but published within the risk window
    PHANTOM = "phantom"  # does not exist on the registry at all


class Check:
    """One registry lookup result."""

    def __init__(self, name: str, ecosystem: str, verdict: str,
                 age_days: int | None, first_released: str | None,
                 error: str | None = None) -> None:
        self.name = name
        self.ecosystem = ecosystem
        self.verdict = verdict
        self.age_days = age_days
        self.first_released = first_released
        self.error = error

    def registry_url(self) -> str:
        if self.ecosystem == "npm":
            return f"https://www.npmjs.com/package/{urllib.parse.quote(self.name)}"
        return f"https://pypi.org/project/{urllib.parse.quote(self.name)}/"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ecosystem": self.ecosystem,
            "verdict": self.verdict,
            "age_days": self.age_days,
            "first_released": self.first_released,
            "error": self.error,
        }


class RegistryChecker:
    def __init__(self, cache_dir: str | None = None, timeout: float = 15.0,
                 new_days: int = DEFAULT_NEW_DAYS, use_cache: bool = True) -> None:
        self.cache_dir = cache_dir or os.path.join(
            os.path.expanduser("~"), ".cache", "phantom-deps")
        self.timeout = timeout
        self.new_days = new_days
        self.use_cache = use_cache
        self._cache: dict[str, dict] = {}
        self._cache_loaded = False
        self.lookups = 0  # network lookups performed (useful for tests)

    # -- cache ---------------------------------------------------------
    def _cache_path(self) -> str:
        return os.path.join(self.cache_dir, "checks.json")

    def _load_cache(self) -> None:
        if self._cache_loaded:
            return
        self._cache_loaded = True
        try:
            with open(self._cache_path(), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._cache = data
        except (OSError, ValueError):
            self._cache = {}

    def _save_cache(self) -> None:
        if not self.use_cache:
            return
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_path(), "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
        except OSError:
            pass  # caching is best-effort; never fail a scan over it

    def _cache_get(self, key: str) -> Check | None:
        self._load_cache()
        entry = self._cache.get(key)
        if not entry:
            return None
        try:
            checked = _parse_iso(entry.get("checked_at", ""))
        except Exception:
            return None
        if checked is None:
            return None
        if (_now_utc() - checked).days > CACHE_TTL_DAYS:
            return None
        return Check(
            entry["name"], entry["ecosystem"], entry["verdict"],
            entry.get("age_days"), entry.get("first_released"),
        )

    def _cache_put(self, key: str, check: Check) -> None:
        self._cache[key] = {
            "name": check.name,
            "ecosystem": check.ecosystem,
            "verdict": check.verdict,
            "age_days": check.age_days,
            "first_released": check.first_released,
            "checked_at": _now_utc().isoformat(),
        }

    # -- lookups -------------------------------------------------------
    def check(self, name: str, ecosystem: str = "pypi") -> Check:
        """Check one package name against a registry."""
        ecosystem = ecosystem.lower()
        key = f"{ecosystem}:{name.lower()}"
        if self.use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        try:
            check = self._lookup(name, ecosystem)
        except Exception as exc:  # network failures fail open with an error note
            check = Check(name, ecosystem, Verdict.OK, None, None,
                          error=f"lookup failed: {exc}")
        if self.use_cache and check.error is None:
            self._cache_put(key, check)
            self._save_cache()
        return check

    def _lookup(self, name: str, ecosystem: str) -> Check:
        self.lookups += 1
        if ecosystem == "npm":
            url = NPM_URL.format(name=urllib.parse.quote(name, safe=""))
            payload = _http_json(url, self.timeout)
            first = _npm_first_upload(payload) if payload else None
        else:
            url = PYPI_URL.format(name=urllib.parse.quote(name, safe=""))
            payload = _http_json(url, self.timeout)
            first = _pypi_first_upload(payload) if payload else None
        if payload is None:
            return Check(name, ecosystem, Verdict.PHANTOM, None, None)
        if first is None:
            return Check(name, ecosystem, Verdict.OK, None, None)
        age = (_now_utc() - first).days
        if age < self.new_days:
            return Check(name, ecosystem, Verdict.NEW, age, first.date().isoformat())
        return Check(name, ecosystem, Verdict.OK, age, first.date().isoformat())
