import asyncio
import shutil
import sys
from pathlib import Path

from app.config import DATA_DIR


def get_script_dir(script_id: str) -> Path:
    d = DATA_DIR / script_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_venv_python(script_id: str) -> Path:
    venv = get_script_dir(script_id) / ".venv"
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_exists(script_id: str) -> bool:
    return get_venv_python(script_id).exists()


def _uv() -> str | None:
    return shutil.which("uv")


async def stream_create_venv(script_id: str):
    """Yield output lines while creating the venv."""
    venv_dir = get_script_dir(script_id) / ".venv"
    uv = _uv()
    if uv:
        cmd = [uv, "venv", str(venv_dir)]
    else:
        cmd = [sys.executable, "-m", "venv", str(venv_dir)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for line in proc.stdout:
        yield line.decode("utf-8", errors="replace").rstrip()
    await proc.wait()
    if proc.returncode != 0:
        yield f"ERROR: venv creation failed (exit {proc.returncode})"
    else:
        yield "DONE"


async def stream_install(script_id: str, requirements: str):
    """Write requirements.txt and yield pip install output lines."""
    script_dir = get_script_dir(script_id)
    req_file = script_dir / "requirements.txt"
    req_file.write_text(requirements, encoding="utf-8")

    python = get_venv_python(script_id)
    uv = _uv()

    if uv:
        cmd = [uv, "pip", "install", "-r", str(req_file), "--python", str(python)]
    else:
        cmd = [str(python), "-m", "pip", "install", "-r", str(req_file)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for line in proc.stdout:
        yield line.decode("utf-8", errors="replace").rstrip()
    await proc.wait()
    if proc.returncode != 0:
        yield f"ERROR: install failed (exit {proc.returncode})"
    else:
        yield "DONE"
