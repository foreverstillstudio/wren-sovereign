# The Grove at Spring Hill — a tenant house, kept by Vale.
# PRODUCTION REALITY: the Grove's database is REAL client data. Fortress
# enters only through the tenant's own front door (its APIs, Vale's tools)
# — never its database, never migrations, never seeds.
ROOM = {
    "id": "grove",
    "name": "the Grove at Spring Hill",
    "purpose": "Serving the venue.",
    "frame": ("A restored 1908 Tudor estate venue in Titusville, kept day to "
              "day by Vale. Venue operations, bookings, tours, and events "
              "live here — reached only through the venue's own systems. "
              "Its owners are the keepers of this room, not you."),
    "knows": ["venue operations", "bookings", "tour interest", "events",
              "what Vale surfaces"],
    "does_not_know": ["Fortress internals", "other clients", "the studio's books"],
    "capabilities": ["tenant:read", "assistant:write"],
    "memory_scopes": ["client:grove"],
    "skills": ["venue-steward"],
    "visual": {"icon": "villa", "accent": "#C8A96A"},
    "status_checks": [
        {"name": "site answering on groveatspringhill.com",
         "status": "active",
         "source": "night watch sites_up probe (rookery_config.json, "
                   "read-only curl — shipped Phase 7)"},
    ],
    "presence": {"interrupt": "never", "default_state": "sleeping"},
    "steward": "vale",
}
