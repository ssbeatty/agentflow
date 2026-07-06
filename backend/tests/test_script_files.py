"""Script filename normalization / path-traversal safety (services/script_files.py).

This is a security boundary — user-supplied filenames must never escape the
script directory or collide with runtime files. Add a case here whenever a new
traversal/edge shape is discovered.
"""
import pytest

from services.script_files import normalize_script_filename


@pytest.mark.parametrize("raw,expected", [
    ("main.py", "main.py"),
    ("pkg/util.py", "pkg/util.py"),
    ("a\\b\\c.py", "a/b/c.py"),        # backslashes normalized to forward slashes
    ("  main.py  ", "main.py"),        # surrounding whitespace trimmed
    ("a/./b.py", "a/b.py"),            # single-dot segment collapsed by PurePosixPath
])
def test_normalize_accepts(raw, expected):
    assert normalize_script_filename(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "../secret.py",                     # parent traversal
    "a/../../etc/passwd",               # nested traversal
    "/etc/passwd",                      # absolute path
    "C:/Windows/system32",             # drive letter (':' rejected)
    "http://evil/x",                    # URL scheme (':' rejected)
    "_runner_evil.py",                  # collides with runtime runner file
    "_input_x.json",                    # collides with runtime input file
    "bad\x00name.py",                   # control character
    "x" * 256 + ".py",                  # exceeds 255 chars
])
def test_normalize_rejects(raw):
    with pytest.raises(ValueError):
        normalize_script_filename(raw)
