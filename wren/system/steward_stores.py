# ============================================================
# WREN KERNEL — Sovereign Stewardship Engine (Foundation)
# ------------------------------------------------------------
# PURPOSE: Manages the isolation of encrypted stores, keys, 
# and locks for each sovereign companion.
# STANDARD: Pure (Lean/Stable) & Exemplary (Type-Safe/Rigorous).
# ============================================================

import contextlib
import contextvars
import os
import threading
from typing import (
    TypedDict, List, Optional, Dict, Any, 
    Union, Final, Literal, cast
)
from types import MappingProxyType

# --- ARCHITECTURAL TYPES ---

StewardName = Literal["wren", "ember", "maeve", "rowan"]

class StewardConfig(TypedDict):
    key_env: str
    is_legacy: bool

# --- CONSTANTS ---

STORE_STEWARDS: Final = ("wren", "ember", "maeve", "rowan")

STEWARD_CONFIGS: Final = MappingProxyType({
    "wren":  {"key_env": "GUARDIAN_ENCRYPTION_KEY", "is_legacy": True},
    "ember": {"key_env": "EMBER_STORE_KEY", "is_legacy": False},
    "maeve": {"key_env": "MAEVE_STORE_KEY", "is_legacy": False},
    "rowan": {"key_env": "ROWAN_STORE_KEY", "is_legacy": False},
})

HOUSE_KEY_ENV: Final = "HOUSE_WORK_KEY"
GUEST_ROOM_KEEPERS: Final = MappingProxyType({"vale": "wren"})

# --- EXCEPTIONS ---

class StewardStoreError(Exception):
    """Base for all stewardship failures."""

class UnknownStewardStore(StewardStoreError, ValueError):
    """Companion name is not recognized."""

class NoStewardScope(StewardStoreError):
    """Store accessed without an active steward context."""

class StoreKeyError(StewardStoreError):
    """Key is missing, invalid, or reused."""

# --- CONTEXT MANAGEMENT ---

_scope: Final = contextvars.ContextVar("wren_steward_store_scope", default=None)

class StewardshipContext:
    """
    Manages the ambient identity of the current store caller.
    Ensures fail-closed behavior for all store operations.
    """
    @staticmethod
    def normalize(name: Any) -> StewardName:
        s = str(name).strip().lower() if isinstance(name, str) else ""
        if s not in STORE_STEWARDS:
            raise UnknownStewardStore(f"{name!r} is not a recognized steward.")
        return cast(StewardName, s)

    @staticmethod
    @contextlib.contextmanager
    def scope(name: Union[str, StewardName]):
        token = _scope.set(StewardshipContext.normalize(name))
        try:
            yield
        finally:
            _scope.reset(token)

    @staticmethod
    def current() -> StewardName:
        s = _scope.get()
        if s is None:
            raise NoStewardScope("No steward scope active. Store access denied.")
        return cast(StewardName, s)

# --- RESOURCE RESOLUTION ---

class StewardResourceManager:
    """
    Resolves physical paths, encryption keys, and thread locks 
    based on the active steward.
    """
    _LOCKS: Dict[StewardName, threading.RLock] = {}
    _LOCKS_GUARD: Final = threading.Lock()

    @staticmethod
    def resolve_steward(speaker: Any) -> StewardName:
        """Maps a speaker identity to a store-owning steward."""
        s = str(speaker).strip().lower() if isinstance(speaker, str) else ""
        if s in STORE_STEWARDS:
            return cast(StewardName, s)
        if s in GUEST_ROOM_KEEPERS:
            return cast(StewardName, GUEST_ROOM_KEEPERS[s])
        raise UnknownStewardStore(f"No store assigned to speaker {speaker!r}")

    @staticmethod
    def get_store_path(base_path: str, steward: Optional[StewardName] = None) -> str:
        """Resolves the physical path for a steward's store."""
        steward = steward or StewardshipContext.current()
        if steward == "wren":
            return base_path
        
        # Path: <dir>/stewards/<name>/<filename>
        return os.path.join(
            os.path.dirname(base_path), 
            "stewards", 
            steward, 
            os.path.basename(base_path)
        )

    @staticmethod
    def get_key(steward: StewardName) -> str:
        """Retrieves and validates the encryption key for a steward."""
        config = STEWARD_CONFIGS[steward]
        env_name = config["key_env"]
        raw_key = os.environ.get(env_name, "").strip()
        
        if not raw_key:
            raise StoreKeyError(f"Key {env_name} is missing for {steward}.")
            
        # Check for key reuse across stewards
        for other, other_cfg in STEWARD_CONFIGS.items():
            if other != steward:
                if os.environ.get(other_cfg["key_env"]) == raw_key:
                    raise StoreKeyError(f"Key collision between {steward} and {other}.")
        
        # Check for collision with House key
        if os.environ.get(HOUSE_KEY_ENV) == raw_key:
            raise StoreKeyError(f"Steward {steward} is using the shared House key.")
            
        return raw_key

    @staticmethod
    def get_lock(steward: StewardName, legacy_lock: Optional[threading.Lock] = None) -> threading.RLock:
        """Provides a reentrant lock per steward to prevent store corruption."""
        if steward == "wren":
            if legacy_lock is None:
                raise StewardStoreError("Legacy lock required for Wren's store.")
            return cast(threading.RLock, legacy_lock)
            
        with StewardResourceManager._LOCKS_GUARD:
            if steward not in StewardResourceManager._LOCKS:
                StewardResourceManager._LOCKS[steward] = threading.RLock()
            return StewardResourceManager._LOCKS[steward]

# --- PUBLIC INTERFACE (Bridge to Legacy) ---

def steward_scope(name):
    return StewardshipContext.scope(name)

def current():
    return StewardshipContext.current()

def store_file(wren_path, steward=None):
    return StewardResourceManager.get_store_path(wren_path, steward)

def normalize(name):
    """Canonical steward name, or UnknownStewardStore."""
    return StewardshipContext.normalize(name)

def require_openable(steward):
    """Raise StewardStoreError if the steward's store cannot be opened
    (their encryption key is missing or collides)."""
    StewardResourceManager.get_key(steward)

def storage_steward(speaker):
    """The steward whose store holds a speaker's data (guests map to their host)."""
    return StewardResourceManager.resolve_steward(speaker)

def lock_for(steward, legacy_lock):
    return StewardResourceManager.get_lock(steward, legacy_lock)

def key_status():
    """Returns the health of all steward keys."""
    status = {}
    for s in STORE_STEWARDS:
        try:
            StewardResourceManager.get_key(s)
            status[s] = "ok"
        except StoreKeyError as e:
            status[s] = str(e)
    return status


def test_default_active():
    """True when a test-only default steward is installed in the roster.

    The sovereign roster (wren, ember, maeve, rowan) contains no test or
    placeholder steward, so this guard is always clean. Kept as a named
    hook so preflight() can keep its fail-closed check without coupling to
    the roster's internals."""
    return False
