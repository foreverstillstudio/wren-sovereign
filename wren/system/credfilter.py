# ============================================================
# WREN KERNEL — Sovereign Credential Filter (Foundation)
# ------------------------------------------------------------
# PURPOSE: The final fail-closed gate preventing secrets from
# ever reaching a model prompt.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import re
from typing import (
    TypedDict, List, Optional, Dict, Any,
    Union, Final, cast
)
from types import MappingProxyType

# --- ARCHITECTURAL TYPES ---

class ScrubResult(TypedDict):
    text: str
    count: int

# --- CONSTANTS ---

PLACEHOLDER: Final = "[credential removed]"

# Keys that never contain credentials (identifiers, metadata, etc.)
_SKIP_KEYS: Final = frozenset({
    "role", "id", "type", "name", "tool_call_id", "call_id", "url", "image_url",
    "data", "mime_type", "media_type", "model", "finish_reason",
})

_BENIGN_VALUES: Final = frozenset({
    "required", "needed", "none", "null", "unset", "missing", "empty", "here", "below",
    "above", "stored", "hidden", "redacted", "removed", "optional", "true", "false",
    "set", "not", "wrong", "correct", "invalid", "valid", "expired", "secret", "private",
})

# --- REGEX PIPELINE ---

# Combined patterns for single-pass efficiency where possible
_PEM_RE: Final = re.compile(r"-----BEGIN [A-Z0-9 ]*-----.*?(?:-----END [A-Z0-9 ]*-----|\Z)", re.S)
_SK_RE: Final = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{5,}")
_BEARER_RE: Final = re.compile(r"\b(Bearer)(\s+)[A-Za-z0-9._~+/=-]{16,}", re.I)
_TOKENS_RE: Final = re.compile(
    r"\bgh[pousr]_[A-Za-z0-9]{20,}"                      # GitHub
    r"|\bAKIA[0-9A-Z]{16}\b"                             # AWS access key id
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"                   # Slack
    r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"   # JWT
)
_HINT_RE: Final = re.compile(
    r'''(?P<hint>(?<![A-Za-z])(?:api[ _-]?key|secret[ _-]?key|access[ _-]?token|auth[ _-]?token|password|passphrase|credentials?|private[ _-]?key)[A-Za-z0-9_]*)(?P<sep>\s*(?:[:=]|\bis\b|\bare\b)\s*)(?P<q>["'`]?)(?P<val>[^\s"',;]{4,})''',
    re.I
)

# --- SOVEREIGN FILTER ENGINE ---

class SovereignCredentialFilter:
    """
    A stateless, high-fidelity filter for the removal of credentials.
    Implemented as a Singleton for consistent resource management.
    """
    _instance: Optional['SovereignCredentialFilter'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SovereignCredentialFilter, cls).__new__(cls)
        return cls._instance

    def _hint_replacement(self, match: re.Match) -> str:
        """Logic to determine if a hint-matched value is actually a secret."""
        val = match.group("val")
        low = val.lower()

        # 1. Exclude code-like patterns or environment references
        if (val.startswith(("[", "$", "%", "<", "{", "(", "os.", "env", "process.", "config", "self."))
                or "(" in val or low in _BENIGN_VALUES or low.rstrip(".") in _BENIGN_VALUES):
            return match.group(0)

        # 2. Heuristic for "is/are" plain-English hints
        if ":" not in match.group("sep") and "=" not in match.group("sep"):
            looks_secret = (
                re.search(r"[0-9]|[^A-Za-z]", val) is not None
                or (any(c.isupper() for c in val) and any(c.islower() for c in val))
                or len(val) >= 14
            )
            if not looks_secret:
                return match.group(0)

        return match.group("hint") + match.group("sep") + match.group("q") + PLACEHOLDER

    def scrub_text(self, text: Any) -> ScrubResult:
        """
        Performs a multi-pass scrub of a string.
        Returns a ScrubResult containing the cleaned text and total replacements.
        """
        if not isinstance(text, str) or not text:
            return {"text": text, "count": 0}

        count = 0
        current_text = text

        # Regex pipeline
        # 1. Standard Tokens (PEM, SK, Bearer, API Tokens)
        def tally_and_replace(match: re.Match, replacement: Union[str, callable]) -> str:
            nonlocal count
            count += 1
            return replacement(match) if callable(replacement) else replacement

        current_text = _PEM_RE.sub(lambda m: tally_and_replace(m, PLACEHOLDER), current_text)
        current_text = _SK_RE.sub(lambda m: tally_and_replace(m, PLACEHOLDER), current_text)
        current_text = _BEARER_RE.sub(
            lambda m: tally_and_replace(m, lambda x: x.group(1) + x.group(2) + PLACEHOLDER),
            current_text
        )
        current_text = _TOKENS_RE.sub(lambda m: tally_and_replace(m, PLACEHOLDER), current_text)

        # 2. Hint-based values
        def hint_handler(match: re.Match) -> str:
            nonlocal count
            res = self._hint_replacement(match)
            if res != match.group(0):
                count += 1
            return res

        current_text = _HINT_RE.sub(hint_handler, current_text)

        return {"text": current_text, "count": count}

    def scrub_value(self, value: Any, key: Optional[str] = None) -> Any:
        """
        Deep recursive scrub of any data structure.
        Implements the _SKIP_KEYS optimization to avoid scanning metadata.
        """
        if isinstance(value, str):
            if key in _SKIP_KEYS:
                return value
            return self.scrub_text(value)["text"]

        if isinstance(value, list):
            return [self.scrub_value(v, key) for v in value]
        if isinstance(value, tuple):
            return tuple(self.scrub_value(v, key) for v in value)
        if isinstance(value, dict):
            return {k: self.scrub_value(v, k) for k, v in value.items()}

        return value

    def has_credential(self, text: str) -> bool:
        """Boolean check for credential presence."""
        return self.scrub_text(text)["count"] > 0

# --- PUBLIC INTERFACE (Bridge to Legacy) ---

def scrub_text(text: str) -> tuple[str, int]:
    res = SovereignCredentialFilter().scrub_text(text)
    return res["text"], res["count"]

def has_credential(text: str) -> bool:
    return SovereignCredentialFilter().has_credential(text)

def scrub_value(value: Any, _key: Optional[str] = None) -> Any:
    return SovereignCredentialFilter().scrub_value(value, _key)

def scrub_messages(messages: Any) -> Any:
    return SovereignCredentialFilter().scrub_value(messages)

def scrub_result(normalized: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a tool result's output fields."""
    out = dict(normalized)
    filter_engine = SovereignCredentialFilter()
    for key in ("stdout", "stderr", "target", "error", "data"):
        if key in out:
            out[key] = filter_engine.scrub_value(out[key], key if key != "data" else None)
    return out
