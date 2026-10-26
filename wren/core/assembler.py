"""
Wren Assembly Engine v2.0: The Context Librarian.

This module is responsible for the selective retrieval and formatted assembly 
of memories, decisions, and working states. It transforms raw memory stores 
into a structured, budgeted, and provenance-labeled prompt section.

BEAUTY IS STRUCTURE. TRUTH IS PROVENANCE.
"""

import os
import re
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Final, TypedDict, Set, Union
from dataclasses import dataclass

from wren.mind import memory_store
from wren.tools import provenance as provenance_model
from wren.mind.memory import memory_line

# --- Type Definitions ---

class MemoryRecord(TypedDict, total=False):
    id: str
    text: str
    source: str
    type: str
    scope: str
    confidence: str
    kind: str
    confirmed: bool
    supersedes: Optional[str]
    created: str
    why: Optional[str]
    guardrail: Optional[str]
    retrieval: Optional[Dict[str, Any]]

class SourceReceipt(TypedDict):
    id: str
    source: str
    type: str
    scope: str
    confidence: str
    retrieved_from: str
    fresh_observation: bool
    provenance: str

class AssemblyResult(TypedDict):
    prompt_section: str
    sources: List[SourceReceipt]
    omitted: int

@dataclass(frozen=True)
class AssemblerConfig:
    """Immutable configuration for the Assembly Engine."""
    memory_budget_tokens: int
    chars_per_token: int = 4
    decision_max_items: int = 10
    decision_budget_chars: int = 2400
    working_state_budget_chars: int = 1600
    working_state_max_days: int = 7
    recency_filler_enabled: bool = False

# --- Constants & Patterns ---

_WORD_PATTERN: Final = re.compile(r"[a-z0-9']+")
_STOP_WORDS: Final = frozenset("""the and for are but not you your with that this have has had was were will would could should about from they
them their there then than what when where which while who whom why how can its into out over also just like some any all one our his
her she him very more most much many such only other been being does did done get got let may might must shall these those here
again once both each few own same too off per via yes""".split())

def _load_config() -> AssemblerConfig:
    """Loads configuration from environment with fallback defaults."""
    def get_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        try:
            return int(str(raw).strip()) if raw else default
        except ValueError:
            return default

    return AssemblerConfig(
        memory_budget_tokens=get_int("WREN_MEMORY_BUDGET_TOKENS", 700),
        recency_filler_enabled=str(os.environ.get("WREN_MEMORY_RECENCY_FILLER", "")).strip().lower() in ("1", "true", "yes", "on")
    )

CONFIG: Final = _load_config()
USUAL_PROVENANCE: Final = "Chris/user_message, unverified, known"
TAG_NOTE: Final = f"Every line is remembered, not fresh. A line with no provenance tag is {USUAL_PROVENANCE}."

class AssemblerEngine:
    """
    The engine responsible for selecting, ranking, and formatting 
    knowledge for prompt injection.
    """

    @staticmethod
    def _get_content_words(text: str) -> Set[str]:
        """Extracts significant content words for relevance scoring."""
        return {w for w in _WORD_PATTERN.findall(str(text or "").lower()) 
                if len(w) > 3 and w not in _STOP_WORDS}

    @staticmethod
    def _calculate_tokens(text: str) -> int:
        """Estimates token count based on character length."""
        return len(str(text or "")) // CONFIG.chars_per_token + 1

    @staticmethod
    def _get_tail(rec: MemoryRecord) -> str:
        """Generates the provenance label for a memory line."""
        label = provenance_model.prompt_label(memory_store.record_provenance(rec))
        suffix = "" if label == USUAL_PROVENANCE else f"; provenance: {label}"
        return f"  [source: {rec.get('source', '')}{suffix}]"

    @staticmethod
    def _create_receipt(rec: MemoryRecord) -> SourceReceipt:
        """Creates a source receipt for a retrieved memory."""
        return {
            "id": rec.get("id", "unknown"),
            "source": rec.get("source", "unknown"),
            "type": rec.get("type", "unknown"),
            "scope": rec.get("scope", "global"),
            "confidence": rec.get("confidence", "unknown"),
            "retrieved_from": "memory",
            "fresh_observation": False,
            "provenance": memory_store.record_provenance(rec)
        }

    @classmethod
    def _process_decisions(cls, records: List[MemoryRecord]) -> Tuple[str, List[SourceReceipt]]:
        """Processes the 'Decisions' lane: removes superseded, sorts, and budgets."""
        decs = [r for r in records if r.get("kind") == "decision"]
        superseded = {r.get("supersedes") for r in decs if r.get("supersedes")}
        decs = [r for r in decs if r.get("id") not in superseded]
        
        if not decs: return "", []

        # Sort: Scoped > Global, then Newest first
        decs.sort(key=lambda r: (r.get("scope") != "global", str(r.get("created") or ""), id(r)), reverse=True)
        
        chosen, spent = [], 0
        for rec in decs:
            if len(chosen) >= CONFIG.decision_max_items: break
            
            line = f"- {rec.get('text', '')}"
            if rec.get("why"): line += f" (why: {rec['why']})"
            if rec.get("guardrail"): line += f" [do not: {rec['guardrail']}]"
            line += cls._get_tail(rec)
            
            if spent + len(line) > CONFIG.decision_budget_chars: continue
            chosen.append((rec, line))
            spent += len(line)

        if not chosen: return "", []
        
        omitted_text = f"\n(+{len(decs) - len(chosen)} more decisions beyond budget)" if len(decs) > len(chosen) else ""
        body = "\n".join(line for _, line in chosen) + omitted_text
        
        section = (f"# Decisions already made\n"
                   f"These are settled. Do not quietly redesign or replace. "
                   f"Challenging one is allowed, but must be explicit.\n{TAG_NOTE}\n{body}")
        
        return section, [cls._create_receipt(r) for r, _ in chosen]

    @classmethod
    def _process_working_state(cls, ws_data: Optional[Dict], current_conv: Optional[str], now: Optional[datetime]) -> Tuple[str, List[SourceReceipt]]:
        """Processes the 'Working State' lane: handles expiration and formatting."""
        if not ws_data or not isinstance(ws_data, dict): return "", []
        
        state = ws_data.get("state") or {}
        stamp = str(ws_data.get("updated_at") or "").strip()
        
        try:
            written = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            written = None

        if written:
            age = (now or datetime.now()) - written
            if age.total_seconds() > CONFIG.working_state_max_days * 86400:
                return "", []
            when = f"at {stamp} ({int(age.total_seconds() // 3600)} hours ago)"
        else:
            when = "at an unknown time"

        # Formatting Logic
        lines, sources = [], []
        source_tag = ws_data.get("source", "conversation_rollover")
        
        # Active Task
        task = state.get("active_task") or state.get("task") or state.get("focus")
        if task:
            lines.append(f"- Active focus: {task}")
            sources.append(cls._create_receipt({"id": "ws:task", "source": source_tag, "scope": "global", "confidence": "inferred"}))

        # Evidence
        evid = state.get("evidence") or []
        if isinstance(evid, list) and evid:
            lines.append("- Evidence & verified findings:")
            for ev in evid[:5]:
                fact = ev.get("fact") if isinstance(ev, dict) else ev
                lines.append(f"  * {fact}")
                sources.append(cls._create_receipt({"id": "ws:evid", "source": source_tag, "scope": "global", "confidence": "stated"}))

        if not lines: return "", []
        
        content = "\n".join(lines)
        if len(content) > CONFIG.working_state_budget_chars:
            content = content[:CONFIG.working_state_budget_chars] + "..."
            
        header = (f"# Active working state and unresolved next steps\n"
                  f"Written {when}. This is background info and may be outdated. "
                  f"If it conflicts with current evidence, follow the newer information.\n")
        
        return header + content, sources

    @classmethod
    def _process_memories(cls, records: List[MemoryRecord], query: str, budget: int) -> Tuple[str, List[SourceReceipt], int]:
        """Processes the 'Memories' lane: Filters by keyword, scores relevance, and budgets tokens."""
        query_words = cls._get_content_words(query)
        # Handle pluralization for better recall
        asked = query_words | {w[:-1] for w in query_words if len(w) > 3 and w.endswith("s")}
        
        # 1. Filter: Keyword retrieval vs Durable records
        filtered = []
        for r in records:
            if r.get("kind") == "decision": continue
            
            # Keyword-mode records must have a trigger word
            retrieval = r.get("retrieval")
            if isinstance(retrieval, dict) and retrieval.get("mode") == "keywords":
                if not (asked & set(retrieval.get("words") or [])):
                    continue
            
            # If recency filler is off, must be durable or share content words
            if not CONFIG.recency_filler_enabled:
                is_durable = r.get("kind") == "context" or (r.get("kind") == "preference" and r.get("confirmed"))
                if not (is_durable or (cls._get_content_words(r.get("text", "")) & query_words)):
                    continue
            
            filtered.append(r)

        if not filtered: return "", [], 0

        # 2. Score and Rank
        def score_record(idx_rec):
            idx, rec = idx_rec
            words = set(_WORD_PATTERN.findall(str(rec.get("text", "")).lower()))
            overlap = len(words & query_words)
            recency = idx / max(len(filtered), 1)
            conf = {"stated": 0.2, "inferred": 0.1, "assumed": 0.0}.get(rec.get("confidence"), 0.0)
            return (overlap * 10) + recency + conf

        ranked = sorted(enumerate(filtered), key=score_record, reverse=True)

        # 3. Budget
        chosen, spent = [], 0
        for _, rec in ranked:
            kernel = memory_store.to_kernel(rec)
            if not kernel: continue
            line = f"- {memory_line(kernel)}" + cls._get_tail(rec)
            cost = cls._calculate_tokens(line)
            
            if spent + cost > budget: continue
            chosen.append((rec, line))
            spent += cost

        omitted_count = len(filtered) - len(chosen)
        if not chosen: return "", [], omitted_count
        
        lines = "\n".join(line for _, line in chosen)
        if omitted_count:
            lines += f"\n(+{omitted_count} more memories beyond budget — the Library holds everything)"
            
        section = (f"# What you remember\n"
                   f"Rely on facts, respect expiries, treat unconfirmed preferences as hypotheses.\n"
                   f"{TAG_NOTE}\n{lines}")
        
        return section, [cls._create_receipt(r) for r, _ in chosen], omitted_count

    @classmethod
    def assemble(cls, room_scopes: List[str], query: str = "", budget_tokens: Optional[int] = None, 
                  today: Any = None, current_conversation: Optional[str] = None, now: Optional[datetime] = None) -> AssemblyResult:
        """
        The primary entry point for assembling the context.
        Executes the three-lane pipeline: Decisions $\rightarrow$ Working State $\rightarrow$ Memories.
        """
        budget = budget_tokens if budget_tokens is not None else CONFIG.memory_budget_tokens
        records = memory_store.retrieve(room_scopes, today=today, limit=500)
        
        # Lane 1: Decisions
        dec_section, dec_sources = cls._process_decisions(records)
        
        # Lane 2: Working State
        ws_data = memory_store.get_working_state()
        ws_section, ws_sources = cls._process_working_state(ws_data, current_conversation, now)
        
        # Lane 3: Memories
        mem_section, mem_sources, omitted = cls._process_memories(records, query, budget)
        
        # Final Unification
        all_sections = [s for s in (dec_section, ws_section, mem_section) if s]
        return {
            "prompt_section": "\n\n".join(all_sections),
            "sources": dec_sources + ws_sources + mem_sources,
            "omitted": omitted
        }

# --- Public API ---
assemble = AssemblerEngine.assemble
