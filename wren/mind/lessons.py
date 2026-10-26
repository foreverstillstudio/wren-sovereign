# ============================================================
# WREN KERNEL — Sovereign Lesson Logic (Layer 3)
# ------------------------------------------------------------
# PURPOSE: Captures the "WHY" behind keeper corrections.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import re
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, Mapping
)
from types import MappingProxyType

from wren.mind.memory import PREFERENCE_SCOPES, SCOPE_LABELS

# --- ARCHITECTURAL TYPES ---

CorrectionValue = Literal[
    "wrong_fact", "wrong_tone", "too_long", "too_brief", 
    "too_soft", "too_blunt", "wrong_priority", "missed_policy", 
    "missed_context", "incorrect_recommendation", "keeper_preference", 
    "one_time_exception", "other"
]

LessonScope = Literal["situation", "house", "record", "client", "project"]

class LessonRecord(TypedDict):
    id: Optional[str]
    house_id: Optional[str]
    category: CorrectionValue
    scope: LessonScope
    lesson: str
    explanation: str
    original_output: str
    edited_output: str
    related_type: Optional[str]
    related_id: Optional[str]
    draft_id: Optional[str]
    created_at: Optional[str]
    created_by: Optional[str]
    confirmed: bool
    active: bool
    requires_confirmation: bool

# --- CONSTANTS ---

CORRECTION_CATEGORIES: Final = MappingProxyType({
    "wrong_fact": {"label": "Wrong fact", "teaches": False},
    "wrong_tone": {"label": "Wrong tone", "teaches": True},
    "too_long": {"label": "Too long", "teaches": True},
    "too_brief": {"label": "Too brief", "teaches": True},
    "too_soft": {"label": "Too soft", "teaches": True},
    "too_blunt": {"label": "Too blunt", "teaches": True},
    "wrong_priority": {"label": "Wrong priority", "teaches": True},
    "missed_policy": {"label": "Missed a policy", "teaches": True},
    "missed_context": {"label": "Missed context", "teaches": True},
    "incorrect_recommendation": {"label": "Incorrect recommendation", "teaches": True},
    "keeper_preference": {"label": "My preference", "teaches": True},
    "one_time_exception": {"label": "One-time exception", "teaches": False},
    "other": {"label": "Something else", "teaches": True},
})

GLOBAL_SCOPE_REFUSAL: Final = (
    "A change to how Wren behaves for every house is not something one house "
    "can make. This will be sent to Forever Still Studio as a suggestion, and "
    "it will not change Wren here or anywhere until a person reviews it."
)

_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# --- UTILITIES ---

def _clean(v: Any, max_len: int) -> str:
    return _CONTROL.sub(" ", str(v if v is not None else "")).strip()[:max_len]

def category_teaches(value: str) -> bool:
    """Determines if a correction category should shape future behavior."""
    cat = CORRECTION_CATEGORIES.get(value)
    return bool(cat and cat["teaches"])

# --- CORE LOGIC ---

def make_lesson(
    id: Optional[str] = None, 
    house_id: Optional[str] = None, 
    category: str = "other", 
    scope: str = "situation",
    explanation: str = "", 
    lesson: str = "", 
    original_output: str = "", 
    edited_output: str = "",
    related_type: Optional[str] = None, 
    related_id: Optional[str] = None, 
    draft_id: Optional[str] = None,
    created_at: Optional[str] = None, 
    created_by: Optional[str] = None, 
    confirmed: bool = False, 
    active: bool = True
) -> LessonRecord:
    """Constructs a typed LessonRecord with sanitized inputs."""
    
    # Ensure category and scope are valid, falling back to defaults
    cat_val: CorrectionValue = category if category in CORRECTION_CATEGORIES else "other"
    scope_val: LessonScope = scope if scope in PREFERENCE_SCOPES else "situation"
    
    return {
        "id": id,
        "house_id": house_id,
        "category": cat_val,
        "scope": scope_val,
        "lesson": _clean(lesson or explanation, 400),
        "explanation": _clean(explanation, 1000),
        "original_output": _clean(original_output, 4000),
        "edited_output": _clean(edited_output, 4000),
        "related_type": _clean(related_type, 40) if related_type else None,
        "related_id": _clean(related_id, 80) if related_id else None,
        "draft_id": _clean(draft_id, 80) if draft_id else None,
        "created_at": created_at,
        "created_by": _clean(created_by, 160) if created_by else None,
        "confirmed": confirmed is True,
        "active": active is not False,
        "requires_confirmation": scope_val == "house",
    }

def validate_lesson(src: Any, house_id: Optional[str] = None, now: Optional[str] = None) -> Dict[str, Any]:
    """Rigorous validation of lesson data before persistence."""
    errors = []
    data = src if isinstance(src, dict) else {}
    
    if not house_id:
        errors.append("A lesson cannot be stored without an owning house.")
        
    # Core content check
    if not _clean(data.get("explanation"), 1000) and not _clean(data.get("lesson"), 400):
        errors.append("Say what was wrong — a correction with no reason teaches nothing.")
        
    # Scope validation
    scope = data.get("scope")
    if scope and scope not in PREFERENCE_SCOPES:
        errors.append(f'"{scope}" is not a scope a house can set. {GLOBAL_SCOPE_REFUSAL}')
        
    # Category validation
    cat = data.get("category")
    if cat and cat not in CORRECTION_CATEGORIES:
        errors.append(f'Unknown correction category "{cat}".')
        
    lesson = make_lesson(
        id=data.get("id"), 
        house_id=house_id, 
        category=data.get("category", "other"),
        scope=data.get("scope", "situation"), 
        explanation=data.get("explanation", ""),
        lesson=data.get("lesson", ""), 
        original_output=data.get("original_output", ""),
        edited_output=data.get("edited_output", ""), 
        related_type=data.get("related_type"),
        related_id=data.get("related_id"), 
        draft_id=data.get("draft_id"),
        created_at=data.get("created_at") or now, 
        created_by=data.get("created_by"),
        confirmed=data.get("confirmed", False), 
        active=data.get("active", True),
    )
    
    return {
        "lesson": lesson, 
        "errors": errors, 
        "ok": len(errors) == 0
    }

def active_lessons(records: List[Dict[str, Any]]) -> List[LessonRecord]:
    """Filter for lessons that are active, confirmed, and behaviorally teachable."""
    return [
        cast(LessonRecord, l) for l in (records or [])
        if l and l.get("active") is not False 
        and l.get("confirmed") is True 
        and category_teaches(l.get("category", "other"))
    ]

def lessons_to_prompt(records: List[Dict[str, Any]]) -> str:
    """Transforms active lessons into a high-fidelity prompt section."""
    active = active_lessons(records)
    if not active:
        return ""
        
    lines = []
    # Process only the most recent 30 lessons to maintain prompt density
    for l in active[-30:]:
        scope = l["scope"]
        lesson_text = l["lesson"]
        
        if scope == "record" and l.get("related_id"):
            context = f" (applies to {l.get('related_type') or 'record'} {l['related_id']})"
        elif scope == "situation":
            context = " (applies to this kind of situation)"
        else:
            context = ""
            
        lines.append(f"- {lesson_text}{context}")
        
    header = (
        "# What the keeper has taught you\n"
        "These are corrections the keeper has made and confirmed. Follow them. "
        "They came from this house only and apply only here. If one of them would "
        "conflict with the Steward's Charter, the Charter wins and you say so plainly.\n"
    )
    
    return header + "\n".join(lines)
