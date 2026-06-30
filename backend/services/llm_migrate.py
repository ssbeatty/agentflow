"""One-time data migration: fold legacy per-model `llm_configs` rows into
`channels`, grouped by (provider, api_key, base_url).

Runs on startup (from the FastAPI lifespan). Idempotent and safe:
  - no-op if any channel already exists, or if there are no legacy configs.
The legacy `llm_configs` table is left in place (read-only) as a backup.
"""
from __future__ import annotations


def migrate_llm_configs_to_channels(db) -> int:
    """Returns the number of channels created (0 if nothing to migrate)."""
    from app.models import Channel, LLMConfig

    if db.query(Channel).count() > 0:
        return 0
    try:
        rows = db.query(LLMConfig).order_by(LLMConfig.created_at).all()
    except Exception:
        # legacy table may not exist on a brand-new database — nothing to do.
        return 0
    if not rows:
        return 0

    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in rows:
        key = (r.provider or "openai", r.api_key or "", r.base_url or "")
        g = groups.get(key)
        if g is None:
            g = {"provider": r.provider or "openai", "api_key": r.api_key,
                 "base_url": r.base_url, "models": [], "default_model": None}
            groups[key] = g
            order.append(key)
        if r.model and r.model not in g["models"]:
            g["models"].append(r.model)
        if r.is_default and not g["default_model"]:
            g["default_model"] = r.model

    default_assigned = False
    created = 0
    for i, key in enumerate(order):
        g = groups[key]
        ch = Channel(
            name=g["provider"] if len(order) == 1 else f"{g['provider']}-{i + 1}",
            provider=g["provider"],
            api_key=g["api_key"],
            base_url=g["base_url"],
            models=g["models"],
            priority=0,
            enabled=True,
            is_default=False,
            default_model=None,
            extra_config={},
        )
        if g["default_model"] and not default_assigned:
            ch.is_default = True
            ch.default_model = g["default_model"]
            default_assigned = True
        db.add(ch)
        created += 1

    db.commit()
    return created
