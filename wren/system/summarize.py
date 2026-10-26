# ============================================================
# WREN KERNEL — Sovereign Continuity Engine (Layer 4)
# ------------------------------------------------------------
# PURPOSE: Maintains the rolling summary of live threads to 
# prevent "context holes" as turns fall out of the window.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import json
import re
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, cast
)
from types import MappingProxyType

from wren.mind import conversations as convo_store
from wren.mind import memory_store
from wren.core import provider
from wren.tools import provenance as provenance_model

# --- ARCHITECTURAL TYPES ---

class DecisionItem(TypedDict):
    text: str
    why: Optional[str]
    guardrail: Optional[str]
    scope: str

class EvidenceItem(TypedDict):
    fact: str
    source_actor: str
    source_type: str
    original_source: str
    verified_by_wren: bool

class SummaryPayload(TypedDict):
    summary: str
    active_task: str
    settled_decisions: List[DecisionItem]
    evidence: List[EvidenceItem]
    unresolved_next_steps: List[str]

class WorkingState(TypedDict):
    active_task: Optional[str]
    evidence: List[Dict[str, Any]]
    unresolved_next_steps: List[str]
    conversation_id: str
    summary: str

# --- CONSTANTS ---

MIN_BEHIND: Final = 8
_WORD_RE: Final = re.compile(r"[a-z0-9']+")

# Lookahead triggers derived from the Window Budget
LOOKAHEAD_TRIGGER_CHARS: Final = convo_store.HISTORY_BUDGET_CHARS * 3 // 8
LOOKAHEAD_TARGET_CHARS: Final = convo_store.HISTORY_BUDGET_CHARS * 3 // 4

INSTRUCTION: Final = """You maintain the running continuity and summary of one conversation between Wren and Chrissy.
... (Instruction from manifest) ...
"""

# --- SOVEREIGN ENGINE ---

class SovereignSummarizer:
    """
    Engine managing the incremental compression of conversation history.
    Decouples prompt construction, model extraction, and store persistence.
    """
    def __init__(self, conversation_id: str, engine: str):
        self.conversation_id = conversation_id
        self.engine = engine
        self.convo_engine = convo_store.ConversationStoreEngine()
        self.mem_engine = memory_store.MemoryStoreEngine()

    def calculate_boundary(self, ahead_chars: int = 0) -> tuple[int, int, int]:
        """
        Determines the current state of the summary vs the window.
        Returns: (start_index, covers_index, behind_count)
        """
        # Get current window edge (excluding nothing for boundary calc)
        win = self.convo_engine.window(self.conversation_id, exclude_vault=False)
        conv = self.convo_engine.get_conversation(self.conversation_id)
        
        if not conv: return 0, 0, 0
        
        covers = conv.get("summary_covers") or 0
        start = win.get("start", 0)
        
        # Handle 'ahead_chars' for post-reply updates
        if ahead_chars > 0:
            budget = max(convo_store.HISTORY_BUDGET_CHARS - ahead_chars, 1)
            ahead_win = self.convo_engine.window(self.conversation_id, exclude_vault=False, budget_chars=budget)
            ahead_start = ahead_win.get("start", 0)
            if ahead_start > start:
                start = ahead_start

        # Long-thread override: start summary if thread is substantial but summary is 0
        if start == 0 and conv.get("turns"):
            total_chars = sum(len(t["content"]) for t in conv["turns"])
            if total_chars > (convo_store.HISTORY_BUDGET_CHARS * 3 // 4) and len(conv["turns"]) >= 8:
                target = max(len(conv["turns"]) - 6, 1)
                if target > covers:
                    return target, covers, target - covers

        return start, covers, max(start - covers, 0)

    def build_prompt(self, previous_summary: str, slice_turns: List[Dict]) -> List[Dict]:
        """Constructs the summarization prompt with vault-filtered turns."""
        lines = []
        for t in slice_turns:
            if t.get("vault"): continue # Rule 2: No vault in input
            
            who = "Chrissy" if t["role"] == "user" else "Wren"
            prov = provenance_model.normalize(t.get("provenance"), content=t["content"], trusted=True)
            lines.append(f"{who} [{provenance_model.label(prov)}]: {t['content'][:2000]}")

        return [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": f"# Summary So Far\n{previous_summary}\n\n# Next Stretch\n{'\n'.join(lines)}"}
        ]

    def parse_payload(self, raw: str) -> SummaryPayload:
        """Rigorous JSON extraction of the summary payload."""
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.S).strip()
        
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return self._fallback_payload(text)
            
        try:
            parsed = json.loads(text[start:end+1])
            if isinstance(parsed, dict):
                return cast(SummaryPayload, parsed)
        except Exception:
            pass
        return self._fallback_payload(text)

    def _fallback_payload(self, text: str) -> SummaryPayload:
        return {
            "summary": text,
            "active_task": text[:200] if text else "",
            "settled_decisions": [],
            "evidence": [],
            "unresolved_next_steps": [],
        }

    def persist(self, payload: SummaryPayload, start: int) -> Optional[int]:
        """Atomically persists summary and working state."""
        conv = self.convo_engine.get_conversation(self.conversation_id)
        if not conv: return None

        summary_text = payload["summary"].strip()
        
        working_state: WorkingState = {
            "active_task": payload.get("active_task"),
            "evidence": payload.get("evidence", []),
            "unresolved_next_steps": payload.get("unresolved_next_steps", []),
            "conversation_id": self.conversation_id,
            "summary": summary_text,
        }

        # Store summary and state in one locked rewrite
        stored_covers = convo_store.set_summary(
            self.conversation_id, summary_text, start,
            provenance=provenance_model.make(
                content=summary_text, source_actor="Wren", source_type="inference",
                original_source="rolling conversation summary", provenance_confidence="partial"),
            working_state=working_state, advance_only=True
        )
        
        if stored_covers:
            memory_store.set_working_state(working_state, source=f"conversation:{self.conversation_id}")
            
        return stored_covers

    def extract_memories(self, payload: SummaryPayload):
        """Injects decided facts and decisions into the long-term memory store."""
        # Decisions
        for dec in payload.get("settled_decisions", []):
            text = dec["text"].strip()
            if text and not self._is_duplicate(text, "decision"):
                prov = provenance_model.make(
                    content=text, source_actor="Wren", source_type="inference",
                    original_source=f"conversation:{self.conversation_id}",
                    observed_by_wren=True, provenance_confidence="known")
                self.mem_engine.add(text, "project", dec.get("scope", "global"), 
                                   f"conversation_rollover:{self.conversation_id}",
                                   kind="decision", why=dec.get("why"), guardrail=dec.get("guardrail"), 
                                   provenance=prov)

        # Evidence
        for ev in payload.get("evidence", []):
            fact = (ev.get("fact") or ev.get("content") or "").strip()
            if fact and not self._is_duplicate(fact, "fact"):
                src = ev.get("original_source") or "evidence"
                prov = provenance_model.normalize(ev, content=fact, trusted=True)
                self.mem_engine.add(fact, "project", "global", str(src), 
                                   kind="fact", confidence="inferred" if ev.get("verified_by_wren") else "stated", 
                                   provenance=prov)

    def _is_duplicate(self, text: str, kind: str) -> bool:
        """Optimized overlap check using the Engine's records."""
        records = self.mem_engine.get_records(include_deleted=False)
        for r in records:
            if r["kind"] == kind and self._overlap(text, r["text"]) > 0.8:
                return True
        return False

    def _overlap(self, a: str, b: str) -> float:
        wa, wb = set(_WORD_RE.findall(a.lower())), set(_WORD_RE.findall(b.lower()))
        if not wa or not wb: return 0.0
        return len(wa & wb) / float(min(len(wa), len(wb)))

    def execute(self, ahead_chars: int = 0) -> Dict[str, Any]:
        """Execution pipeline: Boundary $\rightarrow$ Extract $\rightarrow$ Persist."""
        start, covers, behind = self.calculate_boundary(ahead_chars)
        if behind < 1: return {"status": "no_update_needed"}

        conv = self.convo_engine.get_conversation(self.conversation_id)
        if not conv: return {"error": "no-such-conversation"}

        # 1. Prompting
        slice_turns = conv["turns"][covers:start]
        prev_summary = conv.get("summary") or "(no summary yet)"
        
        res = provider.complete(None, self.engine, self.build_prompt(prev_summary, slice_turns))
        if not res or not res.get("ok"):
            return {"error": res.get("reason", "provider-failed") if res else "provider-failed"}

        # 2. Parsing
        payload = self.parse_payload(res.get("content", ""))
        
        # 3. Persistence
        stored_covers = self.persist(payload, start)
        if stored_covers is None:
            return {"status": "superseded"}

        # 4. Memory Extraction
        self.extract_memories(payload)

        return {
            "covered": stored_covers, 
            "read": len(slice_turns), 
            "decisions": len(payload.get("settled_decisions", [])),
            "facts": len(payload.get("evidence", []))
        }

# --- ENTRY POINTS ---

def update(conversation_id, engine, ahead_chars=0):
    summarizer = SovereignSummarizer(conversation_id, engine)
    return summarizer.execute(ahead_chars)

def due(limit=5):
    out = []
    for c in convo_store.list_conversations(limit=50):
        summarizer = SovereignSummarizer(c["id"], "") # Engine not needed for boundary calc
        start, covers, behind = summarizer.calculate_boundary()
        if behind >= MIN_BEHIND:
            out.append({"id": c["id"], "start": start, "covers": covers, "behind": behind})
        if len(out) >= limit: break
    return out

def run_due(engine, limit=3):
    return [update(c["id"], engine) for c in due(limit=limit)]


def window_start(conversation_id, budget_chars=None):
    """The first turn index still inside the composition window."""
    win = convo_store.window(conversation_id, exclude_vault=False, budget_chars=budget_chars)
    return win.get("start", 0)


def long_thread_chars():
    """The char threshold past which an unsummarised thread is 'long'."""
    return convo_store.HISTORY_BUDGET_CHARS * 3 // 4
