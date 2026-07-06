"""Env scrubbing for user-script subprocesses (services/venv_manager.py).

`_clean_env()` must strip anything that would drag debugpy / the parent venv
into a user-script child python — otherwise debugpy infects venvs that don't
have it installed (see CLAUDE.md "Subprocess plumbing").
"""
from services import venv_manager


def test_clean_env_strips_debugger_and_venv_vars(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/injected")
    monkeypatch.setenv("PYTHONHOME", "/py")
    monkeypatch.setenv("VIRTUAL_ENV", "/some/.venv")
    monkeypatch.setenv("PYDEVD_LOAD_VALUES_ASYNC", "1")
    monkeypatch.setenv("DEBUGPY_FOO", "1")
    monkeypatch.setenv("PYCHARM_BAR", "1")
    monkeypatch.setenv("AGENTFLOW_KEEP_ME", "keep")

    env = venv_manager._clean_env()

    for stripped in (
        "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
        "PYDEVD_LOAD_VALUES_ASYNC", "DEBUGPY_FOO", "PYCHARM_BAR",
    ):
        assert stripped not in env, f"{stripped} should have been scrubbed"

    # Ordinary vars are preserved.
    assert env.get("AGENTFLOW_KEEP_ME") == "keep"
