from pathlib import Path, PurePosixPath


_INTERNAL_FILE_PREFIXES = ("_runner_", "_input_")


def normalize_script_filename(filename: str) -> str:
    """Validate and normalize a script-owned relative filename."""
    raw = (filename or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("filename is required")
    if len(raw) > 255:
        raise ValueError("filename must be 255 characters or fewer")
    if ":" in raw:
        raise ValueError("filename must not contain drive letters or URL schemes")
    if any(ord(ch) < 32 for ch in raw):
        raise ValueError("filename contains control characters")

    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ValueError("filename must be relative")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("filename must not contain empty, '.', or '..' path segments")
    if path.name.startswith(_INTERNAL_FILE_PREFIXES):
        raise ValueError("filename conflicts with AgentFlow runtime files")

    return path.as_posix()


def script_file_path(script_dir: Path, filename: str) -> Path:
    """Return a safe absolute path for a script file under script_dir."""
    normalized = normalize_script_filename(filename)
    root = script_dir.resolve()
    target = (root / normalized).resolve()
    if target != root and root not in target.parents:
        raise ValueError("filename escapes the script directory")
    return target
