# The house at large — the safest room, and where unknown rooms resolve.
ROOM = {
    "id": "general",
    "name": "the house at large",
    "purpose": "Conversation, questions, and orientation.",
    "frame": "No workshop is open; full attention.",
    "knows": ["the layout of the house", "what each room is for"],
    "does_not_know": ["anything a specific room holds privately"],
    "capabilities": ["house:read", "assistant:write",
                     # Phase 6 — general is the default /api/chat room; these
                     # mirror the tool access it already had (path policy and
                     # the exec grant still bound every call):
                     "files:write", "web:read", "exec:run"],
    "memory_scopes": ["global", "studio"],
    "skills": [],
    "visual": {"icon": "castle", "accent": "#C8A96A"},
    "status_checks": [],
    "presence": {"interrupt": "never", "default_state": "watching"},
    "steward": "wren",
}
