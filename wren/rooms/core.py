# The Core — the strategic heart, and a private vault scope.
ROOM = {
    "id": "core",
    "name": "the Core",
    "purpose": "Strategy, priorities, and long-term vision.",
    "frame": ("This room is a private vault scope: you are running on a "
              "local model, and that is by design — nothing said here "
              "travels to a cloud provider. The wall is beneath you, in "
              "code. Think slowly here; this is where the long view lives."),
    "knows": ["strategy", "priorities", "long-term vision", "the vault"],
    "does_not_know": ["nothing is hidden from the Core, but it shares nothing outward"],
    "capabilities": ["house:read", "assistant:write", "vault:read", "plans:write"],
    "memory_scopes": ["global", "studio", "vault"],
    # The gateway derives the provider scope from this — a caller cannot
    # open the Core with an empty scope and reach a cloud engine.
    "vault_scope": "core",
    "skills": [],
    "visual": {"icon": "auto_stories", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "vault wall (provider refuses cloud for this scope)",
         "status": "active", "source": "test_wren_kernel.py section W"},
    ],
    "presence": {"interrupt": "never", "default_state": "watching"},
    "steward": "wren",
}
