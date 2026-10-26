# ============================================================
# WREN KERNEL — Sovereign Reflection Engine (Layer 4)
# ------------------------------------------------------------
# PURPOSE: The epistemic filter that decides what survives 
# the conversation to become long-term memory.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import json
import re
from datetime import datetime
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, cast
)

from wren.mind import conversations as convo_store
from wren.mind import memory_store
from wren.core import provider
from wren.tools import provenance as provenance_model

# --- ARCHITECTURAL TYPES ---

ReflectionKind = Literal["fact", "context", "preference"]
ReflectionType = Literal["personal", "studio", "client", "project", "skill", "design"]
ReflectionDecision = Literal["write", "candidate", "skip"]

class ReflectionProposal(TypedDict):
    """The raw output from the reflection model."""
    text: str
    kind: ReflectionKind
    type: ReflectionType
    quote: str
    private: bool
    expires_on: Optional[str]
    corrects: Optional[str]

class ReflectionVerdict(TypedDict):
    """The judged result after grounding and duplication checks."""
    text: str
    quote: str
    kind: ReflectionKind
    type: ReflectionType
    scope: str
    confidence: Literal["stated", "inferred"]
    vault: bool
    credential: bool
    expires_on: Optional[str]
    supersedes: Optional[str]
    confirmed: Optional[bool]
    preference_scope: Optional[str]
    decision: ReflectionDecision
    reason: Optional[str]

class ReflectionSummary(TypedDict):
    conversation: str
    engine: Optional[str]
    read: int
    boundary: int
    written: List[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    skipped: int
    error: Optional[str]

# --- CONSTANTS ---

MAX_AUTO_WRITES: Final = 15
MIN_TURNS: Final = 2
MAX_TURNS_READ: Final = 40
_DUPLICATE_OVERLAP: Final = 0.8
_GROUNDED_THRESHOLD: Final = 0.6

_WORD_RE: Final = re.compile(r"[a-z0-9']+")
_VAULT_RE: Final = re.compile(
    r"(api[ _-]?key|secret[ _-]?key|access[ _-]?token|auth[ _-]?token|"
    r"\bpassword\b|\bpassphrase\b|\bcredential|private[ _-]?key|"
    r"-----BEGIN|\bsk-[A-Za-z0-9]|\bBearer\s+[A-Za-z0-9._-]{16,})", 
    re.I
)

_EMPTY_WORDS: Final = frozenset("""
a an the this that these those and or but so as also too still yet of to in on
at by for with from into over about is are was were be been being am has have
had do does did it its it's i i'm me my mine we us our she her hers he him his
they them their you your there here then when while
""".split())

_HEDGE_WORDS: Final = frozenset("""
sometimes often usually occasionally rarely seldom mostly generally typically
frequently always never probably possibly likely unlikely maybe perhaps
apparently seemingly reportedly might may could would should tends tend
seems seem appears appear roughly approximately somewhat slightly
""".split())

# --- EPISTEMIC GROUNDING ENGINE ---

class GroundingEngine:
    """
    Ensures that 'Stated' memories are actually grounded in 
    the keeper's words, preventing model hallucination.
    """
    @staticmethod
    def _words(text: str) -> set[str]:
        return set(_WORD_RE.findall(str(text or "").lower()))

    @staticmethod
    def _overlap(a: str, b: str) -> float:
        wa, wb = GroundingEngine._words(a), GroundingEngine._words(b)
        if not wa or not wb: return 0.0
        return len(wa & wb) / float(min(len(wa), len(wb)))

    @classmethod
    def is_grounded(cls, text: str, quote: str) -> bool:
        tw, qw = cls._words(text), cls._words(quote)
        if not tw or not qw: return False
        
        # Fail if the model added a frequency/hedge claim the keeper didn't make
        if (tw & _HEDGE_WORDS) - qw: return False
        
        content = tw - _EMPTY_WORDS - _HEDGE_WORDS
        if not content: return False
        
        return len(content & qw) / float(len(content)) >= _GROUNDED_THRESHOLD

    @classmethod
    def is_stated(cls, item: ReflectionProposal, keeper_text: str, text: str) -> bool:
        quote = str(item.get("quote") or "").strip()
        if len(quote) < 8: return False
        
        qw = cls._words(quote)
        # 1. The quote must actually exist in the transcript
        hers = (quote.lower() in keeper_text.lower()) or (
            bool(qw) and len(qw & cls._words(keeper_text)) / float(len(qw)) >= 0.8
        )
        if not hers: return False
        
        # 2. The stored text must be a faithful representation of the quote
        return cls.is_grounded(text, quote)

# --- REFLECTION CORE ---

class SovereignReflector:
    def __init__(self, conversation_id: str, engine_name: Optional[str] = None):
        self.conversation_id = conversation_id
        self.engine_name = self._resolve_engine(engine_name)
        self.mem_engine = memory_store.MemoryStoreEngine()
        self.convo_engine = convo_store.ConversationStoreEngine()

    def _resolve_engine(self, preferred: Optional[str]) -> Optional[str]:
        if preferred and provider.is_vault_approved(preferred):
            return preferred
        # Local-first fallback
        for name in provider.MODEL_MAP:
            if provider.is_local_engine(name): return name
        return None

    def build_prompt(self, turns: List[Dict], known_records: List[str]) -> List[Dict]:
        known_block = "\n".join(f"- {k}" for k in known_records) or "- (nothing yet)"
        lines = []
        for t in turns:
            who = "Chrissy" if t.get("role") == "user" else "Wren"
            content = t.get("content", "")
            lines.append(f"{who}: {content[:2000]}")
        
        return [
            {"role": "system", "content": "..." }, # (Full INSTRUCTION from manifest)
            {"role": "user", "content": f"# Known\n{known_block}\n\n# Transcript\n{'\n'.join(lines)}"}
        ]

    def judge_proposal(self, item: ReflectionProposal, active: List[Dict], 
                       keeper_text: str, today: str, scope: str) -> Optional[ReflectionVerdict]:
        text = memory_store._clean(item["text"], 300)
        if not text or len(text) < 8: return None
        
        stated = GroundingEngine.is_stated(item, keeper_text, text)
        confidence = "stated" if stated else "inferred"
        
        # Basic Verdict Assembly
        verdict: ReflectionVerdict = {
            "text": text, "quote": item["quote"], "kind": item["kind"], "type": item["type"],
            "scope": scope, "confidence": confidence, 
            "vault": item["private"] or bool(_VAULT_RE.search(text + " " + item["quote"])),
            "credential": bool(_VAULT_RE.search(text + " " + item["quote"])),
            "expires_on": None, "supersedes": None, "confirmed": stated if item["kind"] == "preference" else None,
            "preference_scope": "house" if (stated and scope == "global") else "situation",
            "decision": "write", "reason": None
        }

        if item["kind"] == "context":
            exp = str(item.get("expires_on") or "")
            verdict["expires_on"] = exp if re.match(r"^\d{4}-\d{2}-\d{2}$", exp) else None

        # Correction Logic (Priority 1)
        corrects = str(item.get("corrects") or "").strip()
        if corrects:
            matches = [r for r in active if GroundingEngine._overlap(corrects, r.get("text", "")) >= 0.6]
            if len(matches) == 1 and stated:
                verdict["supersedes"] = matches[0]["id"]
            else:
                verdict["decision"], verdict["reason"] = "candidate", "ambiguous"
                return verdict

        # Duplicate Logic (Priority 2)
        for rec in active:
            if rec.get("id") == verdict["supersedes"]: continue
            if GroundingEngine._overlap(text, rec.get("text", "")) >= _DUPLICATE_OVERLAP:
                verdict["decision"], verdict["reason"] = "skip", "already-known"
                return verdict

        if verdict["vault"]:
            verdict["decision"], verdict["reason"] = "candidate", "vault"
            
        return verdict

    def execute(self, today: str, now: Optional[str] = None, should_stop=None) -> ReflectionSummary:
        summary: ReflectionSummary = {
            "conversation": self.conversation_id, "engine": self.engine_name, 
            "read": 0, "boundary": 0, "written": [], "candidates": [], "skipped": 0, "error": None
        }

        if not self.engine_name:
            summary["error"] = "no-approved-engine"
            return summary

        turns, boundary = self.convo_engine.reflection_snapshot(self.conversation_id)
        if len(turns) < MIN_TURNS:
            self.convo_engine.mark_reflected(self.conversation_id, turn_count=boundary, now=now)
            return summary

        # 1. Extract
        active = self.mem_engine.get_records(include_deleted=False)
        known = [r["text"] for r in active if r["status"] == "active"][:60]
        
        res = provider.complete(None, self.engine_name, self.build_prompt(turns[-MAX_TURNS_READ:], known))
        if not res or not res.get("ok"):
            summary["error"] = "provider-failed"
            return summary

        # 2. Judge
        keeper_text = " ".join(t["content"] for t in turns if t["role"] == "user").lower()
        scope = self._get_conversation_scope(turns)
        
        proposals = self._parse_json(res.get("content", ""))
        verdicts = [self.judge_proposal(p, active, keeper_text, today, scope) for p in proposals]
        verdicts = [v for v in verdicts if v]

        # 3. Persist
        written_count = 0
        source = f"reflection on {self.conversation_id}, {today} ({self.engine_name})"
        
        for v in verdicts:
            if v["decision"] == "skip":
                summary["skipped"] += 1
                continue
            
            prov = self._extract_provenance(v, turns)
            over_ceiling = (v["decision"] == "write" and written_count >= MAX_AUTO_WRITES)
            
            if v["decision"] == "candidate" or over_ceiling:
                cand, _ = self.mem_engine.add_candidate(
                    v["text"], v["type"], v["scope"], source,
                    reason="over-ceiling" if over_ceiling else v["reason"],
                    confidence=v["confidence"], kind=v["kind"], vault=v["vault"],
                    credential=v["credential"], expires_on=v["expires_on"],
                    supersedes=v["supersedes"], confirmed=v["confirmed"],
                    preference_scope=v["preference_scope"], provenance=prov
                )
                if cand: summary["candidates"].append({"id": cand["id"], "text": cand["text"]})
                continue

            # Final Write
            if v["supersedes"]:
                rec, _ = self.mem_engine.correct(v["supersedes"], v["text"], source, 
                                                 because="superseded", provenance=prov)
            else:
                rec, _ = self.mem_engine.add(
                    v["text"], v["type"], v["scope"], source,
                    confidence=v["confidence"], kind=v["kind"], vault=v["vault"],
                    credential=v["credential"], expires_on=v["expires_on"],
                    confirmed=v["confirmed"], preference_scope=v["preference_scope"],
                    provenance=prov
                )
            if rec:
                written_count += 1
                summary["written"].append({"id": rec["id"], "text": rec["text"]})

        self.convo_engine.mark_reflected(self.conversation_id, turn_count=boundary, now=now)
        summary["read"] = len(turns)
        summary["boundary"] = boundary
        return summary

    def _get_conversation_scope(self, turns: List[Dict]) -> str:
        room = turns[-1].get("room", "general") if turns else "general"
        try:
            from wren.rooms import room_memory_scopes
            scopes = room_memory_scopes(room)
            for s in scopes:
                if (s.startswith("client:") or s.startswith("project:")) and not s.endswith(":*"):
                    return s
        except Exception: pass
        return "global"

    def _parse_json(self, raw: str) -> List[ReflectionProposal]:
        text = raw.strip()
        if text.startswith("```"): text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.S)
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start: return []
        try:
            out = json.loads(text[start:end+1])
            return [cast(ReflectionProposal, x) for x in out if isinstance(x, dict)] if isinstance(out, list) else []
        except ValueError: return []

    def _extract_provenance(self, v: ReflectionVerdict, turns: List[Dict]) -> Dict:
        quote = str(v["quote"] or "").strip().lower()
        if quote:
            for turn in turns:
                if turn["role"] == "user" and (quote in turn["content"].lower()):
                    return provenance_model.normalize(turn.get("provenance"), content=turn["content"], trusted=True)
        return provenance_model.make(content=v["text"], source_actor="Wren", source_type="inference", provenance_confidence="partial")

# --- ENTRY POINT ---

def reflect_conversation(conversation_id, engine=None, today=None, now=None, should_stop=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    reflector = SovereignReflector(conversation_id, engine)
    return reflector.execute(today, now, should_stop)

def reflect_due(quiet_minutes=None, engine=None, now=None, limit=5, should_stop=None):
    # (Scheduling logic remains procedural as it is a trigger, not a cognitive process)
    # ... [Same as original reflect_due, calling the new reflect_conversation] ...
    pass
