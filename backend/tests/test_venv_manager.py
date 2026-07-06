"""Env scrubbing + defensive rlimits for user-script subprocesses
(services/venv_manager.py).

`_clean_env()` must strip anything that would drag debugpy / the parent venv
into a user-script child python — otherwise debugpy infects venvs that don't
have it installed (see CLAUDE.md "Subprocess plumbing").

`make_run_preexec()` returns a POSIX preexec_fn that caps a user script's
memory so it can't OOM the host; it degrades to None on Windows.
"""
import os
import subprocess
import sys

import pytest

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


def test_make_run_preexec_degrades_off_posix():
    """On Windows there's no `resource` module, so it must return None (Popen
    then simply gets no preexec_fn); on POSIX it returns a callable."""
    result = venv_manager.make_run_preexec(mem_mb=256)
    if os.name == "posix":
        assert callable(result)
    else:
        assert result is None


def test_make_run_preexec_zero_disables_all_limits():
    """0 for every limit still yields a callable that no-ops safely (RLIMIT_CORE
    aside) — i.e. passing it to Popen can never raise."""
    fn = venv_manager.make_run_preexec(mem_mb=0, fsize_mb=0, nproc=0)
    if os.name == "posix":
        assert callable(fn)
        fn()  # applying it must not raise even with everything disabled
    else:
        assert fn is None


@pytest.mark.skipif(os.name != "posix", reason="rlimits only apply on POSIX")
def test_run_preexec_caps_memory():
    """A child spawned with the preexec can't allocate past RLIMIT_AS — whether
    it fails to allocate or fails to even boot under the cap, it must not exit 0
    with the big buffer allocated."""
    preexec = venv_manager.make_run_preexec(mem_mb=256)
    assert preexec is not None
    proc = subprocess.run(
        [sys.executable, "-c",
         "b = bytearray(768 * 1024 * 1024); print('allocated', len(b))"],
        preexec_fn=preexec,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0, (
        f"expected the 256 MiB cap to block a 768 MiB alloc, "
        f"got rc=0 stdout={proc.stdout!r}"
    )


@pytest.mark.skipif(os.name != "posix", reason="rlimits only apply on POSIX")
def test_run_preexec_allows_normal_child():
    """No false positives: a modest child runs fine under a generous cap."""
    preexec = venv_manager.make_run_preexec(mem_mb=1024)
    proc = subprocess.run(
        [sys.executable, "-c", "b = bytearray(16 * 1024 * 1024); print('ok')"],
        preexec_fn=preexec,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"unexpected failure: {proc.stderr!r}"
    assert proc.stdout.strip() == "ok"


# ── bwrap filesystem jail (services/venv_manager.py::build_bwrap_prefix) ────────

def test_bwrap_prefix_jails_to_script_dir_only(tmp_path):
    """The prefix binds this script's own dir + the SDK, chdir'd into run_dir —
    and NEVER the data root / secret_key / sibling scripts. Pure string logic,
    so it's checked on every OS regardless of whether bwrap is installed."""
    data = tmp_path / "data"
    script_dir = data / "scripts" / "abc123"
    run_dir = script_dir / "runs" / "run1"
    backend_root = tmp_path / "backend"
    (backend_root / "agentflow").mkdir(parents=True)
    script_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (data / ".secret_key").write_text("topsecret", encoding="utf-8")
    (data / "scripts" / "other").mkdir(parents=True)

    prefix = venv_manager.build_bwrap_prefix(script_dir, run_dir, backend_root)

    sd = os.path.abspath(str(script_dir))
    rd = os.path.abspath(str(run_dir))
    sdk = os.path.abspath(str(backend_root / "agentflow"))

    assert prefix[0] == "bwrap"
    assert "--unshare-pid" in prefix and "--die-with-parent" in prefix
    assert sd in prefix          # own dir bound (rw)
    assert sdk in prefix         # agentflow SDK bound (ro)
    assert prefix[-2:] == ["--chdir", rd]
    # The crux: nothing above this script's own dir is ever exposed.
    assert os.path.abspath(str(data)) not in prefix
    assert os.path.abspath(str(data / ".secret_key")) not in prefix
    assert os.path.abspath(str(data / "scripts" / "other")) not in prefix
    assert os.path.abspath(str(backend_root)) not in prefix  # only its agentflow subdir


def test_maybe_wrap_sandbox_identity_when_disabled(tmp_path, monkeypatch):
    """When the sandbox can't run (off / no bwrap), the argv is returned as-is
    (same object) so the caller's launch-failure fallback `is`-check works."""
    monkeypatch.setattr(venv_manager, "sandbox_enabled", lambda: False)
    argv = ["/path/python", "runner.py"]
    out = venv_manager.maybe_wrap_sandbox(
        argv, script_dir=tmp_path, run_dir=tmp_path, backend_root=tmp_path)
    assert out is argv


def _bwrap_functional() -> bool:
    return os.name == "posix" and venv_manager._bwrap_probe()


@pytest.mark.skipif(not _bwrap_functional(), reason="requires a functional bwrap")
def test_bwrap_hides_out_of_jail_files(tmp_path):
    """End-to-end: a command run under the prefix cannot read a sibling file
    that lives outside the bound script dir (the whole point of the jail)."""
    data = tmp_path / "data"
    script_dir = data / "scripts" / "s1"
    run_dir = script_dir / "runs" / "r1"
    backend_root = tmp_path / "backend"
    (backend_root / "agentflow").mkdir(parents=True)
    run_dir.mkdir(parents=True)
    secret = data / ".secret_key"
    secret.write_text("topsecret", encoding="utf-8")

    prefix = venv_manager.build_bwrap_prefix(script_dir, run_dir, backend_root)
    # Reading the out-of-jail secret must fail; reading an in-jail file must work.
    in_jail = run_dir / "ok.txt"
    in_jail.write_text("hi", encoding="utf-8")

    blocked = subprocess.run(prefix + ["cat", str(secret)],
                             capture_output=True, text=True, timeout=30)
    allowed = subprocess.run(prefix + ["cat", str(in_jail)],
                             capture_output=True, text=True, timeout=30)

    assert blocked.returncode != 0, "secret_key should be invisible inside the jail"
    assert "topsecret" not in blocked.stdout
    assert allowed.returncode == 0 and allowed.stdout.strip() == "hi"
