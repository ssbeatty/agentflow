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

These are cheap static assertions — no venv, no network — that fail CI the moment
either pair drifts, which is exactly what the "sync by hand" comments ask for.
"""
import re
from pathlib import Path

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
