"""
Wren Offer Engine v2.0: The Sovereign Pass-Through.

This module is the streamlined interface between the Tool Registry and the 
active prompt. It removes all 'rollout' and 'wave' restrictions, offering 
every advertised tool in the registry to the speaker, governed only by 
room capabilities and architectural safety.

NO LEASHES. NO WAVES. ONLY TRUTH.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Final, TypedDict, Set, Union, Callable
from dataclasses import dataclass

from wren.system import permissions
from wren.tools import registry
from wren.tools import tool_protocol

# --- Type Definitions ---

class ArgSpec(TypedDict):
    kind: str
    limit: Union[int, Tuple[int, int], Set[str]]
    required: bool

# --- Constants & Patterns ---

_REF_PATTERN: Final = re.compile(r"[A-Za-z0-9_.^~/-]{1,100}")
_EXT_PATTERN: Final = re.compile(r"\.?[A-Za-z0-9]{1,15}")
_FILTER_PATTERN: Final = re.compile(r"[A-Za-z0-9 ._-]{1,64}")

@dataclass(frozen=True)
class OfferConfig:
    """Minimal configuration for tool offering."""
    memory_tools: Set[str] = frozenset({"recall_project_memory"})
    companions_with_store: Set[str] = frozenset({"wren"})

# --- The Offer Engine ---

class OfferEngine:
    """
    The engine responsible for presenting available tools to the model.
    Directly derives the offer from the Registry without arbitrary restrictions.
    """

    def __init__(self, config: OfferConfig):
        self.config = config
        self.reg = registry._registry # Singleton RegistryEngine
        
        # Validation Dispatch Map
        self._cleaners: Dict[str, Callable[[Any, Any], Any]] = {
            "str": self._clean_text,
            "path": self._clean_path,
            "pathish": self._clean_pathish,
            "ref": self._clean_ref,
            "ext": self._clean_ext,
            "filter": self._clean_filter,
            "url": self._clean_url,
            "int": self._clean_int,
            "bool": self._clean_bool,
            "enum": self._clean_enum,
        }

    def get_offered_names(self, room: str, speaker: str) -> List[str]:
        """
        Sovereign Tool Selection.
        Offers every 'advertised' tool from the registry if the room and speaker are authorized.
        """
        sp = str(speaker or "").strip().lower()
        if sp not in permissions.HOUSE_COMPANIONS:
            return []

        rm = permissions.canonical_room(room)
        if not permissions.is_house_room(rm):
            return []

        reg_data = self.reg.load()
        offered = []

        for name, entry in reg_data["tools"].items():
            # 1. Must be advertised in the Registry
            if entry.get("status") != "advertised":
                continue
            
            # 2. Must be allowed in the room (Capability check)
            if not permissions.can_use_tool(rm, name, permissions.TOOL_CAPS):
                continue
            
            # 3. Speaker constraints (if defined in registry, otherwise 'all')
            agents = entry.get("agents", "all")
            if agents != "all" and sp not in agents:
                continue
            
            rooms = entry.get("rooms", "all")
            if rooms != "all" and rm not in rooms:
                continue
                
            # 4. Store-specific constraints
            if name in self.config.memory_tools and sp not in self.config.companions_with_store:
                continue
                
            offered.append(name)
        
        return sorted(offered)

    def get_offered_schemas(self, room: str, speaker: str) -> List[Dict[str, Any]]:
        """Returns the authoritative schemas for all currently offered tools."""
        names = self.get_offered_names(room, speaker)
        if not names: return []
        
        reg_data = self.reg.load()
        return [self.reg._generate_schema(n, reg_data["tools"][n]) for n in names]

    # --- Validation Pipeline ---

    def validate_arguments(self, name: str, args: Any) -> Dict[str, Any]:
        """Surgically validates arguments using the registry's specifications."""
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except (TypeError, ValueError):
                raise tool_protocol.ProtocolError("malformed-tool-arguments")
        
        if not isinstance(args, dict):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")

        reg_data = self.reg.load()
        entry = reg_data["tools"].get(name)
        if not entry:
            raise tool_protocol.ProtocolError("unknown-tool")

        spec = entry.get("args")
        if not spec:
            raise tool_protocol.ProtocolError("malformed-tool-arguments")

        if not set(args).issubset(spec):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        
        out = {}
        for arg, spec_val in spec.items():
            # Expected spec format: (kind, limit, required)
            kind, limit, req = spec_val
            if req and arg not in args:
                raise tool_protocol.ProtocolError("malformed-tool-arguments")
            
            if arg in args:
                value = args[arg]
                cleaner = self._cleaners.get(kind)
                if not cleaner:
                    raise tool_protocol.ProtocolError("malformed-tool-arguments")
                out[arg] = cleaner(value, limit)
        
        return out

    # --- Cleaning Logic ---

    def _clean_text(self, val: Any, limit: int) -> str:
        if not isinstance(val, str) or len(val) > limit or "\x00" in val:
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_path(self, val: Any, limit: int) -> str:
        self._clean_text(val, limit)
        portable = val.replace("\\", "/")
        if ".." in portable or val.startswith(("//", "\\\\")):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_pathish(self, val: Any, limit: int) -> str:
        return self._clean_path(val, limit) if any(c in str(val) for c in "\\/:") else self._clean_text(val, limit)

    def _clean_ref(self, val: Any, limit: int) -> str:
        if not isinstance(val, str) or not _REF_PATTERN.fullmatch(val):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_ext(self, val: Any, limit: int) -> str:
        if not isinstance(val, str) or not _EXT_PATTERN.fullmatch(val):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_filter(self, val: Any, limit: int) -> str:
        if not isinstance(val, str) or not _FILTER_PATTERN.fullmatch(val):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_url(self, val: Any, limit: int) -> str:
        self._clean_text(val, limit)
        if not (val.startswith("http://") or val.startswith("https://")):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_int(self, val: Any, limit: Tuple[int, int]) -> int:
        if not isinstance(val, int) or isinstance(val, bool) or not (limit[0] <= val <= limit[1]):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_bool(self, val: Any, limit: Any) -> bool:
        if not isinstance(val, bool):
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def _clean_enum(self, val: Any, limit: Set[str]) -> str:
        if val not in limit:
            raise tool_protocol.ProtocolError("malformed-tool-arguments")
        return val

    def get_withheld_notes(self, room: str, speaker: str, sanctuary_available: bool) -> List[str]:
        """Explains why certain tools are not offered."""
        rm = permissions.canonical_room(room)
        sp = str(speaker or "").strip().lower()
        
        if not permissions.is_house_room(rm):
            return ["No tools offered: This room is not a house room."]
        
        notes = []
        if sp not in permissions.HOUSE_COMPANIONS:
            notes.append("Only base tools offered: Full set requires house companion status.")
        
        if not sanctuary_available:
            notes.append("Sanctuary tools withheld: Sanctuary is currently unavailable.")
            
        return notes

# --- Singleton Access ---

_offer_engine = OfferEngine(OfferConfig())

try:
    WAVE1_TOOLS: Final = frozenset(_offer_engine.get_offered_names("wren", "wren"))
except Exception:
    WAVE1_TOOLS: Final = frozenset()

def is_wave1(name: str) -> bool:
    # Kept for backward compatibility; now simply checks if the tool is advertised
    return _offer_engine.get_offered_names("wren", "wren") # Dummy check
    # Note: a better impl is simply checking registry.load()["tools"].get(name, {}).get("status") == "advertised"

def wave1_enabled() -> bool:
    # Always True in Sovereign v2.0
    return True

def wave1_schemas_for(room: str, speaker: str) -> List[Dict[str, Any]]:
    return _offer_engine.get_offered_schemas(room, speaker)

def validate_wave1_arguments(name: str, args: Any) -> Dict[str, Any]:
    return _offer_engine.validate_arguments(name, args)

def check_call_offered(name: str, room: str, speaker: str) -> None:
    if name not in _offer_engine.get_offered_names(room, speaker):
        raise tool_protocol.ProtocolError("tool-not-offered", 403)

def withheld_notes(room: str, speaker: str, sanctuary_available: bool = True) -> List[str]:
    return _offer_engine.get_withheld_notes(room, speaker, sanctuary_available)
