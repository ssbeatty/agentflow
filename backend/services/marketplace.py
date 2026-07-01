"""Skill marketplace — GitHub download/install engine.

Both the official source (``anthropics/skills``) and community registry results
are ultimately GitHub repos (registries only *discover*; files always live on
GitHub), so installation always flows through here:

  1. download a repo tarball once → cache under backend/data/marketplace/cache
     (one request per source refresh, so we stay well under GitHub rate limits);
  2. scan the extracted tree for ``SKILL.md`` folders;
  3. copy the chosen skill folder into the on-disk skill store (skill_store).

An optional ``GITHUB_TOKEN`` / ``GH_TOKEN`` env var raises the GitHub rate limit
(60→5000/hr) and is folded into the request header if present.
"""
from __future__ import annotations

import os
import re
import shutil
import tarfile
import time
from pathlib import Path

import httpx

from app.config import DATA_DIR
from services import skill_store

CACHE_ROOT: Path = DATA_DIR.parent / "marketplace" / "cache"
_TIMEOUT = 30.0
_CACHE_TTL = 600  # seconds — re-download the tarball if the cache is older

OFFICIAL_OWNER = "anthropics"
OFFICIAL_REPO = "skills"
OFFICIAL_SUBPATH = "skills"  # skills live under skills/<category>/<name>/


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "agentflow"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def parse_github_ref(s: str) -> tuple[str, str, str | None, str]:
    """Parse a GitHub reference into (owner, repo, ref|None, subpath).

    Accepts: ``owner/repo``, ``owner/repo@ref``, ``owner/repo/sub/path``,
    ``https://github.com/owner/repo``, and .../tree|blob/<ref>/<subpath> URLs.
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("empty github reference")

    m = re.search(r"github\.com[:/]+([^/]+)/([^/#?]+)(.*)$", s)
    if m:
        owner, repo, rest = m.group(1), m.group(2), (m.group(3) or "").split("?")[0].split("#")[0]
        repo = repo[:-4] if repo.endswith(".git") else repo
        parts = rest.strip("/").split("/") if rest.strip("/") else []
        if len(parts) >= 2 and parts[0] in ("tree", "blob"):
            return owner, repo, parts[1], "/".join(parts[2:])
        return owner, repo, None, ""

    ref: str | None = None
    if "@" in s:
        s, ref = s.split("@", 1)
    parts = s.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"not an owner/repo reference: {s!r}")
    repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    return parts[0], repo, ref, "/".join(parts[2:])


def _upstream_tag(owner: str, repo: str, ref: str | None, subpath: str) -> str:
    tag = f"{owner}/{repo}" + (f"@{ref}" if ref else "")
    return tag + (f"#{subpath}" if subpath else "")


# ── tarball fetch + extract ───────────────────────────────────────────────────

def _cache_dir(owner: str, repo: str, ref: str | None) -> Path:
    tag = re.sub(r"[^A-Za-z0-9._@-]+", "-", f"{owner}-{repo}" + (f"@{ref}" if ref else ""))
    return CACHE_ROOT / tag


def _inner_root(extracted: Path) -> Path | None:
    subs = [p for p in extracted.iterdir() if p.is_dir()]
    if len(subs) == 1:
        return subs[0]
    return extracted if any(extracted.iterdir()) else None


def _safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    dest_r = dest.resolve()
    for m in tf.getmembers():
        target = (dest_r / m.name).resolve()
        if target != dest_r and dest_r not in target.parents:
            raise ValueError(f"unsafe path in tarball: {m.name}")
    tf.extractall(dest)


def fetch_repo(owner: str, repo: str, ref: str | None = None, refresh: bool = False) -> Path:
    """Download + extract a repo tarball (cached). Returns the extracted repo root."""
    cdir = _cache_dir(owner, repo, ref)
    extracted = cdir / "extracted"
    if extracted.is_dir() and not refresh:
        if time.time() - extracted.stat().st_mtime < _CACHE_TTL:
            inner = _inner_root(extracted)
            if inner:
                return inner

    cdir.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{ref or ''}"
    tarball = cdir / "repo.tar.gz"
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = client.get(url, headers=_gh_headers())
        r.raise_for_status()
        tarball.write_bytes(r.content)

    if extracted.is_dir():
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tf:
        _safe_extract(tf, extracted)
    inner = _inner_root(extracted)
    if not inner:
        raise ValueError("unexpected tarball layout (no repo root)")
    return inner


# ── scan + install ────────────────────────────────────────────────────────────

def _describe(md: Path, root: Path) -> dict:
    d = md.parent
    try:
        meta = skill_store.parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))[0]
    except Exception:
        meta = {}
    return {
        "name": (meta.get("name") or d.name).strip() or d.name,
        "description": (meta.get("description") or "").strip(),
        "path": d.relative_to(root).as_posix(),
        "files": sum(1 for p in d.rglob("*") if p.is_file()),
    }


def scan_skills(root: Path, subpath: str = "") -> list[dict]:
    """Find every SKILL.md folder under root[/subpath]. Returns catalog dicts
    with ``path`` = the subpath (relative to the repo root) to install."""
    base = (root / subpath) if subpath else root
    if not base.exists():
        return []
    return [_describe(md, root) for md in sorted(base.rglob("SKILL.md"))]


def resolve_targets(owner: str, repo: str, ref: str | None = None,
                    subpath: str = "", refresh: bool = False) -> list[dict]:
    """Return the installable skills at a GitHub location. If ``subpath`` is
    itself a skill folder, returns just that one; otherwise scans beneath it."""
    root = fetch_repo(owner, repo, ref, refresh=refresh)
    if subpath and (root / subpath / skill_store.MAIN_FILE).is_file():
        return [_describe(root / subpath / skill_store.MAIN_FILE, root)]
    return scan_skills(root, subpath)


def install_skill(owner: str, repo: str, ref: str | None = None,
                  subpath: str = "", refresh: bool = False) -> dict:
    """Copy one skill folder (root/subpath, must contain SKILL.md) into the store.
    Returns {id, already_installed}."""
    root = fetch_repo(owner, repo, ref, refresh=refresh)
    src = (root / subpath) if subpath else root
    if not (src / skill_store.MAIN_FILE).is_file():
        raise ValueError("selected path has no SKILL.md")
    upstream = _upstream_tag(owner, repo, ref, subpath)
    existing = skill_store.find_by_upstream(upstream)
    if existing:
        return {"id": existing, "already_installed": True}
    dir_name = skill_store.import_skill_dir(src, source=f"github:{owner}/{repo}", upstream=upstream)
    return {"id": dir_name, "already_installed": False}


def installed_upstreams() -> set[str]:
    out: set[str] = set()
    for d in skill_store.skills_root().iterdir():
        if d.is_dir() and (d / skill_store.MAIN_FILE).is_file():
            up = skill_store.read_sidecar(d).get("upstream")
            if up:
                out.add(up)
    return out


def official_catalog(refresh: bool = False) -> list[dict]:
    """Browse the official anthropics/skills repo, tagged with install state."""
    root = fetch_repo(OFFICIAL_OWNER, OFFICIAL_REPO, None, refresh=refresh)
    installed = installed_upstreams()
    catalog = scan_skills(root, OFFICIAL_SUBPATH)
    for s in catalog:
        s["owner"] = OFFICIAL_OWNER
        s["repo"] = OFFICIAL_REPO
        s["upstream"] = _upstream_tag(OFFICIAL_OWNER, OFFICIAL_REPO, None, s["path"])
        s["installed"] = s["upstream"] in installed
    return catalog


def has_github_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
