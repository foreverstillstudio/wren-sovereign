# The Forge — where things are built.
ROOM = {
    "id": "forge",
    "name": "the Forge",
    "purpose": "Building and maintaining systems.",
    "frame": ("Code, repositories, tests, architecture, and deploy "
              "preparation live here. Deploy execution always goes to the "
              "approval desk, and a deployment is only 'done' when the real "
              "platform said so."),
    "knows": ["repositories", "deployments and their verified states",
              "architecture", "tests"],
    "does_not_know": ["private client details unless the keeper grants them",
                      "finances"],
    "capabilities": ["house:read", "assistant:write", "code:read",
                     "code:write", "git:read", "deploy:prepare",
                     # Phase 6 — the tool-layer grants (TOOL_CAPS), declared:
                     "files:write", "web:read", "exec:run"],
    "memory_scopes": ["global", "studio", "project:*"],
    "skills": ["builder", "security-auditor"],
    "visual": {"icon": "code_blocks", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "deploy truth (/api/forge/status)", "status": "active",
         "source": "gates_server.py"},
        {"name": "suite green (test_security + kernel)", "status": "active",
         "source": "test_*.py"},
        {"name": "repo drift vs docs", "status": "planned",
         "source": "night watch probe"},
    ],
    "presence": {"interrupt": "never", "default_state": "watching"},
    # Forge-Hands slice (2026-08-07): Ember keeps the Forge. Her soul,
    # not Wren's, projects into this room's identity block (doc 11,
    # wren/soul.py); doc 06's one-identity law is preserved per-steward.
    "steward": "ember",
}
