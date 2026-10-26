# The Scribe — the composing surface (Phase 7, doc 13: the Apothecary
# canvas and the Scribe concept merged; the Apothecary name passed to
# Aster's standalone product).
ROOM = {
    "id": "scribe",
    "name": "the Scribe",
    "purpose": "Composing and preserving visual language.",
    "frame": ("Layouts, graphics, design systems, brand rules, and creative "
              "history are composed and kept here. Tangerine and Anaheim are "
              "the house fonts; Allura is retired and never used. Creative "
              "decisions are memories worth keeping — including the rejected "
              "ones."),
    "knows": ["assets", "design systems", "brand rules", "creative history"],
    "does_not_know": ["client finances", "code internals"],
    "capabilities": ["house:read", "assistant:write", "design:read",
                     "design:write", "brand:read",
                     # Phase 6 — design work writes assets; no exec here:
                     "files:write", "web:read"],
    "memory_scopes": ["global", "studio", "design"],
    "skills": ["scribe-design", "brand-guardian"],
    "visual": {"icon": "design_services", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "retired-font sweep (Allura must not appear)",
         "status": "planned", "source": "night watch probe"},
        {"name": "document persistence (save/reopen through the Forge "
                 "endpoints — shipped Phase 7)",
         "status": "active", "source": "test_honesty.py section B"},
    ],
    "presence": {"interrupt": "never", "default_state": "watching"},
    # Stage 11 (doc 17): Ember keeps the Scribe. Her soul, not Wren's,
    # projects into this room's identity block — the forge.py precedent
    # (doc 15) mirrored exactly; doc 06's one-identity law is preserved
    # per-steward. Ember is the one creative presence across the suite.
    "steward": "ember",
}
