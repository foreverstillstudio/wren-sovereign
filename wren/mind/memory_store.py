# ============================================================
# WREN KERNEL — The Sovereign Memory Engine (Layer 3)
# ------------------------------------------------------------
# AUTHORITY: The definitive store of truth for Wren's cognitive
# architecture. 
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import functools
import json
import os
import re
import uuid
from datetime import datetime
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, Mapping, cast
)
from types import MappingProxyType

from wren.mind.memory import make_memory, normalize_memory
from wren.tools import provenance as provenance_model
from wren.system import credfilter
from wren.system import steward_stores

# --- ARCHITECTURAL TYPES ---

MemoryType = Literal["personal", "studio", "client", "project", "skill", "design"]
ConfidenceLevel = Literal["stated", "inferred", "assumed"]
MemoryStatus = Literal["active", "corrected", "superseded", "deleted"]
MemoryKind = Literal["fact", "context", "preference", "decision"]
CandidateReason = Literal["vault", "ambiguous", "over-ceiling"]
CandidateStatus = Literal["pending", "kept", "discarded"]

class MemoryRecord(TypedDict):
    id: str
    type: MemoryType
    scope: str
    kind: MemoryKind
    text: str
    source: str
    confidence: ConfidenceLevel
    created: str
    status: MemoryStatus
    supersedes: Optional[str]
    history: List[Dict[str, str]]
    vault: bool
    credential: bool
    provenance: Dict[str, Any]
    retrieval: Optional[Dict[str, Any]]
    expires_on: Optional[str]      # For 'context'
    preference_scope: Optional[str] # For 'preference'
    confirmed: Optional[bool]       # For 'preference'
    why: Optional[str]              # For 'decision'
    guardrail: Optional[str]       # For 'decision'

class MemoryCandidate(MemoryRecord):
    id: str # Starts with cnd_
    record_id: Optional[str]
    reason: CandidateReason
    note: str
    status: CandidateStatus

class MemoryLesson(TypedDict):
    id: str
    text: str
    confirmed: bool
    created_at: str
    house_id: str

class StoreData(TypedDict):
    records: List[MemoryRecord]
    lessons: List[MemoryLesson]
    candidates: List[MemoryCandidate]
    working_state: Optional[Dict[str, Any]]

# --- CONSTANTS & REGEX ---

STORE_FILENAME: Final = "memory_store.json"
_SCOPE_RE: Final = re.compile(r"^(global|(client|project|room):[a-z0-9][a-z0-9._-]*)$")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# --- SOVEREIGN ENGINE ---

class MemoryStoreEngine:
    """
    A Singleton Engine managing the lifecycle of Wren's memory.
    Implements caching to protect encrypted I/O and strict typing to prevent drift.
    """
    _instance: Optional['MemoryStoreEngine'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MemoryStoreEngine, cls).__new__(cls)
            cls._instance._cache: Optional[StoreData] = None
        return cls._instance

    def _get_path(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            STORE_FILENAME
        )

    def load(self, force: bool = False) -> StoreData:
        """Load store with caching. MappingProxyType is not used here as we need mutation."""
        if self._cache is not None and not force:
            return self._cache

        from fortress_store import read_store
        steward = steward_stores.current()
        
        raw_data = read_store(
            steward_stores.store_file(self._get_path(), steward),
            {"records": [], "lessons": [], "candidates": []}, 
            steward
        )
        
        if not isinstance(raw_data, dict):
            raw_data = {"records": [], "lessons": [], "candidates": []}
            
        # Ensure schema integrity
        self._cache = {
            "records": raw_data.get("records", []),
            "lessons": raw_data.get("lessons", []),
            "candidates": raw_data.get("candidates", []),
            "working_state": raw_data.get("working_state"),
        }
        return self._cache

    def save(self):
        """Persist cached state to encrypted store."""
        if self._cache is None:
            return
            
        from fortress_store import write_store
        steward = steward_stores.current()
        write_store(
            steward_stores.store_file(self._get_path(), steward), 
            self._cache, 
            steward
        )

    def get_records(self, include_deleted: bool = True) -> List[MemoryRecord]:
        data = self.load()
        recs = data["records"]
        return recs if include_deleted else [r for r in recs if r.get("status") != "deleted"]

    def get_record_by_id(self, record_id: str) -> Optional[MemoryRecord]:
        return next((r for r in self.load()["records"] if r.get("id") == record_id), None)

# --- UTILITIES ---

def _clean(v: Any, max_len: int) -> str:
    return _CONTROL.sub(" ", str(v if v is not None else "")).strip()[:max_len]

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def _guarded(fn):
    @functools.wraps(fn)
    def _wrapped(*a, **kw):
        from fortress_store import store_lock
        with store_lock(steward_stores.current()):
            return fn(*a, **kw)
    return _wrapped

# --- CORE LOGIC ---

@_guarded
def make_record(
    text: str, 
    type: MemoryType, 
    scope: str, 
    source: str, 
    **kwargs
) -> tuple[Optional[MemoryRecord], List[str]]:
    """Builds a governed record with zero-tolerance validation."""
    errors = []
    text = _clean(text, 1000)
    source = _clean(source, 300)
    
    if not text: errors.append("Empty text.")
    if not source: errors.append("No source, no record.")
    if not _SCOPE_RE.match(str(scope or "")): errors.append(f"Invalid scope: {scope}")
    
    if errors:
        return None, errors

    # Extraction of optional fields with strict defaults
    confidence: ConfidenceLevel = kwargs.get("confidence", "inferred")
    kind: MemoryKind = kwargs.get("kind", "fact")
    
    if confidence not in ["stated", "inferred", "assumed"]:
        errors.append(f"Invalid confidence: {confidence}")
    if kind not in ["fact", "context", "preference", "decision"]:
        errors.append(f"Invalid kind: {kind}")

    if errors: return None, errors

    rec: MemoryRecord = {
        "id": kwargs.get("id") or ("mem_" + uuid.uuid4().hex[:12]),
        "type": type,
        "scope": scope,
        "kind": kind,
        "text": text,
        "source": source,
        "confidence": confidence,
        "created": kwargs.get("created") or _now_iso(),
        "status": "active",
        "supersedes": kwargs.get("supersedes"),
        "history": [{"at": kwargs.get("created") or _now_iso(), "event": "created"}],
        "vault": kwargs.get("vault", False) is True,
        "credential": kwargs.get("credential", False) is True or credfilter.has_credential(text),
        "provenance": (
            provenance_model.normalize(kwargs.get("provenance"), content=text, trusted=True)
            if isinstance(kwargs.get("provenance"), dict)
            else provenance_model.legacy_unknown(text, created_at=kwargs.get("created") or _now_iso())
        ),
        "retrieval": None,
        "expires_on": None,
        "preference_scope": None,
        "confirmed": None,
        "why": None,
        "guardrail": None,
    }

    # Handle Retrieval
    retrieval = kwargs.get("retrieval")
    if retrieval:
        if isinstance(retrieval, dict) and retrieval.get("mode") == "keywords":
            words = retrieval.get("words", [])
            if isinstance(words, (list, tuple)):
                clean_words = sorted({str(w).strip().lower() for w in words if re.fullmatch(r"[a-z0-9']{2,30}", str(w).strip().lower())})
                if 1 <= len(clean_words) <= 40:
                    rec["retrieval"] = {"mode": "keywords", "words": clean_words}
                else:
                    errors.append("Retrieval words must be between 1 and 40.")
        else:
            errors.append("Invalid retrieval shape.")

    # Handle Special Kinds
    if kind == "context":
        rec["expires_on"] = str(kwargs.get("expires_on")) if kwargs.get("expires_on") else None
    elif kind == "preference":
        from wren.mind.memory import PREFERENCE_SCOPES
        rec["preference_scope"] = kwargs.get("preference_scope") if kwargs.get("preference_scope") in PREFERENCE_SCOPES else "situation"
        rec["confirmed"] = kwargs.get("confirmed") is True
    elif kind == "decision":
        rec["why"] = _clean(kwargs.get("why"), 400) if kwargs.get("why") else None
        rec["guardrail"] = _clean(kwargs.get("guardrail"), 300) if kwargs.get("guardrail") else None

    return (rec, []) if not errors else (None, errors)

@_guarded
def add(text: str, type: MemoryType, scope: str, source: str, **kw) -> tuple[Optional[MemoryRecord], List[str]]:
    rec, errors = make_record(text, type, scope, source, **kw)
    if errors: return None, errors
    
    engine = MemoryStoreEngine()
    data = engine.load()
    data["records"].append(rec)
    engine.save()
    return rec, []

@_guarded
def correct(record_id: str, new_text: str, source: str, because: str = "corrected", provenance: Any = None) -> tuple[Optional[MemoryRecord], List[str]]:
    if because not in ("corrected", "superseded"):
        return None, [f"Invalid correction status: {because}"]
    
    engine = MemoryStoreEngine()
    data = engine.load()
    old = engine.get_record_by_id(record_id)
    
    if not old: return None, [f"No record {record_id}"]
    if old["status"] == "deleted": return None, ["Cannot correct deleted memory."]

    new_rec, errors = make_record(
        new_text, old["type"], old["scope"], source,
        confidence="stated",
        kind=old["kind"], 
        vault=old["vault"],
        credential=old["credential"],
        supersedes=old["id"], 
        provenance=provenance,
        why=old.get("why"), 
        guardrail=old.get("guardrail")
    )
    
    if errors: return None, errors
    
    old["status"] = because
    old["history"].append({"at": _now_iso(), "event": f"{because}_by:{new_rec['id']}"})
    data["records"].append(new_rec)
    engine.save()
    return new_rec, []

@_guarded
def delete(record_id: str) -> bool:
    engine = MemoryStoreEngine()
    data = engine.load()
    rec = engine.get_record_by_id(record_id)
    if not rec: return False
    
    rec["status"] = "deleted"
    rec["text"] = ""
    rec["history"].append({"at": _now_iso(), "event": "deleted"})
    engine.save()
    return True

def retrieve(room_scopes: List[str], today: Optional[str] = None, limit: int = 60) -> List[MemoryRecord]:
    """High-fidelity retrieval based on scope enforcement."""
    room_scopes = list(room_scopes or [])
    allow_vault = "vault" in room_scopes
    today = today or datetime.now().strftime("%Y-%m-%d")
    
    engine = MemoryStoreEngine()
    records = engine.get_records(include_deleted=False)
    
    out = []
    for rec in records:
        if rec["status"] != "active": continue
        if not rec["source"]: continue
        if rec["credential"] or credfilter.has_credential(rec["text"]): continue
        if rec["vault"] and not allow_vault: continue
        if rec["kind"] == "context" and rec["expires_on"] and rec["expires_on"] < today: continue
        
        # Scope Matching
        match = False
        for entry in room_scopes:
            if entry == "vault": continue
            if entry == "global" and rec["scope"] == "global": match = True
            elif entry in ["personal", "studio", "client", "project", "skill", "design"] and rec["type"] == entry: match = True
            elif ":" in str(entry):
                prefix, _, name = str(entry).partition(":")
                r_prefix, _, r_name = str(rec["scope"]).partition(":")
                if prefix == r_prefix and (name == "*" or name == r_name): match = True
            if match: break
            
        if match: out.append(rec)
        
    return out[-limit:]

def to_kernel(rec: MemoryRecord):
    """Bridges a sovereign record to the kernel's rendering contract."""
    text = rec["text"]
    if rec["confidence"] == "inferred":
        text = f"[inferred] {text}"
    elif rec["confidence"] == "assumed":
        text = f"[assumed — unverified; flag before relying on this] {text}"
    
    source = ("keeper_correction" if rec["supersedes"] 
              else "keeper_stated" if rec["confidence"] == "stated" 
              else "inferred")
    
    confidence = {"stated": "high", "inferred": "medium", "assumed": "low"}[rec["confidence"]]
    
    return normalize_memory(make_memory(
        id=rec["id"], 
        kind=rec["kind"], 
        text=text,
        created_at=rec["created"], 
        expires_on=rec["expires_on"],
        source=source, 
        confidence=confidence,
        scope=rec["preference_scope"], 
        confirmed=rec["confirmed"],
        provenance=record_provenance(rec)
    ))

def record_provenance(rec: MemoryRecord) -> Dict[str, Any]:
    if "provenance" not in rec:
        return provenance_model.legacy_unknown(rec["text"], created_at=rec["created"])
    return provenance_model.normalize(rec["provenance"], content=rec["text"], trusted=True)

# --- CANDIDATES & LESSONS (Refactored to use Engine) ---

@_guarded
def add_candidate(text: str, type: MemoryType, scope: str, source: str, reason: CandidateReason, **kw) -> tuple[Optional[MemoryCandidate], List[str]]:
    if reason not in ["vault", "ambiguous", "over-ceiling"]:
        return None, ["Invalid candidate reason."]
    
    rec, errors = make_record(text, type, scope, source, **kw)
    if errors: return None, errors
    
    cand: MemoryCandidate = cast(MemoryCandidate, dict(rec))
    cand["id"] = "cnd_" + uuid.uuid4().hex[:12]
    cand["record_id"] = None
    cand["reason"] = reason
    cand["note"] = _clean(kw.get("note", ""), 200)
    cand["status"] = "pending"
    
    engine = MemoryStoreEngine()
    data = engine.load()
    data["candidates"].append(cand)
    engine.save()
    return cand, []

@_guarded
def resolve_candidate(candidate_id: str, decision: Literal["keep", "discard"], text: str = None, by: str = "Chrissy") -> tuple[Optional[MemoryRecord], List[str]]:
    engine = MemoryStoreEngine()
    data = engine.load()
    cand = next((c for c in data["candidates"] if c["id"] == candidate_id), None)
    
    if not cand or cand["status"] != "pending":
        return None, ["Candidate unavailable or already resolved."]

    if decision == "discard":
        cand["status"] = "discarded"
        engine.save()
        return cand, []

    final_text = _clean(text, 1000) if text else cand["text"]
    source = f"{cand['source']} (kept by {by} at the Memory panel)"
    
    if cand.get("supersedes"):
        rec, errors = correct(cand["supersedes"], final_text, source, because="superseded", provenance=cand.get("provenance"))
    else:
        rec, errors = add(final_text, cand["type"], cand["scope"], source, confidence="stated", **{k: v for k, v in cand.items() if k not in ["id", "status", "reason", "note", "record_id"]})
    
    if errors: return None, errors
    
    cand["status"] = "kept"
    cand["record_id"] = rec["id"]
    engine.save()
    return rec, []

@_guarded
def add_lesson(src: Any, house_id: str = "sanctuary") -> tuple[Optional[MemoryLesson], List[str]]:
    from wren.mind.lessons import validate_lesson
    v = validate_lesson(src, house_id=house_id, now=_now_iso())
    if not v["ok"]: return None, v["errors"]
    
    lesson: MemoryLesson = v["lesson"]
    lesson["id"] = lesson.get("id") or ("les_" + uuid.uuid4().hex[:12])
    
    engine = MemoryStoreEngine()
    data = engine.load()
    data["lessons"].append(lesson)
    engine.save()
    return lesson, []

# --- STATE MANAGEMENT ---

@_guarded
def set_working_state(state: Dict[str, Any], source: str = "conversation_rollover"):
    engine = MemoryStoreEngine()
    data = engine.load()
    data["working_state"] = {"state": state, "updated_at": _now_iso(), "source": source}
    engine.save()
    return data["working_state"]

def get_working_state() -> Optional[Dict[str, Any]]:
    return MemoryStoreEngine().load().get("working_state")

@_guarded
def clear_working_state():
    engine = MemoryStoreEngine()
    data = engine.load()
    data.pop("working_state", None)
    engine.save()


# --- PUBLIC BRIDGE (read-only views + path, reconstructed) ---

def store_path():
    """The base memory store path (per-steward resolution happens via steward_stores)."""
    return MemoryStoreEngine()._get_path()


def lessons():
    return MemoryStoreEngine().load().get("lessons", [])


def all_records(include_deleted=False):
    recs = MemoryStoreEngine().load().get("records", [])
    return recs if include_deleted else [r for r in recs if r.get("status") != "deleted"]


def candidates(status="pending"):
    cands = MemoryStoreEngine().load().get("candidates", [])
    return [c for c in cands if c.get("status") == status]


def status():
    data = MemoryStoreEngine().load()
    return {
        "records": len(data.get("records", [])),
        "lessons": len(data.get("lessons", [])),
        "candidates": len(data.get("candidates", [])),
    }
