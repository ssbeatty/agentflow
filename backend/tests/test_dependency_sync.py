"""Guards against two documented "keep these in sync by hand" footguns.

CLAUDE.md calls out two places where the same thing is written twice and a silent
drift becomes a real runtime bug:

  1. `venv_manager.BASELINE_PACKAGES` (installed into every user-script venv) vs
     `backend/requirements.txt` (the backend python, which the built-in assistant
     reuses). If a langchain-stack package is added to one and not the other, the
     assistant and user scripts run different versions — or one is missing a dep.

  2. `_norm()` exists verbatim in BOTH `agentflow/__init__.py` (resolves
     get_llm/get_secret names in the subprocess) and `execution_engine.py` (builds
     the matching `AGENTFLOW_*` env vars). If they diverge, a secret/model name
     normalizes to a different env var on each side and silently resolves to None.

A third guard covers the frontend editor's code-hint catalog
(`frontend/src/lib/agentflowApi.ts`) — a hand-maintained mirror of the public
`agentflow` SDK surface with no runtime introspection. If someone adds a new
built-in SDK function and forgets to add a catalog entry, the editor silently
stops advertising it; this test fails CI instead.

These are cheap static assertions — no venv, no network — that fail CI the moment
either pair drifts, which is exactly what the "sync by hand" comments ask for.
"""
import re
from pathlib import Path

import pytest

from services.venv_manager import BASELINE_PACKAGES

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _pkg_name(spec: str) -> str:
    """Strip version specifiers / extras / markers → the bare distribution name,
    normalized (lowercase, `_`→`-`) per PEP 503 so `nest_asyncio`==`nest-asyncio`."""
    name = re.split(r"[<>=!~; \[]", spec.strip(), 1)[0]
    return name.strip().lower().replace("_", "-")


def _requirements_names() -> set[str]:
    text = (BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(_pkg_name(line))
    return names


def test_baseline_packages_are_all_in_requirements():
    """Every user-script baseline package must also be a backend dependency, so
    the assistant (backend python, no per-script venv) has the same stack."""
    reqs = _requirements_names()
    missing = sorted(
        _pkg_name(p) for p in BASELINE_PACKAGES if _pkg_name(p) not in reqs
    )
    assert not missing, (
        "BASELINE_PACKAGES has package(s) absent from backend/requirements.txt: "
        f"{missing}. Add them to requirements.txt too (the assistant reuses the "
        "backend python) — see CLAUDE.md 'keep the two lists in sync'."
    )


def _extract_norm_body(rel_path: str) -> str:
    """Pull the one-liner body of the first `def _norm(name: str) -> str:` in a
    source file, whitespace-normalized so indentation (module-level vs nested)
    doesn't matter — only the actual expression is compared."""
    src = (BACKEND_ROOT / rel_path).read_text(encoding="utf-8")
    m = re.search(
        r"def _norm\(name: str\) -> str:\s*\n\s*(return .+)", src
    )
    assert m, f"could not find _norm() in {rel_path}"
    return re.sub(r"\s+", " ", m.group(1)).strip()


def test_norm_definitions_are_identical():
    """The two hand-copied `_norm()` bodies must match character-for-character
    (after whitespace normalization) so a name maps to the same env var on both
    sides of the subprocess boundary."""
    sdk = _extract_norm_body("agentflow/__init__.py")
    engine = _extract_norm_body("services/execution_engine.py")
    assert sdk == engine, (
        "_norm() has drifted between agentflow/__init__.py and "
        f"execution_engine.py:\n  SDK:    {sdk}\n  engine: {engine}\n"
        "Keep them identical (CLAUDE.md) or get_llm/get_secret name resolution "
        "will silently disagree with the env vars the engine builds."
    )


def test_norm_behavior_is_locked():
    """Lock the SDK `_norm` contract so a refactor can't quietly change how names
    map to env vars (which would orphan every existing secret/model binding)."""
    from agentflow import _norm

    assert _norm("gpt-4o") == "GPT_4O"
    assert _norm("deepseek-reasoner") == "DEEPSEEK_REASONER"
    assert _norm("my.key_name") == "MY_KEY_NAME"
    assert _norm("  spaced  ") == "SPACED"
    assert _norm("") == "UNNAMED"
    assert _norm("!!!") == "UNNAMED"


# ── Editor code-hint catalog ⇄ agentflow SDK surface ──────────────────────────

FRONTEND_CATALOG = BACKEND_ROOT.parent / "frontend" / "src" / "lib" / "agentflowApi.ts"

# Public SDK names intentionally NOT surfaced as editor code hints. Empty today;
# add a name here (with a reason) if you export a public helper that genuinely
# should not appear in the completion list, so this guard stays meaningful.
CATALOG_EXCLUDE: set[str] = set()


def _sdk_public_surface() -> set[str]:
    """The real public `agentflow` SDK surface, derived by introspection: every
    non-underscore name whose definition lives in the `agentflow` package —
    module-level functions, the `_sandbox` re-exports (run_bash/run_python), the
    `paths` object, and the `AgentFlowFile` class. Imported stdlib / third-party
    symbols (os, json, Path, …) are filtered out by their `__module__`."""
    import agentflow

    out: set[str] = set()
    for name in dir(agentflow):
        if name.startswith("_"):
            continue
        obj = getattr(agentflow, name)
        mod = getattr(obj, "__module__", None) or getattr(type(obj), "__module__", "") or ""
        if mod.startswith("agentflow"):
            out.add(name)
    return out


def _catalog_names() -> set[str]:
    """Names declared in the frontend editor-hint catalog (the `AGENTFLOW_API`
    array in frontend/src/lib/agentflowApi.ts). Scoped to that array so the
    interface's `name: string;` and the snippet block can't leak in."""
    text = FRONTEND_CATALOG.read_text(encoding="utf-8")
    start = text.index("AGENTFLOW_API")
    end = text.index("AGENTFLOW_SNIPPETS", start)
    return set(re.findall(r'^\s*name:\s*"([^"]+)"', text[start:end], re.MULTILINE))


def test_editor_hint_catalog_matches_sdk_surface():
    """The editor's code-hint catalog must list exactly the public SDK surface, so
    a newly added built-in shows up in completion/hover and a removed one stops
    being advertised. See CLAUDE.md 'Editor code hints'."""
    if not FRONTEND_CATALOG.exists():
        pytest.skip("frontend catalog not present (backend-only checkout)")
    sdk = _sdk_public_surface() - CATALOG_EXCLUDE
    catalog = _catalog_names()
    missing = sorted(sdk - catalog)
    stale = sorted(catalog - sdk)
    assert not missing and not stale, (
        "frontend/src/lib/agentflowApi.ts (editor code-hint catalog) has drifted "
        "from the agentflow SDK:\n"
        f"  public in SDK but missing from catalog: {missing}\n"
        f"  in catalog but not a public SDK name:   {stale}\n"
        "Add the new symbol to AGENTFLOW_API (name + signature + doc), or if it is "
        "intentionally not a code hint, add it to CATALOG_EXCLUDE in this test."
    )
