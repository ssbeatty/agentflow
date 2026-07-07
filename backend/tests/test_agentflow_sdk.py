"""User-facing agentflow SDK helpers (backend/agentflow/__init__.py).

Importing `agentflow` is cheap — the langchain/langgraph stack is imported
lazily inside get_llm()/get_agent(), so these unit tests don't need a venv.
"""
import os
from pathlib import Path

import pytest

import agentflow


def test_norm_matches_env_var_convention():
    # `_norm` maps an arbitrary name to the AGENTFLOW_LLM_/AGENTFLOW_SECRET_ suffix.
    assert agentflow._norm("bark-key") == "BARK_KEY"
    assert agentflow._norm("My Model 1.5") == "MY_MODEL_1_5"
    assert agentflow._norm("") == "UNNAMED"


def test_get_secret_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_SECRET_BARK_KEY", "s3cret")
    assert agentflow.get_secret("bark-key") == "s3cret"     # non-alnum → _
    assert agentflow.get_secret("BARK_KEY") == "s3cret"
    assert agentflow.get_secret("Bark.Key") == "s3cret"


def test_get_secret_default_when_missing(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_SECRET_NOPE", raising=False)
    assert agentflow.get_secret("nope") is None
    assert agentflow.get_secret("nope", "fallback") == "fallback"


def test_paths_resolve_lazily(monkeypatch):
    """Regression (Bug #1): `paths` must reflect the CURRENT env on every access,
    NOT a value snapshotted at import. A warm worker imports agentflow once at
    boot (before any job's path env exists) and reuses it across jobs; a snapshot
    would freeze every path to the boot cwd (the script dir) for all reused runs."""
    monkeypatch.setenv("AGENTFLOW_RUN_DIR", "/tmp/af_run_a")
    monkeypatch.setenv("AGENTFLOW_WORKSPACE_DIR", "/tmp/af_ws_a")
    assert agentflow.paths.run_dir == Path("/tmp/af_run_a")
    assert agentflow.paths.workspace == Path("/tmp/af_ws_a")
    # A later change (as happens per-job inside the worker) is picked up.
    monkeypatch.setenv("AGENTFLOW_RUN_DIR", "/tmp/af_run_b")
    assert agentflow.paths.run_dir == Path("/tmp/af_run_b")


def test_get_tools_handles_none_injected(monkeypatch):
    """Regression (Bug #3): a no-MCP run leaves `_injected_tools` empty and the
    warm worker resets it per job — get_tools()/get_agent() must never crash with
    'NoneType is not iterable'. `include_builtins=False` keeps this hermetic (no
    langchain import); the point is that iterating `_injected_tools` tolerates None."""
    monkeypatch.setattr(agentflow, "_injected_tools", None)
    assert agentflow.get_tools(include_builtins=False) == []


def test_get_llm_unknown_model_raises(monkeypatch):
    """Regression (F2): an unconfigured *named* model must raise a clear error
    (naming the bad id) instead of silently returning None — which used to surface
    downstream as a confusing `'NoneType' object has no attribute 'invoke'`."""
    monkeypatch.delenv("AGENTFLOW_LLM_NOPE_MODEL", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        agentflow.get_llm("nope-model")


def test_get_llm_default_missing_returns_none(monkeypatch):
    """The default (`get_llm()`) with no LLM configured at all still returns None —
    only *named* lookups raise (F2 must not change the no-LLM-configured case)."""
    for k in list(os.environ):
        if k.startswith("AGENTFLOW_LLM_"):
            monkeypatch.delenv(k, raising=False)
    assert agentflow.get_llm() is None
