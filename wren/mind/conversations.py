# ============================================================
# WREN KERNEL — The Sovereign Conversation Engine (Layer 3)
# ------------------------------------------------------------
# PURPOSE: Authoritative persistence of conversation threads,
# turn-level room annotation, and rolling history management.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import contextlib
import functools
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, cast
)

from wren.tools import provenance as provenance_model
from wren.system import steward_stores

# --- ARCHITECTURAL TYPES ---

Role = Literal["user", "assistant"]

class TurnRecord(TypedDict):
    id: str
    role: Role
    content: str
    room: str
    engine: str
    vault: bool
    at: str
    provenance: Dict[str, Any]
    client_turn_id: Optional[str]

class HumanQuestionRecord(TypedDict):
    id: str
    question_turn_id: str
    reason: str
    status: Literal["pending", "answered"]
    created_at: str
    notified_at: Optional[str]
    notification_status: Literal["not_sent", "sent"]
    notification_dedupe_key: Optional[str]
    answered_by_turn_id: Optional[str]
    answered_at: Optional[str]

class ConversationRecord(TypedDict):
    id: str
    title: str
    project: str
    created: str
    updated: str
    turns: List[TurnRecord]
    speaker: Optional[str]
    archived: Optional[bool]
    summary: Optional[str]
    summary_covers: Optional[int]
    summary_at: Optional[str]
    summary_provenance: Optional[Dict[str, Any]]
    reflected_turns: Optional[int]
    reflected_at: Optional[str]
    working_state: Optional[Dict[str, Any]]
    seq: Optional[int]
    human_questions: Optional[List[HumanQuestionRecord]]

class StoreData(TypedDict):
    conversations: List[ConversationRecord]
    seq: int

# --- CONSTANTS ---

STORE_FILENAME: Final = "conversation_store.json"
ROLES: Final = ("user", "assistant")
MAX_TURN_CHARS: Final = 32000
DEFAULT_HISTORY_BUDGET_CHARS: Final = 12000
MIN_HISTORY_BUDGET_CHARS: Final = 1000
SUMMARY_MAX_CHARS: Final = 2000

HUMAN_QUESTION_REASONS: Final = frozenset({
    "explicit_approval", "conflicting_authority", "production_boundary",
    "security_or_privacy_boundary", "money_or_external_commitment",
    "material_preference", "critical_missing_fact",
})

CONVERSATION_ID_PATTERN: Final = re.compile(r"^cnv_[0-9a-f]{12}$")
HUMAN_QUESTION_ID_PATTERN: Final = re.compile(r"^hq_[0-9a-f]{12}$")
CLIENT_TURN_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# --- SOVEREIGN ENGINE ---

class ConversationStoreEngine:
    """
    Singleton Engine managing conversation persistence.
    Implements the 'Turn Snapshot' pattern via internal caching.
    """
    _instance: Optional['ConversationStoreEngine'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConversationStoreEngine, cls).__new__(cls)
            cls._instance._cache: Optional[StoreData] = None
            cls._instance._sig: Optional[tuple] = None
        return cls._instance

    def _get_path(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            STORE_FILENAME
        )

    def _get_signature(self) -> Optional[tuple]:
        try:
            st = os.stat(self._get_path())
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def load(self, force: bool = False) -> StoreData:
        sig = self._get_signature()
        if not force and self._cache is not None and self._sig == sig:
            return self._cache

        from fortress_store import read_store
        steward = steward_stores.current()
        
        raw_data = read_store(
            steward_stores.store_file(self._get_path(), steward),
            {"conversations": [], "seq": 0}, 
            steward
        )
        
        if not isinstance(raw_data, dict):
            raw_data = {"conversations": [], "seq": 0}
            
        self._cache = {
            "conversations": raw_data.get("conversations", []),
            "seq": raw_data.get("seq", 0),
        }
        self._sig = sig
        return self._cache

    def save(self):
        if self._cache is None: return
        from fortress_store import write_store
        steward = steward_stores.current()
        write_store(
            steward_stores.store_file(self._get_path(), steward), 
            self._cache, 
            steward, 
            compact=True
        )
        # Invalidate signature to force reload on next read if necessary
        self._sig = self._get_signature()

    def get_conversation(self, conversation_id: str) -> Optional[ConversationRecord]:
        return next((c for c in self.load()["conversations"] if c.get("id") == conversation_id), None)

# --- UTILITIES ---

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def _clean_content(content: Any) -> str:
    if isinstance(content, list):
        texts = [str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text"]
        content = " ".join(t for t in texts if t) or "[image]"
    content = _CONTROL.sub(" ", str(content if content is not None else ""))
    return content[:MAX_TURN_CHARS]

def _guarded(fn):
    @functools.wraps(fn)
    def _wrapped(*a, **kw):
        from fortress_store import store_lock
        with store_lock(steward_stores.current()):
            return fn(*a, **kw)
    return _wrapped

# --- CORE LOGIC ---

def _create_turn(role: Role, content: Any, room: str, engine: str = "", vault: bool = False, 
                 provenance: Any = None, trusted_provenance: bool = False, client_turn_id: Optional[str] = None) -> TurnRecord:
    cleaned = _clean_content(content)
    created = _now_iso()
    return {
        "id": "trn_" + uuid.uuid4().hex[:12],
        "role": role,
        "content": cleaned,
        "room": str(room or "general"),
        "engine": str(engine or ""),
        "vault": vault is True,
        "at": created,
        "provenance": provenance_model.for_turn(
            role, cleaned, supplied=provenance, trusted=trusted_provenance, created_at=created
        ),
        "client_turn_id": client_turn_id
    }

@_guarded
def append_turn(conversation_id: Optional[str], role: Role, content: Any, room: str, 
                engine: str = "", vault: bool = False, provenance: Any = None, 
                trusted_provenance: bool = False, client_turn_id: Optional[str] = None) -> tuple[Optional[ConversationRecord], Optional[TurnRecord]]:
    if role not in ROLES: return None, None
    
    engine = ConversationStoreEngine()
    data = engine.load(force=True)
    
    # Idempotency Check
    cid_clean = str(client_turn_id).strip() if client_turn_id and CLIENT_TURN_ID_PATTERN.fullmatch(str(client_turn_id).strip()) else None
    if role == "user" and cid_clean:
        for conv in data["conversations"]:
            existing = next((t for t in conv.get("turns", []) if t.get("client_turn_id") == cid_clean), None)
            if existing: return conv, existing

    conv = engine.get_conversation(conversation_id) if conversation_id else None
    if conv is None:
        conv: ConversationRecord = {
            "id": "cnv_" + uuid.uuid4().hex[:12], "title": "", "project": "General",
            "created": _now_iso(), "updated": _now_iso(), "turns": [], "seq": data["seq"],
            "speaker": None, "archived": False, "summary": None, "summary_covers": None,
            "summary_at": None, "summary_provenance": None, "reflected_turns": 0, "reflected_at": None,
            "working_state": None, "human_questions": []
        }
        data["conversations"].append(conv)

    turn = _create_turn(role, content, room, engine, vault, provenance, trusted_provenance, cid_clean)
    conv["turns"].append(turn)
    
    # Update Sequence & Metadata
    data["seq"] += 1
    conv["updated"] = _now_iso()
    conv["seq"] = data["seq"]
    
    if not conv["title"] and role == "user" and turn["content"]:
        conv["title"] = _generate_title(turn["content"])
        
    engine.save()
    return conv, turn

def _generate_title(content: str) -> str:
    text = str(content or "")
    if text.lstrip().startswith("[SYSTEM CONTEXT]") and "[END SYSTEM CONTEXT]" in text:
        text = text.split("[END SYSTEM CONTEXT]", 1)[1]
    text = text.strip()
    if m := re.match(r"^\s*Chrissy:\s*", text):
        text = text[m.end():].strip()
    return " ".join(text.split())[:60] or "(untitled)"

def window(conversation_id: str, exclude_vault: bool, current_room: Optional[str] = None, 
           budget_chars: Optional[int] = None) -> Dict[str, Any]:
    """The character-budgeted slice of conversation history."""
    budget = budget_chars or DEFAULT_HISTORY_BUDGET_CHARS
    conv = ConversationStoreEngine().get_conversation(conversation_id)
    if not conv:
        return {"messages": [], "omitted_vault": 0, "turns": 0, "start": 0, "dropped": 0, "chars": 0}

    # 1. Filter & Annotate
    omitted_vault = 0
    candidates = []
    for idx, t in enumerate(conv["turns"]):
        if exclude_vault and t["vault"]:
            omitted_vault += 1
            continue
        
        content = t["content"]
        if current_room and t["room"] != current_room and content:
            content = f"[said in the {t['room']} room] {content}"
            
        prov = provenance_model.normalize(t["provenance"], content=t["content"], trusted=True)
        candidates.append((idx, {"role": t["role"], "content": content}, prov))

    # 2. Budgeting (Newest first)
    kept = []
    spent = 0
    for i, (idx, m, prov) in enumerate(reversed(candidates)):
        cost = len(m["content"])
        if i > 0 and spent + cost > budget:
            break
        kept.append((idx, m, prov))
        spent += cost
    
    kept.reverse()
    start_idx = kept[0][0] if kept else len(conv["turns"])
    
    return {
        "messages": [m for _, m, _ in kept],
        "evidence": [prov for _, _, prov in kept],
        "indexes": [idx for idx, _, _ in kept],
        "omitted_vault": omitted_vault,
        "turns": len(conv["turns"]),
        "start": start_idx,
        "dropped": len(candidates) - len(kept),
        "chars": spent,
        "budget_chars": budget,
        "summary_chars": len(str(conv.get("summary") or "").strip()) if start_idx else 0
    }

@_guarded
def set_summary(conversation_id: str, text: str, covers: int, now: Optional[str] = None, 
                provenance: Any = None, working_state: Optional[Dict] = None, advance_only: bool = False):
    engine = ConversationStoreEngine()
    data = engine.load(force=True)
    conv = engine.get_conversation(conversation_id)
    if not conv: return None
    
    if advance_only and covers < (conv.get("summary_covers") or 0):
        return None
        
    if working_state:
        conv["working_state"] = working_state
        
    conv["summary"] = str(text or "")[:SUMMARY_MAX_CHARS]
    conv["summary_covers"] = max(covers, 0)
    conv["summary_at"] = now or _now_iso()
    conv["summary_provenance"] = (
        provenance_model.normalize(provenance, content=conv["summary"], trusted=True)
        if isinstance(provenance, dict) else provenance_model.make(
            content=conv["summary"], source_actor="Wren", source_type="inference",
            original_source="rolling conversation summary", observed_by_wren=False,
            provenance_confidence="partial", created_at=conv["summary_at"])
    )
    engine.save()
    return conv["summary_covers"]

def summary_section(conversation_id: str, start: int, engine: Any = None) -> str:
    if not start: return ""
    conv = ConversationStoreEngine().get_conversation(conversation_id)
    if not conv: return ""
    
    text = str(conv.get("summary") or "").strip()
    covers = conv.get("summary_covers") or 0
    
    if (not text or covers < start) and engine:
        try:
            from wren.system import summarize
            summarize.update(conversation_id, engine)
            conv = ConversationStoreEngine().get_conversation(conversation_id)
            text = str(conv.get("summary") or "").strip()
            covers = conv.get("summary_covers") or 0
        except Exception as e:
            print(f"[wren] summary on demand failed ({e})")

    if not text:
        return f"# Earlier in this conversation\n{start} earlier turn(s) are not in your context and no summary exists yet."
    
    prov = provenance_model.normalize(conv.get("summary_provenance"), content=text, trusted=True)
    section = f"# Earlier in this conversation (remembered:not-fresh; provenance: {provenance_model.prompt_label(prov)})\n{text}"
    if covers < start:
        section += f"\n({start - covers} of the earlier turn(s) are not in this summary yet.)"
    return section

# --- REFLECTION MARKERS ---

def reflection_snapshot(conversation_id: str) -> tuple[List[TurnRecord], int]:
    conv = ConversationStoreEngine().get_conversation(conversation_id)
    if not conv: return [], 0
    turns = conv.get("turns", [])
    marker = conv.get("reflected_turns") or 0
    return turns[marker:], len(turns)

@_guarded
def mark_reflected(conversation_id: str, turn_count: Optional[int] = None, now: Optional[str] = None):
    engine = ConversationStoreEngine()
    data = engine.load(force=True)
    conv = engine.get_conversation(conversation_id)
    if not conv: return None
    
    conv["reflected_turns"] = turn_count if turn_count is not None else len(conv.get("turns", []))
    conv["reflected_at"] = now or _now_iso()
    engine.save()
    return conv["reflected_turns"]

def status():
    engine = ConversationStoreEngine()
    path = engine._get_path()
    exists = os.path.isfile(path)
    out = {"exists": exists, "path": os.path.basename(path), "encrypted_at_rest": True}
    if exists:
        out["bytes"] = os.path.getsize(path)
        data = engine.load()
        out["conversations"] = len(data["conversations"])
        out["turns"] = sum(len(c.get("turns", [])) for c in data["conversations"])
    return out


# --- PUBLIC BRIDGE (reconstructed to the callers' expectations) ---

# summarize.py reads the budget under this name.
HISTORY_BUDGET_CHARS: Final = DEFAULT_HISTORY_BUDGET_CHARS


def _new_conversation(project, title=""):
    now = _now_iso()
    return {
        "id": "cnv_" + uuid.uuid4().hex[:12],
        "title": str(title or "")[:60],
        "project": str(project or "General"),
        "created": now, "updated": now, "turns": [], "seq": 0,
        "speaker": None, "archived": False, "summary": None, "summary_covers": None,
        "summary_at": None, "summary_provenance": None, "reflected_turns": 0,
        "reflected_at": None, "working_state": None, "human_questions": [],
    }


def get(conversation_id):
    """One conversation, or None."""
    return ConversationStoreEngine().get_conversation(conversation_id)


@_guarded
def create(project, title=""):
    """A new conversation tagged with its project. Returns its id."""
    engine = ConversationStoreEngine()
    data = engine.load(force=True)
    data["seq"] += 1
    conv = _new_conversation(project, title)
    conv["seq"] = data["seq"]
    data["conversations"].append(conv)
    engine.save()
    return conv["id"]


@_guarded
def rename(conversation_id, title):
    title = _clean_content(title).strip()[:60]
    if not title:
        return None
    engine = ConversationStoreEngine()
    engine.load(force=True)
    conv = engine.get_conversation(conversation_id)
    if not conv:
        return None
    conv["title"] = title
    engine.save()
    return conv


@_guarded
def set_archived(conversation_id, archived=True):
    engine = ConversationStoreEngine()
    engine.load(force=True)
    conv = engine.get_conversation(conversation_id)
    if not conv:
        return None
    conv["archived"] = archived is True
    engine.save()
    return conv


@_guarded
def delete(conversation_id):
    engine = ConversationStoreEngine()
    data = engine.load(force=True)
    before = len(data["conversations"])
    data["conversations"] = [c for c in data["conversations"]
                             if c.get("id") != conversation_id]
    if len(data["conversations"]) == before:
        return False
    engine.save()
    return True


def full(conversation_id, include_vault=True):
    """The whole conversation for a surface to render."""
    conv = get(conversation_id)
    if not conv:
        return None
    turns = conv["turns"] if include_vault else \
        [t for t in conv["turns"] if not t.get("vault")]
    return {**{k: conv[k] for k in ("id", "title", "created", "updated")},
            "turns": turns}


def list_conversations(limit=50, archived=False):
    """Summaries, newest first — no turn content, for fast list rendering."""
    convs = ConversationStoreEngine().load()["conversations"]
    convs = [c for c in convs if bool(c.get("archived")) is bool(archived)]
    out = [{
        "id": c.get("id"),
        "title": c.get("title") or "(untitled)",
        "project": c.get("project"),
        "created": c.get("created", ""),
        "updated": c.get("updated", ""),
        "turns": len(c.get("turns", [])),
        "rooms": sorted({t.get("room", "general") for t in c.get("turns", [])}),
        "seq": c.get("seq", 0),
        "archived": bool(c.get("archived")),
    } for c in convs]
    out.sort(key=lambda c: c.get("seq", 0), reverse=True)
    return out[:limit]


@_guarded
def bind_speaker(conversation_id, speaker):
    """Stamp whose lane this is; first explicit speaker wins."""
    sid = str(speaker or "").strip().lower()
    if not sid:
        return None
    engine = ConversationStoreEngine()
    engine.load(force=True)
    conv = engine.get_conversation(conversation_id)
    if conv is None:
        return None
    if not conv.get("speaker"):
        conv["speaker"] = sid
        engine.save()
    return conv["speaker"]


def vault_exclusion_note(omitted):
    """The honest sentence for a cloud-bound prompt with withheld turns."""
    if not omitted:
        return ""
    return (f"# Withheld from this conversation\n{omitted} earlier turn(s) took "
            "place in the Core, which never leaves this machine. They are not "
            "in your context on this cloud model — do not guess at them; if "
            "the keeper refers to them, say plainly that those turns are "
            "private to the Core.")


@contextlib.contextmanager
def turn_snapshot():
    """A consistent snapshot of the conversation store for one turn.

    The cache is dropped on entry and again on exit, so the turn's first read
    is fresh and the next turn starts clean. No read happens here on entry:
    the steward scope is only established inside the turn."""
    engine = ConversationStoreEngine()
    engine._cache = None
    engine._sig = None
    try:
        yield
    finally:
        engine._cache = None
        engine._sig = None


@_guarded
def dispute_turn_provenance(conversation_id, turn_id, reason):
    """Mark a turn's source attribution as disputed by the keeper."""
    engine = ConversationStoreEngine()
    engine.load(force=True)
    conv = engine.get_conversation(conversation_id)
    if not conv:
        return None
    turn = next((t for t in conv.get("turns", []) if t.get("id") == turn_id), None)
    if not turn:
        return None
    prov = dict(turn.get("provenance") or {})
    prov["disputed_reason"] = str(reason or "")
    prov.setdefault("disputes", [])
    prov["disputes"].append({"reason": str(reason or ""), "at": _now_iso()})
    turn["provenance"] = prov
    engine.save()
    return turn
