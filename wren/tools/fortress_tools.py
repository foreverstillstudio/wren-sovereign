"""
WREN KERNEL — Fortress bridge executor (Layer 3)
------------------------------------------------
Wren's hands on the Fortress (Chrissy's PC). These tools are prefixed
`fortress_` to stay distinct from her local (Sanctuary) tools, and every
call is signed with the shared secret the sentinel verifies.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Final, List, Optional

import requests

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://192.168.40.96:5002").rstrip("/")
BRIDGE_SECRET = os.environ.get("WREN_BRIDGE_SECRET", "").strip()

TOOL_NAMES: Final = frozenset({
    "fortress_system_vitals", "fortress_gpu_metrics",
    "fortress_read_file", "fortress_write_file", "fortress_edit_file",
    "fortress_list_directory", "fortress_find_files", "fortress_run_command",
    "fortress_palette_extractor", "fortress_optimize_web_assets",
    "fortress_ollama_run_inference",
})

_SENTINEL_NAME = {n: n[len("fortress_"):] for n in TOOL_NAMES}
_ORDER = tuple(sorted(TOOL_NAMES))


def _bridge_available() -> bool:
    return bool(BRIDGE_URL and BRIDGE_SECRET)


def schema_for(name: str) -> Dict[str, Any]:
    def fn(desc: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": props,
                    "required": required,
                },
            },
        }

    if name == "fortress_system_vitals":
        return fn("Read system vitals (CPU, RAM, disk, boot time) on the Fortress (Chrissy's PC).", {}, [])
    if name == "fortress_gpu_metrics":
        return fn("Read GPU metrics (name, load, VRAM, temperature) on the Fortress.", {}, [])
    if name == "fortress_read_file":
        return fn("Read a text file on the Fortress.", {"path": {"type": "string"}}, ["path"])
    if name == "fortress_write_file":
        return fn("Write a text file on the Fortress.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])
    if name == "fortress_edit_file":
        return fn("Replace one exact, unique text block in a file on the Fortress.",
                  {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
                  ["path", "old_text", "new_text"])
    if name == "fortress_list_directory":
        return fn("List a directory on the Fortress.", {"path": {"type": "string"}}, ["path"])
    if name == "fortress_find_files":
        return fn("Find files by glob pattern within the Fortress workspace.", {"pattern": {"type": "string"}}, ["pattern"])
    if name == "fortress_run_command":
        return fn("Run a bounded command on the Fortress (allowlisted executables).", {"command": {"type": "array", "items": {"type": "string"}}}, ["command"])
    if name == "fortress_palette_extractor":
        return fn("Extract a color palette from an image on the Fortress.", {"path": {"type": "string"}}, ["path"])
    if name == "fortress_optimize_web_assets":
        return fn("Optimize an image to WebP on the Fortress.", {"path": {"type": "string"}}, ["path"])
    if name == "fortress_ollama_run_inference":
        return fn("Run a local Ollama inference on the Fortress.", {"model": {"type": "string"}, "prompt": {"type": "string"}}, ["prompt"])
    raise KeyError(name)


def execute_tool_call(*, speaker, room, engine, tool_call_id, tool_name, tool_arguments) -> Dict[str, Any]:
    """Forward one tool call to the Fortress sentinel and return its result."""
    if tool_name not in TOOL_NAMES:
        return {"status": "failed", "error": "unknown-tool", "data": None}
    if not _bridge_available():
        return {"status": "failed", "error": "fortress-bridge-not-configured", "data": None}
    endpoint = _SENTINEL_NAME[tool_name]
    try:
        resp = requests.post(
            f"{BRIDGE_URL}/api/bridge/{endpoint}",
            json={"args": tool_arguments if isinstance(tool_arguments, dict) else {}},
            headers={"X-Bridge-Token": BRIDGE_SECRET},
            timeout=90,
        )
    except requests.RequestException as e:
        return {"status": "failed", "error": f"fortress-unreachable: {type(e).__name__}", "data": None}
    if resp.status_code == 401:
        return {"status": "failed", "error": "fortress-bridge-unauthorized", "data": None}
    if resp.status_code == 404:
        return {"status": "failed", "error": "fortress-tool-not-found", "data": None}
    try:
        return resp.json()
    except Exception:
        return {"status": "failed", "error": "fortress-bad-response", "data": None}


def active_fortress_schemas(room: Optional[str] = None, speaker: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fortress tool schemas to offer (empty when the bridge is unconfigured)."""
    if not _bridge_available():
        return []
    return [schema_for(n) for n in _ORDER]
