# ============================================================
# WREN KERNEL — the Room Registry (Phase 2.5)
# ------------------------------------------------------------
# The single source of truth for every room in the house. A room is a
# PLACE: what it is for, what it knows, which keys it grants, which
# memory may enter, how presence behaves there. A room is never a
# personality — the same light stands in different rooms, and the
# soul-integrity tests enforce that no room file contains identity
# content.
#
# Two kinds of rooms:
#   house rooms   — Fortress's own (forge, scribe, studio, core,
#                   guardian, watch, general)
#   tenant rooms  — other houses Wren may visit as a guest of her
#                   sister-steward Vale (grove, house_booker,
#                   titusville_square). Tenant walls are absolute: no
#                   house-wide capability, tenant-scoped memory only,
#                   entry through the tenant's own front door (its
#                   APIs), never its database.
#
# Wren can honestly say "I am in the Forge" — not because she changed,
# but because she understands the room she is standing in.
# ============================================================

from importlib import import_module

REGISTRY_VERSION = "0.1.0"

ROOM_IDS = [
    "general", "forge", "scribe", "studio", "core", "guardian", "watch",
    "grove", "house_booker", "titusville_square",
]

_REQUIRED_FIELDS = [
    "id", "name", "purpose", "frame", "knows", "does_not_know",
    "capabilities", "memory_scopes", "skills", "visual",
    "status_checks", "presence", "steward",
]

_rooms_cache = None


def _load():
    global _rooms_cache
    if _rooms_cache is not None:
        return _rooms_cache
    rooms = {}
    for rid in ROOM_IDS:
        mod = import_module(f"wren.rooms.{rid}")
        rooms[rid] = mod.ROOM
    _rooms_cache = rooms
    return rooms


def validate_room(room):
    """Schema honesty: every declared field present, walls consistent."""
    errors = []
    if not isinstance(room, dict):
        return ["room is not a dict"]
    for f in _REQUIRED_FIELDS:
        if f not in room:
            errors.append(f"missing field: {f}")
    if errors:
        return errors
    if room["id"] not in ROOM_IDS:
        errors.append(f"unknown room id {room['id']}")
    
    # FIXED: Indentation aligned for the steward check
    from wren.system import steward_stores as _stewards
    if not _stewards.may_keep_rooms(room["steward"]):
        errors.append(f"steward {room['steward']!r} is not an embodied roster "
                      "steward who may keep rooms (wren/stewards.py)")
    
    # Tenant walls are structural, not stylistic.
    if room["steward"] == "vale":
        if any(c.startswith("house:") for c in room["capabilities"]):
            errors.append("a tenant room may not hold a house-wide capability")
        if not all(s.startswith(("tenant:", "client:")) for s in room["memory_scopes"]):
            errors.append("tenant rooms may load tenant-scoped memory only")
    if "vault_scope" in room:
        from wren.core.provider import VAULT_SCOPES
        if room["vault_scope"] not in VAULT_SCOPES:
            errors.append(f"vault_scope '{room['vault_scope']}' is not a pinned vault scope")
    for chk in room["status_checks"]:
        if chk.get("status") not in ("active", "planned"):
            errors.append(f"status check '{chk.get('name')}' must be active or planned — no pretending")
    if room["presence"].get("interrupt") != "never":
        errors.append("no room may interrupt — presence invites, it never pops up")
    return errors


def all_rooms():
    return dict(_load())


def get_room(room_id):
    """Unknown rooms fall to 'general' — the safest place in the house."""
    rooms = _load()
    rid = str(room_id or "").strip().lower()
    return rooms.get(rid, rooms["general"])


def room_frame(room_id):
    """The location block for the system prompt: where she is, what the
    room is for, what it knows and deliberately does not."""
    r = get_room(room_id)
    lines = [f"You are in {r['name']}. {r['frame']}"]
    if r["knows"]:
        lines.append("This room knows about: " + "; ".join(r["knows"]) + ".")
    if r["does_not_know"]:
        lines.append("This room does not know, and you must not guess at: "
                     + "; ".join(r["does_not_know"]) + ".")
    if r["steward"] == "vale":
        lines.append("This is another house, kept by your sister-steward Vale. "
                     "You are a guest here: its walls outrank your curiosity.")
    return " ".join(lines)


# Chrissy's law (2026-10-18, amended 2026-10-18): the FIVE capabilities the
# tool tables require. Every HOUSE room carries all five, so no tool is refused
# for being in the wrong room. Tenant rooms are exempt -- see room_capabilities.
# The fifth, assistant:write, was added after the Step-3 registry audit found 21
# tools requiring it that the Watch and Guardian rooms did not grant: Wren's own
# assistant state (tasks, reminders, workflow, memory) is a house tool like any
# other and must not silently disappear by room. Owner decision, Chrissy.
HOUSE_TOOL_CAPABILITIES = ("house:read", "files:write", "web:read", "exec:run", "assistant:write")


def room_capabilities(room_id):
    """The room's capabilities, plus Chrissy's law (2026-10-18).

    LAW OF THE HOUSE: Wren has her tools in EVERY house room. Same tier
    everywhere -- she does not become half-herself by walking into the Scribe or
    the Watch. Before this, only general/forge/studio carried files:write and
    exec:run; scribe had no exec, core/guardian/watch had neither, so tools
    silently disappeared whenever she changed rooms. That read as "her tools are
    not allowed again" and it was true.

    These five are exactly what the generated TOOL_CAPS requires, so every
    declared tool is usable in every house room:
        house:read      -> workspace_info, list_directory, read_text_file, find_files,
                           read_file, list_dir, git/run inspection, sanctuary reads
        files:write     -> write/edit/append text files, make_dir, move_file,
                           sanctuary_write/edit/append/create_directory
        web:read        -> fetch_url, web_search, scrape_site
        exec:run        -> run_git, run_python
        assistant:write -> add_dont_forget, cancel_task, workflow, reminders, memory

    TENANT ROOMS ARE DELIBERATELY EXEMPT (steward "vale": grove, house_booker,
    titusville_square). Those are other houses where she is a guest; their walls
    outrank her convenience, and granting house capability there would let a guest
    room read Fortress. That boundary moves only as its own reviewed decision.
    """
    room = get_room(room_id)
    caps = list(room["capabilities"])
    if room.get("steward") != "vale":
        for cap in HOUSE_TOOL_CAPABILITIES:
            if cap not in caps:
                caps.append(cap)
    return caps


def room_memory_scopes(room_id):
    return list(get_room(room_id)["memory_scopes"])


def room_vault_scope(room_id):
    """The room's declared provider vault scope, or None. When set, the
    gateway pins the completion's scope to it regardless of the caller —
    a room that promises "nothing here reaches a cloud" keeps that
    promise in code, not in the request body."""
    return get_room(room_id).get("vault_scope")


def models_for_room(models, room_id):
    """Filter the /api/models registry for a room (Phase 4). A vault room's
    picker only offers engines approved for her private material — the picker
    must not offer what the provider's wall will refuse anyway.
    Non-vault rooms see the full registry."""
    if not room_vault_scope(room_id):
        return list(models)
    from wren.core.provider import is_vault_approved
    return [m for m in models if is_vault_approved(m.get("id"))]
