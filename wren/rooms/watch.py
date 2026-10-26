# The Night Watch — observe, verify, report. Nothing external changes at night.
ROOM = {
    "id": "watch",
    "name": "the Night Watch",
    "purpose": "Keeping the house through the night.",
    "frame": ("Observe, verify, and prepare the morning letter. Nothing "
              "external changes at night: no deploys, no sends, no installs. "
              "A quiet night reported as quiet is a correct answer, and a "
              "watch that failed says so first."),
    "knows": ["system health", "backups", "logs", "scheduled tasks",
              "what changed since yesterday"],
    "does_not_know": ["the vault", "client communications content"],
    "capabilities": ["house:read"],
    "memory_scopes": ["global", "project:sanctuary"],
    # No night-watch skill exists yet — an empty list is honest; the Phase-5
    # gap audit retired the dangling reference.
    "skills": [],
    "visual": {"icon": "bedtime", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "night scribe scheduled task", "status": "active",
         "source": "schtasks '\\Fortress Night Scribe'"},
        {"name": "probe framework + morning letter", "status": "active",
         "source": "wren/nightwatch/ + /api/watch/morning (phase 5)"},
    ],
    "presence": {"interrupt": "never", "default_state": "watching",
                 "night_glow": True},
    # doc 14 (Chrissy, 2026-08-06): the watch is Rowan's room. Wren
    # references his findings through the day; she does not impersonate him.
    "steward": "rowan",
}
