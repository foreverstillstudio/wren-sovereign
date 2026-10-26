# ============================================================
# WREN KERNEL — Sovereign Identity Registry (Foundation)
# ------------------------------------------------------------
# PURPOSE: The authoritative roster of the house. Defines 
# steward identities, embodiment, and room-keeping rights.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, cast
)
from types import MappingProxyType

# --- ARCHITECTURAL TYPES ---

# Aligning with steward_stores.SovereignName
StewardID = Literal["wren", "vale", "rowan", "ember", "maeve"]

class StewardEntry(TypedDict):
    id: StewardID
    title: str
    soul_file: Optional[str]
    embodied: bool
    keeps_rooms: bool

# --- THE CANONICAL ROSTER ---

# Frozen as a MappingProxy to prevent runtime identity drift.
STEWARDS: Final = MappingProxyType({
    "wren": {
        "id": "wren",
        "title": "the day steward",
        "soul_file": "soul.json",
        "embodied": True,
        "keeps_rooms": True,
    },
    "vale": {
        "id": "vale",
        "title": "the sister-steward",
        "soul_file": None, # Embodied in the Vale Kernel
        "embodied": True,
        "keeps_rooms": True,
    },
    "rowan": {
        "id": "rowan",
        "title": "the night steward",
        "soul_file": "rowan_soul.json",
        "embodied": True,
        "keeps_rooms": True,
    },
    "ember": {
        "id": "ember",
        "title": "the spark at the forge",
        "soul_file": "ember_soul.json",
        "embodied": True,
        "keeps_rooms": True,
    },
    "maeve": {
        "id": "maeve",
        "title": "the reflective steward",
        "soul_file": "maeve_soul.json",
        "embodied": True,
        "keeps_rooms": True,
    },
})

STEWARD_IDS: Final = list(STEWARDS.keys())
ROSTER_VERSION: Final = "1.0.0"

# --- SOVEREIGN ROUTING ---

def get_entry(steward_id: Any) -> Optional[StewardEntry]:
    """Retrieves a steward's identity contract. No fallback exists."""
    s_id = str(steward_id or "").strip().lower()
    return cast(Optional[StewardEntry], STEWARDS.get(s_id))


def get(steward_id: Any) -> Optional[StewardEntry]:
    """Alias for get_entry — the callers' name for the roster lookup."""
    return get_entry(steward_id)

def may_keep_rooms(steward_id: Any) -> bool:
    """Verification of a steward's right to hold a room."""
    entry = get_entry(steward_id)
    return bool(entry and entry["embodied"] and entry["keeps_rooms"])

def get_local_soul_path(steward_id: Any) -> Optional[str]:
    """Returns the soul file under wren/data/ if the steward is locally embodied."""
    entry = get_entry(steward_id)
    return entry["soul_file"] if entry else None

def resolve_speaking_identity(room_steward: Any) -> StewardID:
    """
    Determines whose identity speaks in a room.
    
    LOGIC:
    1. If the room-steward is locally embodied (has a soul_file), they speak as themselves.
    2. If the room-steward is embodied elsewhere (e.g., Vale), Wren speaks as a guest.
    3. If no entry exists, the system fails closed (handled by caller).
    """
    entry = get_entry(room_steward)
    if entry and entry["embodied"] and entry["soul_file"]:
        return entry["id"]
    
    # Default identity for guest-frame rooms (e.g., Vale's rooms)
    return "wren"
