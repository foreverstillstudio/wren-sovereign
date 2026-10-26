from __future__ import annotations
"""
Wren Provenance Engine v2.0: The Evidence Contract.

This module defines the sovereign contract for evidence provenance and 
response integrity. It ensures that every claim made by the system is 
traceable, and every verification claim is backed by a durable tool event.

TRUTH IS TRACEABLE. INTEGRITY IS NON-NEGOTIABLE.
"""

import re
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Final, TypedDict, Set, Union, cast

# --- Type Definitions for the Truth Contract ---

class ProvenanceRecord(TypedDict, total=False):
    source_actor: str
    source_type: str
    original_source: Optional[str]
    observed_by_wren: bool
    verified_by_wren: bool
    verification_method: Optional[str]
    verification_timestamp: Optional[str]
    created_at: str
    provenance_confidence: str
    verification_events: Optional[List[ProvenanceRecord]]
    disputed_reason: Optional[str]
    disputes: Optional[List[Dict[str, Any]]]
    evidence_excerpt: Optional[str]

# --- Constants & Security Patterns ---

SOURCE_ACTORS: Final = ("Chris", "Wren", "Codex", "Watchdog", "Forge", "file", "memory", "other", "unknown")
SOURCE_TYPES: Final = ("user_message", "pasted_text", "tool_result", "file", "agent_report", "memory", "inference", "unknown")
CONFIDENCE_LEVELS: Final = ("known", "partial", "unknown", "disputed")

_CONTROL_CHARS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WORD_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9._:/-]*")
_STOP_WORDS: Final = {
    "a", "an", "and", "as", "at", "by", "checked", "confirmed", "did",
    "documentation", "for", "found", "from", "i", "in", "inspected", "it",
    "of", "on", "queried", "reviewed", "saw", "tested", "that", "the",
    "this", "to", "verified", "with",
}

# Anti-Hallucination Patterns
_CLAIM_RE: Final = re.compile(
    r"(?<![\w])i(?:\s+have|['’]ve)?\s+(?:independently\s+)?"
    r"(?:checked|verified|confirmed|found|accessed|reviewed|tested|queried|"
    r"inspected|observed|opened|read|ran|saw|searched|browsed|used|executed|"
    r"done|completed|placed|created|wrote|written|saved|updated|finished|"
    r"deployed|generated|built|installed|moved|copied|deleted|removed|added|"
    r"appended|renamed|committed|fixed|edited|patched|published|pushed)\b|"
    r"(?<![\w])i(?:\s+have|['’]ve)?\s+looked\s+at\b|"
    r"(?<![\w])i\s+saw\s+in\s+the\s+documentation\b|"
    r"(?<![\w])i\s+can\s+confirm\b", re.I)

_SUPPLIED_REVIEW_RE: Final = re.compile(
    r"(?i)\bi\s+(?:checked|reviewed|read|looked\s+at)\b[^.!?\n]*"
    r"\b(?:you\s+(?:pasted|sent|shared|provided|told)|your\s+(?:paste|"
    r"message|report|text))\b")

_CONVERSATIONAL_SPEECH_RE: Final = re.compile(
    r"(?i)\bi(?:\s+have|['’]ve)?\s+(?:checked|reviewed|read|looked\s+at|saw|found|used|ran|noticed|observed|queried|inspected)\b[^.!?\n]*?"
    r"\b(?:"
    r"you\s+(?:said|wrote|shared|mentioned|noted|told|asked|suggested|pasted|sent|provided|brought\s+up|described)|"
    r"your\s+(?:message|note|notes|idea|ideas|words|thought|thoughts|question|paste|text|report|suggestion|draft|code)|"
    r"what\s+you\s+(?:said|wrote|shared|mentioned|noted|told|asked|suggested|sent|described)|"
    r"what\s+we\s+(?:discussed|talked\s+about|covered|decided|were\s+talking\s+about)|"
    r"we\s+(?:discussed|talked\s+about|covered|decided)|"
    r"our\s+(?:conversation|discussion|chat|talk|notes|plan)|"
    r"what\s+you\s+mean|your\s+point|"
    r"that\s+(?:(?:really|very|quite|so)\s+)?(?:interesting|helpful|fascinating|funny|useful|strange|odd|surprising|compelling|cool|makes\s+sense|good|great)|"
    r"it\s+(?:(?:really|very|quite|so)\s+)?(?:interesting|helpful|fascinating|useful|strange|surprising|good|great)|"
    r"at\s+(?:that|this)\b|saw\s+(?:that|this|it)\b|read\s+(?:that|this|it)\b|"
    r"a\s+way\b|into\s+(?:that|this)|across\s+(?:that|this)|earlier\b|before\b|"
    r"with\s+you\b|on\s+(?:that|this|the)(?:\s+(?:idea|topic|matter|point|question|thought|notes))?\b|in\s+on\b"
    r")\b")

_FAILED_RESULT_RE: Final = re.compile(
    r"(?i)^\s*\[?(?:blocked|error\b|failed\b|failure\b|cancelled\b|"
    r"timed?\s*out\b|permission denied\b|not authorized\b|unavailable\b)")

# --- The Provenance Engine ---

class ProvenanceEngine:
    """
    The engine responsible for the creation and normalization of 
    evidence provenance records.
    """

    @staticmethod
    def _clean(value: Any, limit: int = 500) -> str:
        val = _CONTROL_CHARS.sub(" ", str(value if value is not None else ""))
        return re.sub(r"\s+", " ", val).strip()[:limit]

    @staticmethod
    def _get_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def make_record(self, 
                    content: str = "", 
                    source_actor: str = "unknown", 
                    source_type: str = "unknown",
                    original_source: Optional[str] = None, 
                    observed_by_wren: bool = False, 
                    verified_by_wren: bool = False,
                    verification_method: Optional[str] = None, 
                    verification_timestamp: Optional[str] = None, 
                    created_at: Optional[str] = None,
                    provenance_confidence: str = "known", 
                    verification_events: Optional[List[Dict]] = None,
                    trusted_verification: bool = False) -> ProvenanceRecord:
        
        # Resolve actor and type against allowed sets
        actor = self._clean(source_actor, 40)
        actor = actor if actor in SOURCE_ACTORS else "unknown"
        
        stype = self._clean(source_type, 40)
        stype = stype if stype in SOURCE_TYPES else "unknown"
        
        # Verification logic is fail-closed
        verified = bool(trusted_verification and verified_by_wren and 
                        observed_by_wren and verification_method and verification_timestamp)
        
        confidence = provenance_confidence if provenance_confidence in CONFIDENCE_LEVELS else "unknown"
        
        record: ProvenanceRecord = {
            "source_actor": actor,
            "source_type": stype,
            "original_source": self._clean(original_source, 500) or None,
            "observed_by_wren": observed_by_wren,
            "verified_by_wren": verified,
            "verification_method": self._clean(verification_method, 300) if verified else None,
            "verification_timestamp": self._clean(verification_timestamp, 80) if verified else None,
            "created_at": self._clean(created_at, 80) or self._get_timestamp(),
            "provenance_confidence": confidence,
            "evidence_excerpt": self._clean(content, 500) if content else None
        }

        if verification_events:
            record["verification_events"] = [self.normalize(e, trusted=True) for e in verification_events if isinstance(e, dict)]
        
        return record

    def normalize(self, raw: Any, content: str = "", trusted: bool = False) -> ProvenanceRecord:
        """Normalizes metadata into a strict ProvenanceRecord."""
        if not isinstance(raw, dict):
            return self.make_record(content=content, provenance_confidence="unknown")
        
        return self.make_record(
            content=content or raw.get("evidence_excerpt", ""),
            source_actor=raw.get("source_actor"),
            source_type=raw.get("source_type"),
            original_source=raw.get("original_source"),
            observed_by_wren=raw.get("observed_by_wren") is True,
            verified_by_wren=raw.get("verified_by_wren") is True,
            verification_method=raw.get("verification_method"),
            verification_timestamp=raw.get("verification_timestamp"),
            created_at=raw.get("created_at"),
            provenance_confidence=raw.get("provenance_confidence", "unknown"),
            verification_events=raw.get("verification_events"),
            trusted_verification=trusted
        )

    def create_tool_provenance(self, tool: str, result: Any, target: Optional[str] = None, 
                              successful: bool = False, authorized: bool = False, 
                              timestamp: Optional[str] = None) -> ProvenanceRecord:
        """Creates traceable provenance for a tool event."""
        method = f"{self._clean(tool, 80)}{' on ' + self._clean(target, 300) if target else ''}"
        
        # Fail-closed verification
        is_verified = bool(successful and authorized and str(result or "").strip() 
                            and not _FAILED_RESULT_RE.search(str(result or "")))
        
        return self.make_record(
            content=str(result),
            source_actor="Wren",
            source_type="tool_result",
            original_source=target or tool,
            observed_by_wren=is_verified,
            verified_by_wren=is_verified,
            verification_method=method,
            verification_timestamp=timestamp or (self._get_timestamp() if is_verified else None),
            provenance_confidence="known",
            trusted_verification=True
        )

    def generate_prompt_label(self, prov: Any) -> str:
        """Creates the concise provenance tag used in prompt injection."""
        p = self.normalize(prov)
        origin = f" -> {p['original_source']}" if p.get("original_source") else ""
        verified = "Wren-verified" if p["verified_by_wren"] else "unverified"
        return f"{p['source_actor']}/{p['source_type']}{origin}, {verified}, {p['provenance_confidence']}"

# --- The Integrity Guard ---

class IntegrityGuard:
    """
    The sovereign audit layer that prevents the model from making 
    unsupported verification claims in its responses.
    """

    def __init__(self, events: Optional[List[Dict]] = None):
        self.events = [ProvenanceEngine().normalize(e, trusted=True) for e in (events or [])]

    def _tokens(self, text: str) -> Set[str]:
        return {w for w in _WORD_PATTERN.findall(str(text or "").lower()) 
                if len(w) > 2 and w not in _STOP_WORDS}

    def _find_matching_event(self, sentence: str, require_verified: bool = True) -> Optional[ProvenanceRecord]:
        wanted = self._tokens(sentence)
        if not wanted: return None
        
        for event in self.events:
            if event["source_actor"] != "Wren": continue
            if require_verified and not event["verified_by_wren"]: continue
            if not require_verified and not event["observed_by_wren"]: continue
            
            hay = f"{event.get('evidence_excerpt', '')} {event.get('original_source', '')} {event.get('verification_method', '')}".lower()
            for w in wanted:
                if w in hay:
                    return event
                # stem match (e.g. "written" -> "write_file", "config" -> "config.json")
                if len(w) >= 4 and w[:4] in hay:
                    return event
        return None

    def is_safe_conversational(self, piece: str) -> bool:
        """Detects if a sentence is natural dialogue rather than an external claim."""
        if re.search(r"(?i)\b(?:verified|confirmed|tested)\s+the\s+external\b", piece):
            return False
        return bool(_CONVERSATIONAL_SPEECH_RE.search(piece) or _SUPPLIED_REVIEW_RE.search(piece))

    def guard_text(self, text: str) -> Tuple[str, List[str]]:
        """Scans text for unsupported claims and returns (cleaned_text, violations)."""
        pieces = re.split(r"(?<=[.!?\n])", str(text or ""))
        out, violations = [], []
        
        for piece in pieces:
            if not _CLAIM_RE.search(piece):
                out.append(piece)
                continue
            
            if self.is_safe_conversational(piece):
                out.append(piece)
                continue
                
            if self._find_matching_event(piece):
                out.append(piece)
                continue
            
            violations.append(piece.strip())
            
        return "".join(out).rstrip(), violations

class StreamingGuard:
    """Stateful guard for real-time token streams."""
    def __init__(self, events: Optional[List[Dict]] = None):
        self.guard = IntegrityGuard(events)
        self.pending = ""
        self.violations = []

    def feed(self, chunk: str, final: bool = False) -> List[str]:
        self.pending += str(chunk or "")
        emitted = []
        
        while self.pending:
            # Detect start of a potential claim
            match = re.search(r"(?i)(?<![\w])i(?:\s|['’])", self.pending)
            if not match:
                if final:
                    emitted.append(self.pending)
                    self.pending = ""
                else:
                    # Handle trailing 'I'
                    tail = re.search(r"(?i)(?<![\w])i$", self.pending)
                    if tail:
                        emitted.append(self.pending[:tail.start()])
                        self.pending = self.pending[tail.start():]
                    else:
                        emitted.append(self.pending)
                        self.pending = ""
                break
                
            if match.start():
                emitted.append(self.pending[:match.start()])
                self.pending = self.pending[match.start():]
            
            boundary = re.search(r"[.!?\n]", self.pending)
            candidate = self.pending if boundary is None else self.pending[:boundary.end()]
            
            if boundary is None and not final: break
            
            guarded, violations = self.guard.guard_text(candidate)
            emitted.append(guarded)
            self.violations.extend(violations)
            self.pending = self.pending[len(candidate):]
            
        return emitted

    def finish(self) -> List[str]:
        """Flush any remaining buffered text at end of stream."""
        return self.feed("", final=True)

# --- Public API ---

_prov_engine = ProvenanceEngine()

def make(**kwargs): return _prov_engine.make_record(**kwargs)
def normalize(raw, content="", trusted=False): return _prov_engine.normalize(raw, content, trusted)
def tool_result(*args, **kwargs): return _prov_engine.create_tool_provenance(*args, **kwargs)
def prompt_label(prov): return _prov_engine.generate_prompt_label(prov)
def label(prov): return _prov_engine.generate_prompt_label(prov)


def legacy_unknown(content, created_at=None):
    """The provenance for a legacy record whose source is no longer known."""
    return _prov_engine.make_record(
        content=content, source_actor="unknown", source_type="unknown",
        provenance_confidence="unknown", created_at=created_at)
def guard_response(text, events=None): return IntegrityGuard(events).guard_text(text)


def for_turn(role, content, supplied=None, trusted=False, created_at=None):
    """The provenance record for one conversation turn. A user turn is
    keeper-stated and observed by Wren; an assistant turn is Wren's own
    inference."""
    if isinstance(supplied, dict):
        return _prov_engine.normalize(supplied, content=content, trusted=trusted)
    is_user = str(role).lower() == "user"
    return _prov_engine.make_record(
        content=content,
        source_actor="Chris" if is_user else "Wren",
        source_type="user_message" if is_user else "inference",
        observed_by_wren=is_user,
        provenance_confidence="known" if is_user else "partial",
        created_at=created_at,
    )


def evidence_block(events):
    """Format the evidence list into the source-attributed prompt section."""
    if not events:
        return ""
    lines = ["# Evidence (source-attributed)"]
    for e in events:
        if not isinstance(e, dict):
            continue
        p = _prov_engine.normalize(e, trusted=True)
        content = str(p.get("content") or "").strip()
        if content:
            lines.append(f"- {_prov_engine.generate_prompt_label(p)}: {content}")
    return "\n".join(lines) if len(lines) > 1 else ""


_ATTRIBUTION_CHALLENGE_RE = re.compile(
    r"(?i)\b(?:you|that|it|this)\b[^.!?\n]{0,120}\b(?:made that up|made it up|"
    r"invented|made up|wrong source|attributed wrong|where did you get|"
    r"that's not what|you said it was|not the source)",
)

def attribution_challenge(content):
    """A reason string when the user disputes the previous attribution, else None."""
    text = str(content or "").strip()
    if not text:
        return None
    m = _ATTRIBUTION_CHALLENGE_RE.search(text)
    return m.group(0).strip() if m else None


def with_verification(record, event):
    """Stamp a record as verified by a durable tool event."""
    rec = dict(record or {})
    rec["verified_by_wren"] = True
    rec["verification_method"] = event.get("verification_method")
    rec["verification_timestamp"] = event.get("verification_timestamp")
    return rec
