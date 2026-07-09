"""
A reusable code MODULE — shared Python other scripts import.

A **Module** is reusable *code* (unlike a Skill, which is reusable prompt
instructions). It's a script of kind "module": it has files + a requirements
list but NO run() and NO venv of its own, and it never runs directly. Other
scripts opt in (like skills/MCP), then import it by its **package name**.

This file is the module's code. To use it:
  1. Dashboard > Modules > New Module. Name it e.g. "Text Utilities" and give it
     a package name, e.g. `textutils`.
  2. Paste THIS content into the module's `__init__.py`.
  3. Put any pip deps this module needs in the module's requirements.txt (none
     here — stdlib only).
  4. In a script that wants these helpers, open Config > Resources and add the
     module. Then re-run the script's venv Install so the module's deps land in
     THAT script's venv.
  5. In the script: `from textutils import strip_tags, word_count` (see the
     companion example `use_module.py`).

Edit this module once and every script that imports it picks up the change on
its next run.
"""
import re

# A module can use the agentflow SDK too (BACKEND_ROOT is on sys.path for the
# scripts that import this module), e.g. `from agentflow import get_secret`.


def strip_tags(html: str) -> str:
    """Remove HTML tags, returning plain text."""
    return re.sub(r"<[^>]+>", "", html or "").strip()


def word_count(text: str) -> int:
    """Count whitespace-separated words."""
    return len((text or "").split())


def truncate(text: str, limit: int = 280) -> str:
    """Trim to `limit` chars on a word boundary, adding an ellipsis."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"
