# ============================================================
# WREN KERNEL — is each companion's store ready? (for /health)
# ------------------------------------------------------------
# Job 8 (Chrissy, 2026-10-18): /health shows, per companion, only READY or NOT READY and
# store counts. Never a key, never a word of a conversation or a memory.
#
#   ready  — her key is present, valid and distinct, and her stores (if they exist) open.
#            A companion who has never spoken is ready with zero counts: an empty store is
#            not a broken one.
#   counts — conversations in her store, and active memories. Shown only to a caller who
#            is signed in (the device token): /health is open to anyone who can reach the
#            port, and how much someone has said is not for everyone.
#
# /health must stay fast and must never wait on a 60 MB decrypt. The first answer is the
# cheap one (keys only). The counts come from a cache that a BACKGROUND thread refreshes,
# and only when a store file has actually changed (size or time), at most every
# MIN_REFRESH_SECONDS. Nothing is read while nothing changes.
# ============================================================

import os
import threading
import time

from wren.system import steward_stores as S

MIN_REFRESH_SECONDS = 15

_lock = threading.Lock()
_state = {"signature": None, "data": None, "at": 0.0, "running": False}


def _store_paths():
    from wren.mind import conversations, memory_store
    out = []
    for name in S.STORE_STEWARDS:
        out.append(S.store_file(conversations.store_path(), name))
        out.append(S.store_file(memory_store.store_path(), name))
    return out


def signature():
    """What the store files look like right now (name, size, time) — cheap, no reading."""
    sig = []
    for p in _store_paths():
        try:
            st = os.stat(p)
            sig.append((p, st.st_size, st.st_mtime_ns))
        except OSError:
            sig.append((p, None, None))
    return tuple(sig)


def keys_only():
    """The cheap answer: ready means the key is usable. Counts unknown."""
    status = S.key_status()
    return {n: {"ready": status[n] == "ok", "conversations": None, "memories": None}
            for n in S.STORE_STEWARDS}


def _probe_one(name):
    """One companion, inside her own scope. Never raises, never returns text."""
    status = S.key_status().get(name)
    if status != "ok":
        return {"ready": False, "conversations": None, "memories": None}
    try:
        from wren.mind import conversations, memory_store
        with S.steward_scope(name):
            convs = conversations.status()
            mems = memory_store.status()
        return {"ready": True,
                "conversations": int(convs.get("conversations", 0)),
                "memories": int((mems.get("by_status") or {}).get("active", 0))}
    except Exception:
        return {"ready": False, "conversations": None, "memories": None}


def refresh_now():
    """Recompute everything now (used by the background thread, and by tests)."""
    sig = signature()
    data = {n: _probe_one(n) for n in S.STORE_STEWARDS}
    with _lock:
        _state.update(signature=sig, data=data, at=time.time(), running=False)
    return data


def _refresh_in_background():
    try:
        refresh_now()
    except Exception:
        with _lock:
            _state["running"] = False


def snapshot():
    """The cached answer (or the keys-only one), starting a background refresh when a store
    file has changed since the last one. Never blocks on a read."""
    sig = signature()
    start = False
    with _lock:
        stale = _state["data"] is None or sig != _state["signature"]
        if (stale and not _state["running"]
                and time.time() - _state["at"] >= MIN_REFRESH_SECONDS):
            _state["running"] = True
            start = True
        data = _state["data"]
    if start:
        threading.Thread(target=_refresh_in_background, name="wren-health-counts", daemon=True).start()
    cheap = keys_only()
    if data is None:
        return cheap, None
    # a key that has gone missing since the last refresh shows at once
    merged = {n: {**data[n], "ready": bool(data[n]["ready"] and cheap[n]["ready"])} for n in S.STORE_STEWARDS}
    return merged, _state["at"]


def health_view(authorized):
    """The `stewards` object for /health."""
    data, at = snapshot()
    out = {}
    for name in S.STORE_STEWARDS:
        item = {"ready": bool(data[name]["ready"])}
        if authorized:
            item["conversations"] = data[name]["conversations"]
            item["memories"] = data[name]["memories"]
        out[name] = item
    return out


def reset():
    """For tests."""
    with _lock:
        _state.update(signature=None, data=None, at=0.0, running=False)
