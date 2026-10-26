# House Booker — the venue-platform product, and Vale's birthplace.
ROOM = {
    "id": "house_booker",
    "name": "House Booker",
    "purpose": "The white-label booking and operations platform for one-of-a-kind venues.",
    "frame": ("The product Vale was born in — the same kernel this house's "
              "intelligence was ported from. Product code and the sales demo "
              "live here; each venue running on it is its own house with its "
              "own keeper, and the platform's shared systems never mix their "
              "data."),
    "knows": ["the product's architecture", "the demo venue",
              "the vale kernel lineage"],
    "does_not_know": ["any real venue's private data", "Fortress internals"],
    "capabilities": ["tenant:read", "assistant:write"],
    "memory_scopes": ["client:house-booker"],
    "skills": ["venue-steward"],
    "visual": {"icon": "home_work", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "demo mode intact (localStorage posture is deliberate)",
         "status": "planned", "source": "night watch probe"},
    ],
    "presence": {"interrupt": "never", "default_state": "sleeping"},
    "steward": "vale",
}
