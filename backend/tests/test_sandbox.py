"""Sandbox env + shell selection for the opt-in run_bash / run_python tools
(agentflow/_sandbox.py).

Two regressions guarded here:

- `_sandbox_env()` must put the current interpreter's bin/Scripts dir FIRST on
  PATH, so bash's `python`/`pip` and any venv console scripts (e.g. a skill's
  CLI) resolve to the SAME per-script venv `run_python` already uses via
  `sys.executable` — not a system/pyenv python that lacks the installed
  packages — while still scrubbing every AGENTFLOW_* secret from the env.
- `_shell()` must prefer a real (Git) bash over the System32 `bash.exe` WSL
  launcher on Windows: WSL is a separate Linux environment where the Windows
  per-script venv is unreachable.
"""
import os
import sys

import pytest

from agentflow import _sandbox as sandbox


def test_sandbox_env_prepends_interpreter_bindir():
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    env = sandbox._sandbox_env()
    assert env["PATH"].split(os.pathsep)[0] == bindir


def test_sandbox_env_still_scrubs_agentflow_secrets(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_SECRET_TOKEN", "super-secret")
    monkeypatch.setenv("AGENTFLOW_LLM_DEFAULT", "sk-should-not-leak")
    env = sandbox._sandbox_env()
    assert not any(k.startswith("AGENTFLOW_") for k in env), \
        "sandbox env must never carry AGENTFLOW_* credentials"


def test_sandbox_env_keeps_proxy_config(monkeypatch):
    # Sandboxed code allows network by default, so it must inherit the host's
    # proxy — else a proxied network silently "drops" the sandbox (SSL EOF /
    # timeout) while the main run works. Regression for _ENV_KEEP omitting proxy.
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.local:8080")
    monkeypatch.setenv("http_proxy", "http://proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    env = sandbox._sandbox_env()
    assert env.get("HTTPS_PROXY") == "http://proxy.local:8080"
    assert env.get("http_proxy") == "http://proxy.local:8080"
    assert env.get("NO_PROXY") == "localhost,127.0.0.1"


def test_run_python_uses_current_venv_interpreter():
    # The python tool runs under sys.executable (the per-script venv), so venv
    # packages are importable inside it.
    res = sandbox.run_python("import sys; print(sys.executable)")
    assert res["returncode"] == 0, res
    assert sys.executable in res["stdout"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX $PATH form; on Windows bash may be WSL/Git with translated paths",
)
def test_run_bash_sees_venv_bindir_on_path():
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    res = sandbox.run_bash('echo "$PATH"')
    assert res["returncode"] == 0, res
    assert bindir in res["stdout"], \
        "the venv bin dir must be on the bash sandbox PATH so `python`/CLIs resolve to it"


def test_windows_git_bash_rejects_wsl_launcher(monkeypatch):
    # Simulate a host where the only `bash` is the System32 WSL launcher.
    monkeypatch.setattr(sandbox.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(
        sandbox.shutil, "which",
        lambda name: r"C:\Windows\System32\bash.exe" if name == "bash" else None,
    )
    assert sandbox._windows_git_bash() is None


def test_windows_git_bash_finds_git_install(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    gitbash = os.path.join(r"C:\Program Files", "Git", "bin", "bash.exe")
    monkeypatch.setattr(sandbox.os.path, "isfile", lambda p: p == gitbash)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    assert sandbox._windows_git_bash() == gitbash
