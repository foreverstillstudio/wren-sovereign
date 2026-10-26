# ============================================================
# WREN KERNEL — typed memory (port of vale/core/memory.js)
# ------------------------------------------------------------
# Three kinds, three lifetimes, three levels of authority:
#   fact       – durable truth, stated by a person. Wren may rely on it.
#   context    – true right now; carries an expiry and is filtered out
#                once past — Wren never sees stale context.
#   preference – how the keeper likes things done. Scoped, sourced,
#                confidence-rated. An UNCONFIRMED preference is a
#                hypothesis and is labeled as one in the prompt — it
#                never hardens into a rule on its own.
# Governed-store integration (docs/intelligence/03) lands in Phase 3;
# this module is the record contract it will speak.
# ============================================================

import re

MEMORY_KINDS = ["fact", "context", "preference", "decision"]

# How far a learned preference reaches. Deliberately stops at the house:
# no cross-house scope exists and none can be stored (Keeper Model, 00.6).
PREFERENCE_SCOPES = ["response", "record", "situation", "house"]

SCOPE_LABELS = {
    "response": "This response only",
    "record": "This client or project",
    "situation": "This kind of situation",
    "house": "This house, going forward",
}

_SCOPE_PERSISTS = {"response": False, "record": True, "situation": True, "house": True}

CONFIDENCE_LEVELS = ["low", "medium", "high"]
MEMORY_SOURCES = ["keeper_stated", "keeper_correction", "inferred"]

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean(v, max_len):
    return _CONTROL.sub(" ", str(v if v is not None else "")).strip()[:max_len]


def _one_of(v, options, fallback):
    return v if v in options else fallback


def make_memory(id=None, kind="fact", text="", created_at=None, expires_on=None,
                scope=None, source="keeper_stated", confidence="medium",
                confirmed=None, last_used_at=None, related_type=None,
                related_id=None, lesson_id=None, provenance=None):
    """Only `text` is required. Preferences default to UNCONFIRMED and MEDIUM
    confidence — earning trust is a separate, deliberate act."""
    k = _one_of(kind, MEMORY_KINDS, "fact")
    m = {
        "id": id,
        "kind": k,
        "text": _clean(text, 500),
        "created_at": created_at,
        "last_used_at": last_used_at,
        "source": _one_of(source, MEMORY_SOURCES, "keeper_stated"),
    }
    if provenance is not None:
        m["provenance"] = dict(provenance)
    if k == "context":
        m["expires_on"] = expires_on if _ISO_DATE.match(str(expires_on or "")) else None
    if k == "preference":
        m["scope"] = _one_of(scope, PREFERENCE_SCOPES, "situation")
        m["confidence"] = _one_of(confidence, CONFIDENCE_LEVELS, "medium")
        m["confirmed"] = confirmed is True
        if related_type:
            m["related_type"] = _clean(related_type, 40)
        if related_id:
            m["related_id"] = _clean(related_id, 60)
        if lesson_id:
            m["lesson_id"] = _clean(lesson_id, 60)
    return m


def normalize_memory(raw):
    """Bring a stored entry (possibly legacy flat text) to the current shape."""
    if not isinstance(raw, dict) or not raw.get("text"):
        return None
    return make_memory(
        id=raw.get("id"), kind=raw.get("kind") or "fact", text=raw.get("text"),
        created_at=raw.get("created_at") or raw.get("createdAt"),
        expires_on=raw.get("expires_on"), scope=raw.get("scope"),
        source=raw.get("source", "keeper_stated"),
        confidence=raw.get("confidence", "medium"), confirmed=raw.get("confirmed"),
        last_used_at=raw.get("last_used_at"), related_type=raw.get("related_type"),
        related_id=raw.get("related_id"), lesson_id=raw.get("lesson_id"),
        provenance=raw.get("provenance"),
    )


def is_expired(memory, today):
    if not memory or memory.get("kind") != "context":
        return False
    if not memory.get("expires_on"):
        return False
    if not _ISO_DATE.match(str(today or "")):
        return False
    return memory["expires_on"] < today


def is_spent(memory):
    """A response-scoped preference is spent the moment it is used — it must
    never reappear in a later conversation as a standing rule."""
    return (memory or {}).get("kind") == "preference" and \
        _SCOPE_PERSISTS.get(memory.get("scope")) is False


def active_memories(records, today, limit=60):
    out = []
    for raw in records or []:
        m = normalize_memory(raw)
        if m and not is_expired(m, today) and not is_spent(m):
            out.append(m)
    return out[-limit:]


def expired_memories(records, today):
    return [m for m in map(normalize_memory, records or []) if m and is_expired(m, today)]


def memory_line(m):
    """Render one memory for the prompt, carrying its own epistemic status —
    the model is never left to guess how much weight a line deserves."""
    if m["kind"] == "context":
        until = f", until {m['expires_on']}" if m.get("expires_on") else ""
        return f"[temporary{until}] {m['text']}"
    if m["kind"] == "preference":
        status = ("confirmed preference" if m.get("confirmed")
                  else "unconfirmed preference — treat as a hypothesis, not a rule")
        scope = SCOPE_LABELS.get(m.get("scope"), "")
        scope = f" · {scope.lower()}" if scope else ""
        return f"[{status}{scope}] {m['text']}"
    return m["text"]


def touch_memory(memory, today):
    out = dict(memory)
    out["last_used_at"] = today or memory.get("last_used_at")
    return out


def preference_from_lesson(lesson, id=None, now=None):
    """Promote a confirmed lesson into a standing preference."""
    if not lesson or not lesson.get("confirmed") or not lesson.get("active"):
        return None
    if not _SCOPE_PERSISTS.get(lesson.get("scope")):
        return None
    if lesson.get("category") == "one_time_exception":
        return None
    return make_memory(
        id=id, kind="preference",
        text=lesson.get("lesson") or lesson.get("explanation"),
        scope=lesson["scope"], source="keeper_correction",
        confidence="high", confirmed=True, created_at=now,
        related_type=lesson.get("related_type"), related_id=lesson.get("related_id"),
        lesson_id=lesson.get("id"),
    )
