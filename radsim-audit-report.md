# RadSim v1.1.0 — Package & Dependency Audit

**Date:** 28 February 2026  
**Repo:** github.com/Mbemera/radsim  
**Build system:** Hatchling  
**Python:** ≥3.10  

---

## Executive Summary

RadSim’s **direct dependencies have zero known CVEs**. The codebase passes all 685 tests and has a clean ruff lint. However, there are several actionable findings: a missing declared dependency (`python-dotenv`), significant version drift in pinned packages, inconsistencies between `pyproject.toml` and `requirements.txt`, and a heavy transitive dependency tree from the `chromadb` optional extra.

---

## 1. CVE / Vulnerability Scan

**Tool:** `pip-audit` against `requirements.txt`  
**Result:** ✅ **No known vulnerabilities in RadSim’s direct dependencies.**  

*Note: The broader system environment (pip, setuptools, wheel, pypdf, flask, werkzeug) has 20 CVEs, but none of these are RadSim dependencies. They are pre-installed system packages.*

---

## 2. Declared vs Actual Dependencies

### Missing from `pyproject.toml`

| Package | Import Location | Status |
| :--- | :--- | :--- |
| `python-dotenv` | `radsim/modes.py` (top-level, unconditional) | 🔴 **CRITICAL — not declared anywhere** |

`python-dotenv` is imported at module level in `modes.py` with `from dotenv import load_dotenv` — this is **not** guarded by a try/except, meaning RadSim will crash on import if `python-dotenv` isn’t installed. It needs to be added to `dependencies` in `pyproject.toml`.

### Properly Declared Dependencies

| Package | `pyproject.toml` | `requirements.txt` | Import Guard |
| :--- | :--- | :--- | :--- |
| `anthropic` | `>=0.40.0,<1.0` | `==0.42.0` | ✅ try/except |
| `openai` | `>=1.50.0,<2.0` (optional) | `==1.58.0` | ✅ try/except |
| `google-genai` | `>=0.8.0` (optional) | `>=0.8.0` | ✅ try/except |
| `playwright` | `>=1.40.0,<2.0` (optional) | `==1.49.0` | ✅ try/except |
| `chromadb` | `>=0.4.0,<1.0` (optional) | not listed | ✅ try/except |

---

## 3. Version Drift

Pinned versions in `requirements.txt` are significantly behind latest:

| Package | Pinned | Latest Available | Gap |
| :--- | :--- | :--- | :--- |
| `anthropic` | `0.42.0` | **0.84.0** | ~42 versions behind |
| `openai` | `1.58.0` | **2.24.0** | Major version behind (breaking changes likely) |
| `playwright` | `1.49.0` | **1.58.0** | 9 versions behind |
| `chromadb` | `0.4.0+` | **1.5.2** | `pyproject.toml` caps at `<1.0` — excludes current stable |
| `ruff` | `0.8.4` | **0.15.4** | 7 minor versions behind |
| `pytest` | `8.3.4` | **9.0.2** | Major version behind |

### Recommendations

*   **anthropic:** Update pin. The `<1.0` upper bound in `pyproject.toml` is fine, but `==0.42.0` in `requirements.txt` is stale.
*   **openai:** v2.x is a breaking change. Test compatibility before bumping the `<2.0` cap.
*   **chromadb:** The `<1.0` cap in `pyproject.toml` excludes all current stable releases (now at 1.5.2). This needs revisiting — users installing the `memory` or `vector` extras will get a very old version.
*   **google-genai:** No upper bound in either file — could break on future major releases. Consider adding `<2.0`.

---

## 4. `pyproject.toml` vs `requirements.txt` Inconsistencies

| Issue | Detail |
| :--- | :--- |
| `chromadb` missing from `requirements.txt` | Listed in `pyproject.toml` optional deps but not in `requirements.txt` |
| `python-dotenv` missing from both | Used unconditionally but not declared |
| `google-genai` not pinned in `requirements.txt` | Uses `>=0.8.0` (range) while other packages use exact pins |
| Duplicate optional groups | `memory` and `vector` extras are identical (both just `chromadb`) — consolidate |

---

## 5. Transitive Dependency Weight

The optional extras pull in very different dependency footprints:

| Extra | Direct Dep | Notable Transitive Deps | Approx. Total Packages |
| :--- | :--- | :--- | :--- |
| (core) | `anthropic` | `httpx`, `pydantic`, `anyio`, `jiter` | ~10 |
| `openai` | `openai` | `httpx`, `pydantic` (shared with core) | +3 |
| `gemini` | `google-genai` | `google-auth`, `requests`, `websockets`, `tenacity` | +8 |
| `browser` | `playwright` | `greenlet`, `pyee` | +2 |
| `memory/vector`| `chromadb` | `fastapi`, `uvicorn`, `grpcio`, `kubernetes`, `numpy`, `onnxruntime`, `opentelemetry` (6 pkgs), `tokenizers`, `rich`, `orjson`, `posthog` | **+30** |

**`chromadb` is by far the heaviest optional dependency**, pulling in a full web server stack (fastapi + uvicorn), Kubernetes client, ONNX runtime, and telemetry packages. For a CLI tool, this is a significant weight. Consider whether a lighter vector store option (e.g., `sqlite-vec` or `lancedb`) could replace it.

---

## 6. License Compatibility

All dependencies are compatible with RadSim’s MIT license:

| Package | License |
| :--- | :--- |
| `anthropic` | MIT |
| `openai` | Apache-2.0 |
| `google-genai` | Apache-2.0 |
| `chromadb` | Apache-2.0 |
| `playwright` | Apache-2.0 |
| `python-dotenv` | BSD-3-Clause |
| `pytest` | MIT |
| `ruff` | MIT |

✅ **No license conflicts.**

---

## 7. Code Quality Snapshot

| Metric | Result |
| :--- | :--- |
| Tests collected | 685 |
| Ruff lint | ✅ All checks passed |
| Python classifiers | 3.10 through 3.14 |
| Build system | Hatchling (modern, PEP 517) |

---

## 8. Action Items (Priority Order)

### 🔴 Critical
1.  **Add `python-dotenv` to dependencies** in `pyproject.toml` — it’s an unconditional runtime dependency that will cause `ImportError` if missing.

### 🟡 Important
2.  **Update `requirements.txt` pins** — `anthropic` and `playwright` are significantly behind.
3.  **Reassess `chromadb` version cap** — `<1.0` excludes all current stable releases.
4.  **Add upper bound to `google-genai`** — unbounded ranges risk breaking installs.
5.  **Test `openai` v2.x compatibility** — the ecosystem has moved on.

### 🟢 Housekeeping
6.  **Consolidate `memory` and `vector` extras** — they’re identical.
7.  **Add `chromadb` to `requirements.txt`** if it’s meant to be a reference lockfile.
8.  **Pin `google-genai` in `requirements.txt`** for consistency with other entries.
9.  **Consider lighter alternatives to `chromadb`** for the vector memory feature.
