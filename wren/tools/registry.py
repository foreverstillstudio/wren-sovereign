"""
Wren Registry Engine v2.0: The Tool Catalog.

This module is the single authoritative reader of the tools registry. 
It derives capabilities, OpenAI schemas, and engine specifications 
from the registry, ensuring the kernel has a consistent view of its 
available toolset.

BEAUTY IS ORDER. TRUTH IS CENTRALIZED.
"""

from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Final, TypedDict, cast

# --- Type Definitions for Registry Rigor ---

class ToolEntry(TypedDict, total=False):
    description: str
    capability: str
    kernel_capability: str
    status: str
    args: Dict[str, Any]

class EngineEntry(TypedDict, total=False):
    capability: str
    runs_on: str
    status: str

class RegistryData(TypedDict):
    tools: Dict[str, ToolEntry]
    engines: Dict[str, EngineEntry]
    planned: Optional[Dict[str, Any]]
    aliases: Optional[Dict[str, Any]]

# --- Constants ---

KERNEL_ROOT: Final = Path(__file__).resolve().parent.parent
REGISTRY_PATH: Final = KERNEL_ROOT / "tools" / "tools.registry.json"

class RegistryEngine:
    """
    The engine responsible for loading and parsing the tool registry.
    Implements caching to prevent redundant disk I/O.
    """

    def __init__(self) -> None:
        self._cached_reg: Optional[RegistryData] = None

    def load(self, path: Path = REGISTRY_PATH) -> RegistryData:
        """Loads the registry from disk and caches the result."""
        if self._cached_reg is not None:
            return self._cached_reg

        try:
            raw_data = json.loads(Path(path).read_text(encoding="utf-8"))
            # Cast to RegistryData to ensure structural consistency
            self._cached_reg = cast(RegistryData, raw_data)
            return self._cached_reg
        except (OSError, json.JSONDecodeError) as e:
            # In a production kernel, this should be logged via diagnostics
            raise RuntimeError(f"Registry corruption detected at {path}: {e}")

    def clear_cache(self) -> None:
        """Forces the engine to reload the registry on the next request."""
        self._cached_reg = None

    def get_tool_capabilities(self) -> Dict[str, str]:
        """
        Returns a map of name -> required capability for every canonical tool and engine.
        This is the authoritative source for tool-capability binding.
        """
        reg = self.load()
        caps: Dict[str, str] = {}

        # Process Tools
        for name, t in reg["tools"].items():
            cap = t.get("kernel_capability") or t.get("capability") or "assistant:write"
            caps[name] = cap

        # Process Engines
        for name, e in reg["engines"].items():
            if e.get("capability"):
                caps[name] = e["capability"]

        return caps

    def get_advertised_schemas(self) -> List[Dict[str, Any]]:
        """
        Generates OpenAI function schemas for tools marked as 'advertised'.
        Acts as the fallback schema generator for the kernel.
        """
        reg = self.load()
        out = []
        
        # Sort by name for deterministic prompt injection
        for name in sorted(reg["tools"].keys()):
            t = reg["tools"][name]
            if t.get("status") != "advertised":
                continue
            
            out.append(self._generate_schema(name, t))
        
        return out

    def _generate_schema(self, name: str, entry: ToolEntry) -> Dict[str, Any]:
        """Constructs a standard OpenAI function schema from a registry entry.

        A registry entry may carry a full `parameters` JSON Schema (authoritative,
        matching the desktop executor's own validation). If absent, a minimal
        schema is derived from the legacy `args` map.
        """
        description = entry.get("description") or name.replace("_", " ").strip()
        parameters = entry.get("parameters")
        if parameters is None:
            args = entry.get("args") or {}
            properties = {k: {"type": "string"} for k in args}
            parameters = {
                "type": "object",
                "properties": properties,
                "required": list(properties.keys()),
                "additionalProperties": False,
            }
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
            "runs_on": entry.get("runs_on"),
            "gated": bool(entry.get("gated", False)),
        }

    def get_sanctuary_specs(self) -> Dict[str, EngineEntry]:
        """Returns a map of Sanctuary-compatible engine specifications."""
        reg = self.load()
        return {
            name: e
            for name, e in reg["engines"].items()
            if e.get("runs_on") == "sanctuary" and e.get("status") == "advertised"
        }

    def get_inventory(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Returns counts of capabilities used by tools and engines respectively."""
        reg = self.load()
        tool_caps = Counter(t.get("capability") for t in reg["tools"].values())
        engine_caps = Counter(e.get("capability") for e in reg["engines"].values())
        return dict(tool_caps), dict(engine_caps)

# --- Singleton Access ---

_registry = RegistryEngine()

def load(path: Path = REGISTRY_PATH) -> RegistryData:
    return _registry.load(path)

def tool_caps() -> Dict[str, str]:
    return _registry.get_tool_capabilities()

def advertised_schemas() -> List[Dict[str, Any]]:
    return _registry.get_advertised_schemas()

def sanctuary_specs() -> Dict[str, EngineEntry]:
    return _registry.get_sanctuary_specs()

def capability_inventory() -> Tuple[Dict[str, int], Dict[str, int]]:
    return _registry.get_inventory()

def refresh():
    """Public method to force a registry reload."""
    _registry.clear_cache()
