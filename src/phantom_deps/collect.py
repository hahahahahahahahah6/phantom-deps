"""Collect dependency names from manifest files and bare imports.

Sources:
  - requirements*.txt            -> PyPI
  - pyproject.toml               -> PyPI
  - setup.py / setup.cfg         -> PyPI (best-effort regex)
  - package.json                 -> npm
  - *.py imports                 -> PyPI (best-effort name mapping)
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

# A few common import-name -> distribution-name mismatches. Best-effort only;
# every collected name is still verified against the registry, so a wrong
# guess here can only produce an extra lookup, never a wrong verdict.
IMPORT_ALIASES = {
    "bs4": "beautifulsoup4",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "magic": "python-magic",
    "attr": "attrs",
    "jwt": "PyJWT",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "git": "GitPython",
    "psycopg2": "psycopg2-binary",
    "lxml": "lxml",
    "wx": "wxPython",
    "OpenSSL": "pyOpenSSL",
    "jose": "python-jose",
    "socks": "PySocks",
    "nacl": "PyNaCl",
    "zmq": "pyzmq",
    "bson": "pymongo",
    "gridfs": "pymongo",
    "flask_sqlalchemy": "Flask-SQLAlchemy",
    "skimage": "scikit-image",
}

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")

_SKIP_PREFIXES = ("-", "#", "!", "http://", "https://", "git+", "file:", ".", "/")


def _clean_req_name(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith(_SKIP_PREFIXES):
        return None
    # strip inline comments (only when preceded by whitespace, to be safe)
    line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
    # strip environment markers
    line = line.split(";", 1)[0].strip()
    # strip extras: requests[security] -> requests
    line = line.split("[", 1)[0].strip()
    m = _NAME_RE.match(line)
    if not m:
        return None
    name = m.group(1)
    # guard against option lines like "--index-url" leftovers
    if name.startswith("-"):
        return None
    return name


def parse_requirements(path: str) -> list[str]:
    """Parse a requirements.txt-style file, return distribution names."""
    names: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                name = _clean_req_name(line)
                if name:
                    names.append(name)
    except OSError:
        pass
    return names


def _parse_pyproject_tomllib(path: str) -> list[str]:
    import tomllib  # Python 3.11+

    names: list[str] = []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return names
    project = data.get("project", {})
    deps = list(project.get("dependencies", []) or [])
    for group in (project.get("optional-dependencies", {}) or {}).values():
        deps.extend(group or [])
    for dep in deps:
        if not isinstance(dep, str):
            continue
        name = _clean_req_name(dep)
        if name:
            names.append(name)
    return names


def _parse_pyproject_regex(path: str) -> list[str]:
    """Fallback for Python < 3.11: grab the [project] dependencies block."""
    names: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return names
    m = re.search(
        r"^\[project\].*?^dependencies\s*=\s*\[(.*?)\]",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return names
    for quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1)):
        dep = quoted[0] or quoted[1]
        name = _clean_req_name(dep)
        if name:
            names.append(name)
    return names


def parse_pyproject(path: str) -> list[str]:
    if sys.version_info >= (3, 11):
        return _parse_pyproject_tomllib(path)
    return _parse_pyproject_regex(path)


def parse_package_json(path: str) -> list[str]:
    """Return npm dependency names from package.json."""
    names: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return names
    for section in ("dependencies", "devDependencies", "peerDependencies",
                    "optionalDependencies"):
        deps = data.get(section, {})
        if isinstance(deps, dict):
            names.extend(str(k) for k in deps.keys())
    return names


def _stdlib_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()) or ())
    if not names:  # Python < 3.10 fallback
        names = {
            "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii",
            "bisect", "builtins", "bz2", "calendar", "cmath", "collections",
            "concurrent", "configparser", "contextlib", "contextvars", "copy",
            "csv", "ctypes", "curses", "dataclasses", "datetime", "decimal",
            "difflib", "dis", "email", "encodings", "enum", "errno", "faulthandler",
            "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib",
            "functools", "gc", "getopt", "getpass", "gettext", "glob", "gzip",
            "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib",
            "importlib", "inspect", "io", "ipaddress", "itertools", "json",
            "keyword", "lib2to3", "locale", "logging", "lzma", "mailbox",
            "mailcap", "marshal", "math", "mimetypes", "mmap", "multiprocessing",
            "netrc", "nis", "nntplib", "numbers", "operator", "optparse", "os",
            "ossaudiodev", "pathlib", "pdb", "pickle", "pickletools", "pipes",
            "pkgutil", "platform", "plistlib", "poplib", "posix", "pprint",
            "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc",
            "queue", "quopri", "random", "re", "readline", "reprlib", "resource",
            "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
            "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib",
            "sndhdr", "socket", "socketserver", "sqlite3", "ssl", "stat",
            "statistics", "string", "stringprep", "struct", "subprocess", "sunau",
            "symtable", "sys", "sysconfig", "tabnanny", "tarfile", "telnetlib",
            "tempfile", "termios", "test", "textwrap", "threading", "time",
            "timeit", "tkinter", "token", "tokenize", "tomllib", "trace",
            "traceback", "tracemalloc", "tty", "turtle", "turtle", "types",
            "typing", "unicodedata", "unittest", "urllib", "uu", "uuid",
            "venv", "warnings", "wave", "weakref", "webbrowser", "wsgiref",
            "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
            "zoneinfo", "_thread",
        }
    return names


def scan_imports(root: str) -> list[str]:
    """Walk *.py under root, collect top-level third-party import names."""
    stdlib = _stdlib_names()
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".venv", "venv", ".git",
                                    "node_modules", ".tox", "build", "dist")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=path)
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        found.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import -> local package
                        continue
                    if node.module:
                        found.add(node.module.split(".")[0])
    third_party = sorted(
        IMPORT_ALIASES.get(name, name)
        for name in found
        if name and name not in stdlib and not name.startswith("_")
    )
    # de-duplicate after alias mapping
    seen: set[str] = set()
    out: list[str] = []
    for name in third_party:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


class ScanResult:
    def __init__(self) -> None:
        self.pypi: list[str] = []   # (name, source)
        self.npm: list[str] = []

    def add_pypi(self, name: str, source: str) -> None:
        self.pypi.append((name, source))

    def add_npm(self, name: str, source: str) -> None:
        self.npm.append((name, source))


def scan_path(target: str) -> ScanResult:
    """Scan a file or directory; return collected names per ecosystem."""
    result = ScanResult()
    if os.path.isfile(target):
        _scan_file(target, result)
        return result
    if os.path.isdir(target):
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames
                           if d not in (".venv", "venv", ".git", "node_modules",
                                        "__pycache__", ".tox", "build", "dist")]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                _scan_file(full, result)
        # bare imports across the tree
        for name in scan_imports(target):
            result.add_pypi(name, "imports")
        return result
    raise FileNotFoundError(f"no such file or directory: {target}")


def _scan_file(path: str, result: ScanResult) -> None:
    base = os.path.basename(path)
    low = base.lower()
    if low == "package.json":
        for name in parse_package_json(path):
            result.add_npm(name, "package.json")
    elif low == "pyproject.toml":
        for name in parse_pyproject(path):
            result.add_pypi(name, "pyproject.toml")
    elif low.startswith("requirements") and low.endswith((".txt", ".in")):
        for name in parse_requirements(path):
            result.add_pypi(name, base)
    elif low in ("setup.cfg",):
        for name in parse_requirements(path):  # same line grammar for install_requires
            result.add_pypi(name, base)
