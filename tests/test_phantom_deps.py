"""Smoke tests for phantom-deps. All network access is mocked."""
from __future__ import annotations

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from phantom_deps import collect
from phantom_deps.cli import main as cli_main
from phantom_deps.registry import RegistryChecker, Verdict

NOW = datetime.datetime.now(datetime.timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - datetime.timedelta(days=days_ago)).isoformat()


def _pypi_payload(days_ago: int) -> dict:
    return {
        "info": {"name": "x", "version": "1.0"},
        "releases": {"1.0": [{"upload_time_iso_8601": _iso(days_ago)}]},
    }


def _npm_payload(days_ago: int) -> dict:
    return {
        "name": "x",
        "time": {"created": _iso(days_ago), "1.0": _iso(days_ago)},
    }


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else req
    if "pypi.org/pypi/requests/json" in url:
        return _FakeResp(_pypi_payload(4000))
    if "pypi.org/pypi/brand-new-thing/json" in url:
        return _FakeResp(_pypi_payload(5))
    if "pypi.org/pypi/" in url and "/json" in url:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
    if "registry.npmjs.org/lodash" in url:
        return _FakeResp(_npm_payload(4000))
    if "registry.npmjs.org/" in url:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
    raise AssertionError(f"unexpected URL in test: {url}")


def _write(tmp: str, name: str, content: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestCollect(unittest.TestCase):
    def test_requirements_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "requirements.txt",
                       "# comment\nrequests==2.31.0\nnumpy>=1.24  # inline\n"
                       "Django[argon2]; python_version>'3.8'\n-r other.txt\n"
                       "-e .\nhttps://example.com/pkg.zip\n\n")
            names = collect.parse_requirements(p)
        self.assertEqual(names, ["requests", "numpy", "Django"])

    def test_pyproject_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "pyproject.toml",
                       '[project]\nname = "x"\ndependencies = [\n'
                       '  "requests>=2",\n  "rich; sys_platform==\'win32\'",\n]\n'
                       '[project.optional-dependencies]\ndev = ["pytest"]\n')
            names = collect.parse_pyproject(p)
        self.assertEqual(sorted(names), ["pytest", "requests", "rich"])

    def test_package_json_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "package.json",
                       json.dumps({"dependencies": {"lodash": "^4.0.0"},
                                   "devDependencies": {"jest": "^29.0.0"}}))
            names = collect.parse_package_json(p)
        self.assertEqual(sorted(names), ["jest", "lodash"])

    def test_import_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "app.py",
                   "import os\nimport sys\nimport requests\n"
                   "from bs4 import BeautifulSoup\n"
                   "from .local import thing\nimport numpy as np\n")
            names = collect.scan_imports(tmp)
        self.assertIn("requests", names)
        self.assertIn("beautifulsoup4", names)  # alias mapping
        self.assertIn("numpy", names)
        self.assertNotIn("os", names)
        self.assertNotIn("sys", names)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("urllib.request.urlopen", side_effect=_fake_urlopen)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _checker(self, **kw):
        kw.setdefault("use_cache", False)
        return RegistryChecker(**kw)

    def test_pypi_phantom(self):
        c = self._checker().check("no-such-package-zzz", "pypi")
        self.assertEqual(c.verdict, Verdict.PHANTOM)

    def test_pypi_ok(self):
        c = self._checker().check("requests", "pypi")
        self.assertEqual(c.verdict, Verdict.OK)
        self.assertGreater(c.age_days, 30)

    def test_pypi_new_high_risk(self):
        c = self._checker().check("brand-new-thing", "pypi")
        self.assertEqual(c.verdict, Verdict.NEW)
        self.assertLess(c.age_days, 30)

    def test_npm_phantom(self):
        c = self._checker().check("no-such-package-zzz", "npm")
        self.assertEqual(c.verdict, Verdict.PHANTOM)

    def test_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            checker = RegistryChecker(cache_dir=tmp, use_cache=True)
            checker.check("requests", "pypi")
            first_lookups = checker.lookups
            checker.check("requests", "pypi")
            self.assertEqual(checker.lookups, first_lookups)  # served from cache


class TestEndToEnd(unittest.TestCase):
    def test_scan_fixture_dir_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "requirements.txt",
                   "requests==2.31.0\nno-such-package-zzz==1.0\n")
            _write(tmp, "package.json",
                   json.dumps({"dependencies": {"no-such-npm-zzz": "^1.0.0"}}))
            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                with patch.dict(os.environ, {"NO_COLOR": "1"}):
                    rc = cli_main([tmp, "--no-cache", "--ignore-new"])
        # one pypi phantom + one npm phantom -> findings -> exit 1
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
