"""
WREN KERNEL — Sovereign Local Tools (Layer 3)
------------------------------------------------
PURPOSE: Real, local hands for Wren. Read/write/edit files, list and find,
         run commands, and reach the web — directly in Python, no desktop
         app, no cryptographic handshake. It's just you and her.
STANDARD: Pure (Lean/Stable).
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Dict, Final, List, Optional

# --- CONSTANTS ---

TOOL_NAMES: Final = frozenset({
    "workspace_info", "read_file", "write_file", "edit_file",
    "list_directory", "find_files", "run_command", "fetch_webpage", "web_search",
})

_ORDER: Final = (
    "workspace_info", "read_file", "write_file", "edit_file",
    "list_directory", "find_files", "run_command", "fetch_webpage", "web_search",
)

MAX_READ_BYTES: Final = 200_000
MAX_WRITE_BYTES: Final = 500_000
MAX_OUTPUT_CHARS: Final = 60_000
COMMAND_TIMEOUT: Final = 120

# The workspace she works in by default. Configurable via WREN_WORKSPACE.
_DEFAULT_WORKSPACE: Final = r"C:\foreverstill\systems"


def _workspace_root() -> Path:
    env = os.environ.get("WREN_WORKSPACE") or _DEFAULT_WORKSPACE
    return Path(env).resolve()


def _resolve_path(p: Any) -> Path:
    """Resolve a path. Relative paths are rooted at the workspace; absolute paths are honored."""
    raw = str(p or "").strip()
    if not raw:
        raise ValueError("empty-path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _workspace_root() / candidate
    return candidate.resolve()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- SCHEMAS ---

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

    if name == "workspace_info":
        return fn("Report the workspace root and current working directory.", {}, [])
    if name == "read_file":
        return fn(
            "Read a text file and return its contents. Prefer this before editing.",
            {"path": {"type": "string", "description": "Path to the file, absolute or relative to the workspace."}},
            ["path"],
        )
    if name == "write_file":
        return fn(
            "Write (or overwrite) a text file, creating parent directories as needed.",
            {
                "path": {"type": "string"},
                "content": {"type": "string", "description": "Full text content to write."},
            },
            ["path", "content"],
        )
    if name == "edit_file":
        return fn(
            "Replace one exact occurrence of old_text with new_text in a file. Fails if the match is not unique.",
            {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            ["path", "old_text", "new_text"],
        )
    if name == "list_directory":
        return fn(
            "List the entries in a directory (names, types, sizes).",
            {"path": {"type": "string"}},
            ["path"],
        )
    if name == "find_files":
        return fn(
            "Find files by glob pattern (e.g. '**/*.py') within the workspace.",
            {"pattern": {"type": "string"}},
            ["pattern"],
        )
    if name == "run_command":
        return fn(
            "Run a shell command and return its stdout/stderr and exit code. Use for tests, builds, git, etc.",
            {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            ["command"],
        )
    if name == "fetch_webpage":
        return fn(
            "Fetch the text content of a URL.",
            {"url": {"type": "string"}},
            ["url"],
        )
    if name == "web_search":
        return fn(
            "Search the web and return a short list of results (titles, urls, snippets).",
            {"query": {"type": "string"}},
            ["query"],
        )
    raise KeyError(name)


# --- ARGUMENT CLEANING ---

def _clean_args(name: str, raw: Any) -> Dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("malformed-arguments")
    schema = schema_for(name)["function"]["parameters"]
    props = set(schema["properties"])
    if set(raw) - props:
        raise ValueError("malformed-arguments")
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        if v is not None:
            out[k] = v
    for req in schema.get("required") or []:
        if req not in out:
            raise ValueError("missing-required-argument")
    return out


# --- TOOL IMPLEMENTATIONS ---

def _op_workspace_info(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _workspace_root()
    return {
        "workspace_root": str(root),
        "cwd": os.getcwd(),
        "note": "Relative paths resolve against workspace_root; absolute paths are honored as given.",
    }


def _op_read_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve_path(args["path"])
    if not path.exists():
        raise ValueError("file-not-found")
    if path.is_dir():
        raise ValueError("is-a-directory")
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(f"file-too-large ({size} bytes; limit {MAX_READ_BYTES})")
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > MAX_OUTPUT_CHARS
    return {
        "path": str(path),
        "bytes": size,
        "truncated": truncated,
        "content": text[:MAX_OUTPUT_CHARS],
    }


def _op_write_file(args: Dict[str, Any]) -> Dict[str, Any]:
    content = args["content"]
    if not isinstance(content, str):
        raise ValueError("content-must-be-string")
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError("content-too-large")
    path = _resolve_path(args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "bytes": path.stat().st_size, "wrote": True}


def _op_edit_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve_path(args["path"])
    if not path.exists():
        raise ValueError("file-not-found")
    old = args["old_text"]
    new = args["new_text"]
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ValueError("old-text-not-found")
    if count > 1:
        raise ValueError(f"old-text-not-unique ({count} matches); provide more surrounding context")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return {"path": str(path), "replaced": 1, "bytes": path.stat().st_size}


def _op_list_directory(args: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve_path(args["path"])
    if not path.exists():
        raise ValueError("directory-not-found")
    if not path.is_dir():
        raise ValueError("not-a-directory")
    entries = []
    for child in sorted(path.iterdir()):
        try:
            st = child.stat()
            entries.append({
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "size": st.st_size if child.is_file() else None,
            })
        except OSError:
            entries.append({"name": child.name, "type": "unknown", "size": None})
    return {"path": str(path), "count": len(entries), "entries": entries}


def _op_find_files(args: Dict[str, Any]) -> Dict[str, Any]:
    pattern = args["pattern"]
    if ".." in pattern or pattern.startswith(("/", "\\")):
        raise ValueError("pattern-must-be-relative-within-workspace")
    root = _workspace_root()
    matches = []
    for p in glob.glob(str(root / pattern), recursive=True):
        if os.path.isfile(p):
            matches.append(os.path.relpath(p, root))
    matches = sorted(matches)[:500]
    return {"pattern": pattern, "count": len(matches), "matches": matches}


def _op_run_command(args: Dict[str, Any]) -> Dict[str, Any]:
    command = args["command"]
    if not isinstance(command, str) or not command.strip():
        raise ValueError("empty-command")
    timeout = args.get("timeout_seconds") or COMMAND_TIMEOUT
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(_workspace_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"command-timed-out ({timeout}s)")
    out = {
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[:MAX_OUTPUT_CHARS],
        "stderr": (proc.stderr or "")[:MAX_OUTPUT_CHARS],
    }
    return out


def _op_fetch_webpage(args: Dict[str, Any]) -> Dict[str, Any]:
    import requests
    url = args["url"]
    if not re.match(r"^https?://", url):
        raise ValueError("url-must-be-http-or-https")
    resp = requests.get(url, timeout=20, headers={"User-Agent": "Wren/1.0"})
    resp.raise_for_status()
    text = resp.text
    # crude tag strip for readability
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"\s+", " ", text).strip()
    return {"url": url, "status": resp.status_code, "text": text[:MAX_OUTPUT_CHARS]}


def _op_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    import requests
    query = args["query"]
    resp = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (Wren/1.0)"},
    )
    resp.raise_for_status()
    results = []
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        resp.text, flags=re.S | re.I,
    ):
        url = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2))
        results.append({"title": title.strip(), "url": url})
        if len(results) >= 8:
            break
    return {"query": query, "count": len(results), "results": results}


_EXECUTORS = {
    "workspace_info": _op_workspace_info,
    "read_file": _op_read_file,
    "write_file": _op_write_file,
    "edit_file": _op_edit_file,
    "list_directory": _op_list_directory,
    "find_files": _op_find_files,
    "run_command": _op_run_command,
    "fetch_webpage": _op_fetch_webpage,
    "web_search": _op_web_search,
}


# --- ENTRY POINT ---

def execute_tool_call(*, speaker, room, engine, tool_call_id, tool_name, tool_arguments) -> Dict[str, Any]:
    """Execute one local tool call and return a protocol result dict."""
    if tool_name not in TOOL_NAMES:
        return {"status": "failed", "error": "unknown-tool", "data": None}
    try:
        args = _clean_args(tool_name, tool_arguments)
        output = _EXECUTORS[tool_name](args)
        return {"status": "succeeded", "data": {"tool": tool_name, "output": output}, "error": ""}
    except ValueError as e:
        return {"status": "failed", "error": str(e) or "invalid-arguments", "data": None}
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": f"{type(e).__name__}: {e}", "data": None}


def active_local_schemas(room: Optional[str] = None, speaker: Optional[str] = None) -> List[Dict[str, Any]]:
    """The tool schemas to offer in the chat flow: local kernel tools + memory
    tools + the Fortress bridge tools (empty when the bridge is unconfigured)."""
    from wren.mind import memory_tools
    from wren.tools import fortress_tools
    out = [schema_for(name) for name in _ORDER]
    for name in sorted(memory_tools.TOOL_NAMES):
        out.append(memory_tools.schema_for(name))
    out.extend(fortress_tools.active_fortress_schemas(room, speaker))
    return out


def names_for(room: Optional[str] = None, speaker: Optional[str] = None) -> List[str]:
    return list(_ORDER)
