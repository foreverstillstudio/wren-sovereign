# ============================================================
# WREN KERNEL — Sovereign Permission Engine (Layer 2)
# ------------------------------------------------------------
# PURPOSE: Enforces the agency ladder (L0-L5) and room-based 
# capability ceilings. The final arbiter of "Can Wren do this?"
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

from enum import IntEnum
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, Set, cast
)
from types import MappingProxyType

from wren.mind import charter
from wren import rooms as _registry
from wren.tools import registry as _tool_registry
from wren.system.stewards import STEWARD_IDS

# --- AGENCY LADDER ---

class AgencyLevel(IntEnum):
    """
    The L0-L5 Trust/Permission Model.
    Numeric values allow for direct comparison (e.g., level >= AgencyLevel.PERFORM).
    """
    OBSERVE = 0
    RECOMMEND = 1
    PREPARE = 2
    PERFORM = 3
    MAINTAIN = 4
    OPERATE = 5

    def __str__(self) -> str:
        return self.name.lower()

# --- PERMISSION CONSTANTS ---

HOUSE_COMPANIONS: Final = frozenset(STEWARD_IDS)

# Every room a request may name: the room registry plus the sanctuary
# "wren" room (normalize_room resolves "room:wren" -> "wren").
ROOMS: Final = frozenset(_registry.ROOM_IDS) | frozenset({"wren"})

# FIX: Changed MappingProxyType to frozenset because this is a set of keys, not a mapping.
_FINANCE_KEYS: Final = frozenset({
    "amount", "balance", "price", "cost", "spend", "budget", "revenue",
    "paid", "payment", "payments", "invoice_total", "rate",
})

# --- SOVEREIGN PERMISSIONS ENGINE ---

class PermissionEngine:
    """
    Centralized arbiter for capability and agency validation.
    Implements a fail-closed security model.
    """
    
    @staticmethod
    def normalize_room(room: Any) -> str:
        """Single, strict path for room normalization."""
        r = str(room or "").strip().lower()
        # Handle the Sanctuary naming convention
        if r == "room:wren":
            r = "wren"
        # Fail-safe to general
        return r if r in _registry.ROOM_IDS or r == "wren" else "general"

    @staticmethod
    def get_max_level(kind: str, granted_level: Union[int, AgencyLevel]) -> AgencyLevel:
        """
        Caps the agency level based on the Charter's consequentiality rules.
        Rule: Consequential actions NEVER exceed L2 (PREPARE) without a manual override.
        """
        level = AgencyLevel(max(0, min(int(granted_level), AgencyLevel.OPERATE)))
        
        if charter.is_consequential(kind):
            return AgencyLevel(min(level, AgencyLevel.PREPARE))
        return level

    @staticmethod
    def is_house_room(room: str) -> bool:
        """Verification that a room belongs to the House."""
        r = PermissionEngine.normalize_room(room)
        if r not in _registry.ROOM_IDS and r != "wren":
            return False
        
        # A room is a tenant if it holds no 'house:' capabilities
        caps = _registry.room_capabilities(r)
        return any(str(c).startswith("house:") for c in caps)

    @staticmethod
    def can_use_tool(room: str, tool_name: str, tool_caps: Dict[str, str]) -> bool:
        """
        Sovereign tool-access check.
        1. Room must be a House room.
        2. Tool must be mapped to a capability.
        3. Room must possess that capability.
        """
        normalized_room = PermissionEngine.normalize_room(room)
        
        # Rule: Tenant rooms and unknown rooms are refused all tool access
        if not PermissionEngine.is_house_room(normalized_room):
            return False
        
        # Rule: Sanctuary tools are only reachable from the wren room.
        if str(tool_name).startswith("sanctuary_") and normalized_room != "wren":
            return False

        # Capability Verification
        required_cap = tool_caps.get(tool_name)
        if not required_cap:
            return False # Unmapped tools are refused outright
            
        return required_cap in _registry.room_capabilities(normalized_room)

# --- UTILITY INTERFACE ---

def level_name(level: Union[int, AgencyLevel]) -> str:
    return str(AgencyLevel(level))

def max_level_for_action(kind: str, granted_level: int) -> int:
    return int(PermissionEngine.get_max_level(kind, granted_level))

def normalize_room(room: Any) -> str:
    return PermissionEngine.normalize_room(room)


def canonical_room(room: Any) -> str:
    """Canonical room name: the sanctuary "room:wren" convention resolves to "wren"."""
    r = str(room or "").strip().lower()
    return "wren" if r in ("wren", "room:wren") else r

def room_can(room: Any, capability: str) -> bool:
    return capability in _registry.room_capabilities(PermissionEngine.normalize_room(room))

def is_house_room(room: Any) -> bool:
    return PermissionEngine.is_house_room(room)

def can_use_tool(room: Any, tool_name: str, tool_caps: Dict[str, str]) -> bool:
    return PermissionEngine.can_use_tool(room, tool_name, tool_caps)

def redact_finance(value: Any, room: Any) -> Any:
    """Recursive redaction of financial keys for unauthorized rooms."""
    normalized_room = PermissionEngine.normalize_room(room)
    if room_can(normalized_room, "finance:read"):
        return value

    def walk(v: Any) -> Any:
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {
                k: ("(restricted)" if k in _FINANCE_KEYS else walk(x)) 
                for k, x in v.items()
            }
        return v

    return walk(value)

# Global Capability Map (Generated from Registry)
TOOL_CAPS: Final = _tool_registry.tool_caps()
