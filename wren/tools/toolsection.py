"""
Wren ToolSection Engine v2.0: The Prompt Orchestrator.

This module manages the injection of tool-use guidelines into the kernel prompt.
It ensures that the 'Law of the Tools' is presented only when tools are 
actually offered, providing a lean and focused context for the model.

BEAUTY IS MINIMALISM. ORDER IS EFFICIENCY.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Final

# --- Constants ---

# Root is the folder containing the 'prompts' directory
KERNEL_ROOT: Final = Path(__file__).resolve().parent.parent
RULES_PATH: Final = KERNEL_ROOT / "prompts" / "tool_rules.txt"

class ToolSectionEngine:
    """
    The engine responsible for building the '# Your tools' section of the prompt.
    Implements caching to minimize disk I/O during high-frequency turns.
    """

    def __init__(self) -> None:
        self._cached_rules: Optional[str] = None

    def load_rules(self, path: Path = RULES_PATH) -> str:
        """
        Reads the tool rules from disk. 
        Caches the result to avoid redundant I/O.
        """
        if self._cached_rules is not None:
            return self._cached_rules

        try:
            if not path.is_file():
                return ""
            
            content = path.read_text(encoding="utf-8").strip()
            self._cached_rules = content
            return content
        except OSError as e:
            # In a full implementation, this would call the diagnostic logger
            # For now, we fail silently to ensure the turn still runs
            return ""

    def clear_cache(self) -> None:
        """Forces a reload of the rules file on the next request."""
        self._cached_rules = None

    def build_section(self, schemas: Optional[List[Dict[str, Any]]] = None, 
                     override_rules: Optional[str] = None) -> str:
        """
        Constructs the '# Your tools' block.
        Returns an empty string if no tools are offered.
        """
        # Verify that at least one valid tool is offered
        offered = [
            s for s in (schemas or []) 
            if isinstance(s, dict) and s.get("function", {}).get("name")
        ]
        
        if not offered:
            return ""

        # Use override if provided, otherwise load from cache/disk
        rules = override_rules if override_rules is not None else self.load_rules()
        
        if not rules:
            return ""

        return f"# Your tools\n\n{rules}"

# --- Singleton Access ---

_engine = ToolSectionEngine()

def rules_text(path: Optional[Path] = None) -> str:
    """Public API to retrieve the current rules text."""
    if path:
        return _engine.load_rules(path)
    return _engine.load_rules()

def build_tool_section(schemas: Optional[List[Dict[str, Any]]] = None, 
                      rules: Optional[str] = None) -> str:
    """Public API to construct the tool prompt section."""
    return _engine.build_section(schemas=schemas, override_rules=rules)

def refresh_rules() -> None:
    """Public API to force a reload of the rules from disk."""
    _engine.clear_cache()
