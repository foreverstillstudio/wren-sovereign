# The Studio — where Forever Still Studio runs.
ROOM = {
    "id": "studio",
    "name": "the Studio",
    "purpose": "Running Forever Still Studio.",
    "frame": ("Clients, proposals, communications, and operations live here. "
              "Everything outward-facing is a draft in the keeper's voice "
              "until approved. Never quote prices you cannot verify against "
              "the package sheet; the price floor is a policy, not a "
              "suggestion. Client walls hold even inside the studio: one "
              "client's private details never inform another's work."),
    "knows": ["clients", "proposals", "operations", "the package structure"],
    "does_not_know": ["one client's private data while serving another",
                      "code internals"],
    "capabilities": ["house:read", "assistant:write", "clients:read",
                     "drafts:write", "brand:read",
                     # Phase 6 — the studio builds client sites through the
                     # tool layer; these mirror that real, existing behavior:
                     "files:write", "web:read", "exec:run"],
    "memory_scopes": ["global", "studio", "client:*"],
    "skills": ["client-communication", "brand-guardian",
               "studio-prospect-research", "site-audit"],
    "visual": {"icon": "design_services", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "drafts awaiting approval", "status": "planned",
         "source": "approval desk (phase 4)"},
    ],
    "presence": {"interrupt": "never", "default_state": "watching"},
    "steward": "wren",
}
