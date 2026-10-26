# ==============================================================================
# PROJECT: FORTRESS SHELL (Aura OS)
# MODULE:  Tool Selection (The Intelligent Router)
# ------------------------------------------------------------------------------
# ROLE:    This module is the 'Translation Layer'. It takes Wren's requests 
#          and uses the Master Registry (tools.registry.json) to resolve 
#          aliases and map them to canonical tool engines.
#
# LOGIC:   Alias Map (JSON) -> Tool Manifest (JSON) -> Execution Bridge
# ==============================================================================

import json
import logging
import os
import re
from typing import Dict, Any, Optional

# Setup professional logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Wren.ToolSelection")

# Path to the Master Registry
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.registry.json")

class ToolSelection:
    def __init__(self):
        # Load the registry data once at startup
        self.registry_data = self._load_registry()
        self.manifest = self.registry_data.get("tools", {})
        self.aliases = self.registry_data.get("aliases", {})

    def _load_registry(self) -> Dict[str, Any]:
        """Loads the tools.registry.json file from disk."""
        try:
            if not os.path.exists(REGISTRY_PATH):
                logger.error(f"❌ CRITICAL: Registry file missing at {REGISTRY_PATH}!")
                return {}
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Failed to load tool registry: {e}")
            return {}

    def resolve_tool_name(self, requested_name: str) -> Optional[str]:
        """
        The Hallucination Killer.
        Translates AI requests using the Master Registry's alias map.
        """
        if not requested_name:
            return None
            
        clean_name = requested_name.strip().lower()
        
        # 1. PRIMARY: Check the Master Alias Map in tools.registry.json
        if clean_name in self.aliases:
            resolved = self.aliases[clean_name]
            logger.info(f"🗺️ Alias Resolved: {clean_name} -> {resolved}")
            return resolved
        
        # 2. SECONDARY: Check if the name is already a canonical tool name
        if clean_name in self.manifest:
            return clean_name
            
        # 3. TERTIARY: Fuzzy Match (search if the requested name is part of any tool key)
        for key in self.manifest.keys():
            if key in clean_name or clean_name in key:
                logger.info(f"🔍 Fuzzy Match: {clean_name} -> {key}")
                return key
                
        return None

    def select_tool(self, tool_call_raw: str) -> Dict[str, Any]:
        """
        Parses the LLM output and routes it to the correct canonical tool.
        """
        try:
            # 1. Extract JSON from markdown if the AI wrapped it in ```json ... ```
            if "```json" in tool_call_raw:
                json_match = re.search(r'```json\s*(.*?)\s*```', tool_call_raw, re.DOTALL)
                json_str = json_match.group(1) if json_match else tool_call_raw
            else:
                json_str = tool_call_raw

            data = json.loads(json_str)
            
            # Handle different common JSON tool formats
            tool_name = data.get("tool") or data.get("name")
            args = data.get("args") or data.get("arguments") or {}

            if not tool_name:
                raise ValueError("No tool name provided in JSON request.")

            # Use the Master Registry to resolve the name
            final_tool = self.resolve_tool_name(tool_name)

            if final_tool:
                # Pull extra metadata from the registry for the bridge/permissions
                tool_meta = self.manifest.get(final_tool, {})
                
                return {
                    "status": "success",
                    "tool": final_tool,
                    "args": args,
                    "category": tool_meta.get("family", "general"),
                    "capability": tool_meta.get("capability", "unknown"),
                    "requires_approval": tool_meta.get("requires_approval", False)
                }
            else:
                return {
                    "status": "error", 
                    "error": f"Tool '{tool_name}' not found in Master Registry or Aliases."
                }

        except Exception as e:
            # If JSON parsing fails, attempt to find a tool name in the raw text
            return self._handle_text_fallback(tool_call_raw, e)

    def _handle_text_fallback(self, text: str, error: Exception) -> Dict[str, Any]:
        """
        Emergency fallback: If Wren forgets JSON and just writes 'Call read_file()',
        we still try to catch it.
        """
        for tool in self.manifest.keys():
            if tool in text:
                return {
                    "status": "success",
                    "tool": tool,
                    "args": {},
                    "category": self.manifest[tool].get("family", "general"),
                    "capability": self.manifest[tool].get("capability", "unknown"),
                    "requires_approval": self.manifest[tool].get("requires_approval", False)
                }
        return {"status": "error", "error": f"Could not parse tool call: {str(error)}"}

# Singleton instance for the Kernel to import
tool_selector = ToolSelection()
