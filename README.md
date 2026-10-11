# phantom-deps

A hallucinated-dependency scanner. Before you `pip install` or `npm install`
what an AI assistant just recommended, phantom-deps checks that every package
name actually exists on PyPI / npm — and flags packages published so recently
(< 30 days) that they smell like slopsquatting.

**1 in 5 AI-suggested packages doesn't exist.** Research presented at USENIX
Security 2025 found that 19.7% of the 2.23 million package references produced
by 16 large language models point to packages that were never published. The
classic failure: the model invents a plausible-sounding library name, you
install it, and an attacker who registered that exact name first gets code
execution on your machine (the "slopsquatting" attack). phantom-deps is the
30-second check you run between "the AI gave me code" and "I installed its
dependencies".

Zero dependencies. Python standard library only (`urllib` talks to the PyPI
JSON API and the npm registry directly). Everything stays local; registry
results are cached under `~/.cache/phantom-deps/`.

## Install

```bash
pip install phantom-deps
```

Or from source:

```bash
git clone https://github.com/hahahahahahahahah6/phantom-deps
cd phantom-deps
pip install .
```

Requires Python 3.9+.

## Usage

```bash
# scan a project directory (requirements.txt, pyproject.toml,
# package.json, and bare Python imports are all picked up)
phantom-deps ./my-ai-generated-project

# scan specific files
phantom-deps requirements.txt package.json

# machine-readable output
phantom-deps . --json

# exit codes: 0 = clean, 1 = phantom or brand-new packages found,
#             2 = usage error (bad path)
```

Example output:

```
PHANTOM — does not exist on the registry (1):
  ✗ datavalidator-pro [pypi, from requirements.txt]

NEW — published recently, high risk (1):
  ! fastjson-utils (6d old) [pypi, from imports]

1 known-good packages checked, 3 total.
```

Useful flags:

| Flag | Meaning |
|---|---|
| `--json` | emit JSON instead of text |
| `--new-days N` | risk window for "recently published" (default: 30) |
| `--ignore-new` / `--ignore-phantom` | don't fail on that class |
| `--no-cache` | skip the local registry-result cache |
| `--timeout SEC` | per-request timeout (default: 15) |
| `--no-color` | disable colored output |

Typical CI / pre-commit gate:

```bash
phantom-deps . || echo "unverified dependencies — review before installing"
```

Notes:

- Bare imports are mapped to distribution names on a best-effort basis
  (`bs4` → `beautifulsoup4`, `PIL` → `Pillow`, `cv2` → `opencv-python`, …).
  Every mapped name is still verified against the real registry, so a wrong
  guess only costs an extra lookup — it can never produce a wrong verdict.
- The scanner fails open on network errors: an unreachable registry is
  reported as a note, never as a false "phantom".

## Differentiation

Supply-chain scanners already exist — this one is aimed at a different
moment. Tools in the slopsquatting space generally watch registries for
malicious uploads or audit lockfiles you already committed. phantom-deps
targets the **"the LLM just recommended this — verify before installing"**
step:

1. **Pre-install, not post-hoc.** It runs on the AI-generated snippet's
   `requirements.txt` / import block before anything touches your
   environment, not on a lockfile after the fact.
2. **Nonexistence is the primary signal.** Most scanners assume the package
   exists and ask "is it malicious?". For AI-generated code the base rate is
   different — ~1 in 5 suggested packages was never published at all — so
   "does this exist?" is the cheapest, highest-value question.
3. **Zero-dependency and instant.** One `pip install` (or none — it runs from
   source with the stdlib alone), no daemon, no account, no SBOM pipeline.

## License

MIT — see [LICENSE](LICENSE).
