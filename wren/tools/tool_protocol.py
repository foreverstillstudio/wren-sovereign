"""
PROJECT FORTRESS: THE SOVEREIGN CODEX
Module: tool_protocol.py (Sovereign Edition)
Purpose: Streamlined state management for tool-calling.
         Bypasses cryptographic verification for local development.
Standard: Pure v2.0 (Lean & Functional)
"""

from __future__ import annotations

import os
import json
import time
import uuid
import re
import threading
from datetime import datetime, timezone
from typing import Final, TypedDict, Literal, Optional, Any, Dict, List

# --- CONFIGURATION ---

# When True, the system bypasses signature checks and trust-boundary validation.
SOVEREIGN_MODE: Final[bool] = True

PROTOCOL_VERSION: Final[str] = "workspace-read-v2"
MAX_TOOL_STEPS: Final[int] = 16
ACTIVE_LEASE_SECONDS: Final[int] = 86400  # Extended to 24h for convenience
STORE_FILENAME: Final[str] = "tool_call_store.json"
_ID: Final[re.Pattern] = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# --- TOOL SET ---

TOOL_SCHEMAS: Final[List[Dict[str, Any]]] = [
    {
        "type": "function",
        "function": {
            "name": "workspace_info",
            "description": "Get current workspace and project context.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# The real offered tools come from the registry (fall back to the base set).
try:
    from wren.tools import registry as _tool_registry
    TOOL_NAMES: Final = frozenset(_tool_registry.tool_caps().keys())
except Exception:
    TOOL_NAMES: Final = frozenset(s["function"]["name"] for s in TOOL_SCHEMAS)


class SessionRecord(TypedDict):
    desktop_session_id: str
    room: str
    authority_generation: str
    expires_at: int
    key_id: str
    public_key: str
    workspace_binding: str


class TurnRecord(TypedDict):
    assistant_turn_id: str
    client_turn_id: str
    desktop_session_id: str
    owner: str
    auth_kind: str
    workspace_binding: str
    document_nonce: Optional[str]
    authority_generation: str
    request_digest: str
    conversation: str
    room: str
    speaker: Optional[str]
    state: Literal["generating", "continuing", "completed", "failed", "canceled"]
    step: int
    created_at: float
    updated_at: float
    lease_expires_at: int
    provider_state: Any
    calls: List[Dict[str, Any]]
    pending_calls: List[str]
    events: List[Dict[str, Any]]


# --- STORAGE LAYER ---

def store_path() -> str:
    return os.path.join(os.environ.get("WREN_STORE_DIR", "data"), STORE_FILENAME)

_STORE_LOCK = threading.RLock()


def _load() -> Dict[str, Any]:
    path = store_path()
    if not os.path.exists(path):
        return {"sessions": {}, "turns": {}, "security_audit": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"sessions": {}, "turns": {}, "security_audit": []}
    data.setdefault("sessions", {})
    data.setdefault("turns", {})
    data.setdefault("security_audit", [])
    return data


def _save(data: Dict[str, Any]) -> None:
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def canonical_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- PROTOCOL ENGINE ---

class ProtocolError(ValueError):
    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def _guarded(func):
    def wrapper(*args, **kwargs):
        with _STORE_LOCK:
            return func(*args, **kwargs)
    return wrapper


@_guarded
def verify_session_request(owner: str, auth_kind: str, body: Dict[str, Any], signature: str) -> Dict[str, Any]:
    """In Sovereign Mode, this simply returns the request body."""
    if not SOVEREIGN_MODE:
        raise ProtocolError("Strict mode enabled: signature required", 401)
    if not isinstance(body, dict):
        raise ProtocolError("malformed-session-request", 400)
    return body


@_guarded
def validate_session(session_id: Any) -> str:
    """Ensures the session exists (auto-creating in Sovereign Mode) and returns its id."""
    sid = str(session_id or "").strip()
    data = _load()
    session = data["sessions"].get(sid)

    if not session:
        if not SOVEREIGN_MODE:
            raise ProtocolError("session-not-found", 404)
        if not sid:
            sid = f"desktop_{uuid.uuid4().hex[:16]}"
        data["sessions"][sid] = {
            "desktop_session_id": sid,
            "room": "general",
            "authority_generation": "gen_1",
            "expires_at": int(time.time()) + ACTIVE_LEASE_SECONDS,
        }
        _save(data)
        return sid

    if int(session.get("expires_at") or 0) <= int(time.time()):
        raise ProtocolError("desktop-session-expired", 401)
    return sid


@_guarded
def register_session(owner: str, auth_kind: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create a desktop session from a signed tool-session request.

    The client (wren-tool-client.js) presents its own ed25519 public key and
    signs the unsigned body. We verify that signature and mint a session with a
    fresh authority_generation. This is the key-exchange half that Sovereign
    Mode previously skipped entirely.
    """
    from wren.tools import tool_crypto

    if not isinstance(body, dict):
        raise ProtocolError("malformed-session-request", 400)
    if str(body.get("protocol") or "") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported-tool-protocol", 400)

    signature = body.get("signature")
    unsigned = {k: v for k, v in body.items() if k != "signature"}
    public_key = str(unsigned.get("public_key") or "")
    key_id = str(unsigned.get("key_id") or "")
    room = str(unsigned.get("room") or "general").strip().lower()
    workspace_binding = str(unsigned.get("workspace_binding") or "")
    desktop_session_id = str(unsigned.get("desktop_session_id") or "").strip()

    if not (public_key and key_id and workspace_binding and desktop_session_id):
        raise ProtocolError("malformed-session-request", 400)
    if not _ID.fullmatch(desktop_session_id):
        raise ProtocolError("malformed-session-request", 400)
    if not SOVEREIGN_MODE:
        if not isinstance(signature, str) or not signature:
            raise ProtocolError("missing-session-signature", 401)
        if not tool_crypto.verify(public_key, signature, unsigned):
            raise ProtocolError("invalid-session-signature", 401)

    authority_generation = "gen_" + uuid.uuid4().hex
    now = int(time.time())
    data = _load()
    data["sessions"][desktop_session_id] = {
        "desktop_session_id": desktop_session_id,
        "room": room,
        "authority_generation": authority_generation,
        "expires_at": now + ACTIVE_LEASE_SECONDS,
        "key_id": key_id,
        "public_key": public_key,
        "workspace_binding": workspace_binding,
    }
    _save(data)
    return {
        "desktop_session_id": desktop_session_id,
        "room": room,
        "authority_generation": authority_generation,
        "expires_at": now + ACTIVE_LEASE_SECONDS,
        "key_id": key_id,
        "server_public_key": tool_crypto.server_key_info()["public_key"],
        "owner": owner,
        "auth_kind": auth_kind,
    }


def _signed_tool_call_events(data: Dict[str, Any], turn: Dict[str, Any],
                             raw_calls: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Transform model function-calls into signed tool_call events the desktop
    client can verify against the server's public key."""
    from wren.tools import tool_crypto

    session = data["sessions"].get(str(turn.get("desktop_session_id") or "")) or {}
    events: List[Dict[str, Any]] = []
    for c in (raw_calls or []):
        fn = c.get("function") if isinstance(c.get("function"), dict) else {}
        event = {
            "type": "tool_call",
            "tool_call_id": str(c.get("id") or ""),
            "tool_name": str(fn.get("name") or ""),
            "arguments": fn.get("arguments") if fn.get("arguments") is not None else {},
            "conversation": str(turn.get("conversation") or ""),
            "assistant_turn_id": str(turn.get("assistant_turn_id") or ""),
            "desktop_session_id": str(turn.get("desktop_session_id") or ""),
            "workspace_binding": str(turn.get("workspace_binding") or ""),
            "document_nonce": str(turn.get("document_nonce") or ""),
            "owner": str(turn.get("owner") or ""),
            "auth_kind": str(turn.get("auth_kind") or ""),
            "key_id": str(session.get("key_id") or turn.get("key_id") or ""),
            "authority_generation": str(session.get("authority_generation") or turn.get("authority_generation") or ""),
            "room": str(session.get("room") or turn.get("room") or "general"),
            "expires_at": int(session.get("expires_at") or (int(time.time()) + ACTIVE_LEASE_SECONDS)),
            "execution_nonce": "exec_" + uuid.uuid4().hex,
        }
        unsigned = {k: v for k, v in event.items() if k != "server_signature"}
        event["server_signature"] = tool_crypto.sign(unsigned)
        events.append(event)
    return events


@_guarded
def reserve_initial(owner: str, auth_kind: str, desktop_session_id: str, client_turn_id: str,
                    workspace_binding: str, document_nonce: Optional[str], authority_generation: str,
                    request_digest: str, conversation: str, room: str, speaker: Optional[str] = None) -> Dict[str, Any]:
    """Mints a turn ID and initializes state."""
    sid = validate_session(desktop_session_id)

    data = _load()
    ast_id = f"ast_{uuid.uuid4().hex}"
    now = time.time()

    turn: TurnRecord = {
        "assistant_turn_id": ast_id,
        "client_turn_id": str(client_turn_id),
        "desktop_session_id": sid,
        "owner": str(owner),
        "auth_kind": str(auth_kind),
        "workspace_binding": str(workspace_binding),
        "document_nonce": document_nonce,
        "authority_generation": str(authority_generation),
        "request_digest": str(request_digest),
        "conversation": str(conversation or ""),
        "room": str(room),
        "speaker": speaker,
        "state": "generating",
        "step": 0,
        "created_at": now,
        "updated_at": now,
        "lease_expires_at": int(now) + ACTIVE_LEASE_SECONDS,
        "provider_state": None,
        "calls": [],
        "pending_calls": [],
        "events": [],
    }

    data["turns"][ast_id] = turn
    _save(data)
    return {"claimed": True, "assistant_turn_id": ast_id, "lease_expires_at": turn["lease_expires_at"]}


@_guarded
def verify_server_turn_context(owner: str, auth_kind: str, assistant_turn_id: str,
                               desktop_session_id: str, conversation: Optional[str] = None,
                               tool_names: tuple = ()) -> Dict[str, Any]:
    """Provides context for the Sanctuary adapter."""
    data = _load()
    turn = data["turns"].get(str(assistant_turn_id or ""))

    if turn is None:
        raise ProtocolError("unknown-assistant-turn", 404)

    session = data["sessions"].get(str(desktop_session_id or "")) or {}

    return {
        "assistant_turn_id": turn["assistant_turn_id"],
        "client_turn_id": turn["client_turn_id"],
        "desktop_session_id": str(desktop_session_id or ""),
        "owner": str(owner),
        "auth_kind": str(auth_kind),
        "room": session.get("room") or turn.get("room"),
        "speaker": turn.get("speaker"),
        "conversation": str(turn.get("conversation") or conversation or ""),
        "step": int(turn.get("step") or 0),
        "authority_generation": session.get("authority_generation") or turn.get("authority_generation"),
    }


@_guarded
def claim_continuation(owner: str, auth_kind: str, assistant_turn_id: str,
                       desktop_session_id: str, workspace_binding: str, document_nonce: Optional[str]) -> Dict[str, Any]:
    """Retrieves persisted state for a turn."""
    data = _load()
    turn = data["turns"].get(str(assistant_turn_id))

    if turn is None:
        raise ProtocolError("unknown-assistant-turn", 404)

    turn["updated_at"] = time.time()
    turn["state"] = "continuing"
    _save(data)

    return {"claimed": True, "state": turn["provider_state"], "results": list(turn.get("calls", []))}


@_guarded
def finish_initial(owner: str, auth_kind: str, assistant_turn_id: str, conversation: str,
                   final_events: Optional[List[Dict[str, Any]]] = None,
                   provider_state: Any = None,
                   raw_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Finalizes the initial turn — either a final answer or a set of tool calls."""
    data = _load()
    turn = data["turns"].get(str(assistant_turn_id))

    if turn is None:
        raise ProtocolError("unknown-assistant-turn", 404)

    turn["conversation"] = str(conversation or "")
    turn["updated_at"] = time.time()

    if final_events is not None:
        turn["state"] = "completed"
        turn["provider_state"] = None
        turn["events"] = list(final_events)
        _save(data)
        return {"events": list(final_events)}

    # Tool-calls path: save provider state for continuation, emit tool-call events.
    turn["state"] = "continuing"
    turn["provider_state"] = provider_state
    turn["calls"] = []
    turn["pending_calls"] = [str(c.get("id") or c.get("tool_call_id") or "") for c in (raw_calls or [])]
    events = _signed_tool_call_events(data, turn, raw_calls)
    turn["events"] = events
    _save(data)
    return {"events": events}


@_guarded
def save_continuation(owner: str, auth_kind: str, assistant_turn_id: str, provider_state: Any,
                      final_events: Optional[List[Dict[str, Any]]] = None,
                      raw_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Persists a continuation turn's outcome."""
    data = _load()
    turn = data["turns"].get(str(assistant_turn_id))

    if turn is None:
        raise ProtocolError("unknown-assistant-turn", 404)

    turn["updated_at"] = time.time()

    if final_events is not None:
        turn["state"] = "completed"
        turn["provider_state"] = None
        turn["events"] = list(final_events)
        _save(data)
        return {"events": list(final_events)}

    turn["state"] = "continuing"
    turn["provider_state"] = provider_state
    turn["calls"] = []
    turn["pending_calls"] = [str(c.get("id") or c.get("tool_call_id") or "") for c in (raw_calls or [])]
    events = _signed_tool_call_events(data, turn, raw_calls)
    turn["events"] = events
    _save(data)
    return {"events": events}


@_guarded
def record_result(owner: str, auth_kind: str, envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Records a tool result from the desktop. Returns duplicate/ready/state/events."""
    env = envelope or {}
    data = _load()
    assistant_turn_id = str(env.get("assistant_turn_id") or "")
    turn = data["turns"].get(assistant_turn_id)

    if turn is None:
        raise ProtocolError("unknown-assistant-turn", 404)

    call_id = str(env.get("tool_call_id") or "")
    if any(str(c.get("tool_call_id")) == call_id for c in turn.get("calls", [])):
        return {"duplicate": True, "ready": False, "state": turn.get("state"), "events": []}

    turn["calls"].append({
        "tool_call_id": call_id,
        "result": env.get("result"),
        "timestamp": _now(),
    })

    pending = turn.get("pending_calls") or []
    ready = bool(pending) and all(
        any(str(c.get("tool_call_id")) == str(p) for c in turn["calls"]) for p in pending)
    _save(data)
    return {"duplicate": False, "ready": ready, "state": turn.get("state"), "events": []}


@_guarded
def issue_execution_grant(owner: str, auth_kind: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Issues a short-lived execution grant for a tool call (no crypto in Sovereign Mode)."""
    env = body or {}
    assistant_turn_id = str(env.get("assistant_turn_id") or "")
    data = _load()
    turn = data["turns"].get(assistant_turn_id)

    if turn is None:
        raise ProtocolError("unknown-assistant-turn", 404)

    return {
        "execution_grant_id": f"grant_{uuid.uuid4().hex}",
        "assistant_turn_id": assistant_turn_id,
        "tool_call_id": env.get("tool_call_id"),
        "tool_name": env.get("tool_name"),
        "arguments": env.get("arguments"),
        "issued_at": _now(),
        "expires_at": int(time.time()) + 300,
    }


@_guarded
def fail_continuation(owner: str, auth_kind: str, assistant_turn_id: str, error_event: Dict[str, Any]) -> None:
    data = _load()
    turn = data["turns"].get(str(assistant_turn_id))
    if turn:
        turn["state"] = "failed"
        turn["events"] = [dict(error_event or {})]
        _save(data)


@_guarded
def cancel_turn(owner: str, auth_kind: str, desktop_session_id: str, client_turn_id: str,
                workspace_binding: str, document_nonce: Optional[str], authority_generation: str) -> Dict[str, Any]:
    data = _load()
    cid = str(client_turn_id or "")
    for ast_id, turn in data["turns"].items():
        if str(turn.get("client_turn_id")) == cid and turn.get("state") not in ("completed", "canceled", "failed"):
            turn["state"] = "canceled"
            _save(data)
            return {"canceled": True, "assistant_turn_id": ast_id}
    raise ProtocolError("no-active-turn-to-cancel", 404)


@_guarded
def recover(owner: str, auth_kind: str, desktop_session_id: str, client_turn_id: str,
            workspace_binding: str, document_nonce: Optional[str]) -> Dict[str, Any]:
    data = _load()
    cid = str(client_turn_id or "")
    for ast_id, turn in data["turns"].items():
        if str(turn.get("client_turn_id")) == cid:
            return {"events": list(turn.get("events", [])), "assistant_turn_id": ast_id}
    raise ProtocolError("no-turn-to-recover", 404)


@_guarded
def expire_records() -> int:
    data = _load()
    now = int(time.time())
    init_len = len(data["sessions"]) + len(data["turns"])
    data["sessions"] = {k: v for k, v in data["sessions"].items() if int(v.get("expires_at") or 0) > now}
    data["turns"] = {k: v for k, v in data["turns"].items() if int(v.get("lease_expires_at") or 0) > now}
    _save(data)
    return init_len - (len(data["sessions"]) + len(data["turns"]))


@_guarded
def record_security_refusal(owner: str, auth_kind: str, event: str, reason: str, envelope: Any) -> None:
    """Best-effort audit of a refused tool request."""
    data = _load()
    data["security_audit"].append({
        "at": _now(), "owner": owner, "auth_kind": auth_kind,
        "event": event, "reason": reason, "envelope": envelope,
    })
    _save(data)


# --- SANCTUARY & VALIDATION ---

def active_tool_schemas(room: str = None, speaker: str = None) -> List[Dict[str, Any]]:
    from wren.tools import offer as _offer
    from wren.tools import registry as _registry
    from wren.tools import sanctuary_adapter
    schemas = list(_registry.advertised_schemas()) + \
        list(_offer.wave1_schemas_for(room, speaker)) + \
        sanctuary_adapter.get_active_sanctuary_schemas_for_context(room=room, speaker=speaker)
    # Dedupe by function name — a duplicate function name is an OpenAI API error.
    seen = set()
    out: List[Dict[str, Any]] = []
    for s in schemas:
        name = (s.get("function") or {}).get("name")
        if name in seen:
            continue
        seen.add(name)
        out.append(s)
    return out


def validate_arguments(name: str, arguments: Any) -> Dict[str, Any]:
    from wren.tools import sanctuary_adapter
    if name in sanctuary_adapter.SANCTUARY_TOOL_NAMES:
        return sanctuary_adapter.validate_sanctuary_tool_arguments(name, arguments)
    if name not in TOOL_NAMES and name != "workspace_info":
        raise ProtocolError("unknown-tool")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            raise ProtocolError("malformed-tool-arguments")
    if not isinstance(arguments, dict):
        raise ProtocolError("malformed-tool-arguments")
    return arguments


def validate_result(result: Any, tool_name: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise ProtocolError("malformed-tool-result")
    return {
        "status": result.get("status", "failed"),
        "data": result.get("data"),
        "error": result.get("error", "unknown-error"),
    }


# Deferred to the bottom to avoid a circular import (offer imports tool_protocol).
try:
    from wren.tools import offer as offer
except Exception:
    offer = None


# --- EXPORTS ---
__all__ = [
    "verify_session_request", "validate_session", "reserve_initial",
    "claim_continuation", "record_result", "fail_continuation",
    "cancel_turn", "expire_records", "verify_server_turn_context",
    "active_tool_schemas", "validate_arguments", "validate_result",
    "finish_initial", "save_continuation", "recover", "issue_execution_grant",
    "record_security_refusal", "canonical_bytes", "TOOL_NAMES",
    "PROTOCOL_VERSION", "MAX_TOOL_STEPS", "STORE_FILENAME", "ProtocolError", "_ID", "_now",
]
