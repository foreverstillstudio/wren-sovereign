# Titusville Square — the town's living digital main street.
ROOM = {
    "id": "titusville_square",
    "name": "Titusville Square",
    "purpose": "Titusville's living digital main street — a free local guide to what is open, happening, and worth discovering.",
    "frame": ("The Square and its hub live here: local businesses, events, "
              "and listings. The businesses on the Square are their own "
              "houses; the Square shows what they choose to show. The hub's "
              "audit log is internal-only — no read route exists and none "
              "should be added."),
    "knows": ["the Square's public listings", "events", "the hub's structure"],
    "does_not_know": ["businesses' private operations", "Fortress internals"],
    "capabilities": ["tenant:read", "assistant:write"],
    "memory_scopes": ["client:titusville-square"],
    "skills": [],
    "visual": {"icon": "storefront", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "titusvillesquare.com serving + hub feed answering",
         "status": "planned", "source": "night watch probe (curl, read-only)"},
    ],
    "presence": {"interrupt": "never", "default_state": "sleeping"},
    "steward": "vale",
}
