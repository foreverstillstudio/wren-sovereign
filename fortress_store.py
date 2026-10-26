"""
fortress_store.py — sovereign edition.

Encrypted-at-rest JSON persistence, per steward. Fernet (AES-128-CBC + HMAC),
keyed per steward: GUARDIAN_ENCRYPTION_KEY for Wren, EMBER/MAEVE/ROWAN_STORE_KEY
for the sisters. Pure helpers — no Flask, no shared state beyond the locks.

Two APIs coexist:
  read_store(path, default, steward)            # per-steward encrypted read
  write_store(path, data, steward, compact=True) # per-steward encrypted write
  store_lock(steward=None)                      # reentrant lock (legacy callers omit steward)
  _enc_read(path, default)                      # legacy Wren-keyed read (calendar/tool stores)
  _enc_write(path, data)                        # legacy Wren-keyed write
"""

import json as _json
import os as _os
import threading as _threading
import uuid as _uuid

from cryptography.fernet import Fernet


class StoreUnreadable(Exception):
    """A store exists on disk but cannot be read — wrong or missing key, or a
    corrupted blob. Raised instead of returning the default, because "your desk
    is empty" and "your desk cannot be decrypted" are different mornings."""


# One process-wide reentrant lock guards every load -> mutate -> save sequence.
# Store writes are sub-millisecond JSON dumps; serializing them is correct and
# simple, and it matches the pre-sovereign behaviour.
_STORE_LOCK = _threading.RLock()


def store_lock(steward=None):
    """The reentrant lock guarding every load -> mutate -> save sequence."""
    return _STORE_LOCK


def _tmp_path(path):
    return "%s.%d.%d.%s.tmp" % (path, _os.getpid(), _threading.get_ident(),
                                _uuid.uuid4().hex[:8])


def _fernet_for(steward):
    from wren.system import steward_stores
    key = steward_stores.StewardResourceManager.get_key(steward)
    return Fernet(key.encode("utf-8"))


def _legacy_fernet():
    k = _os.environ.get("GUARDIAN_ENCRYPTION_KEY", "").strip()
    return Fernet(k.encode("utf-8")) if k else None


def _decrypt(blob, fernet):
    """Return the decrypted dict, or None if the blob is unreadable."""
    if fernet is not None:
        try:
            return _json.loads(fernet.decrypt(blob).decode("utf-8"))
        except Exception:
            pass
    # Migration path: the file predates encryption, or no key is configured.
    try:
        return _json.loads(blob.decode("utf-8"))
    except Exception:
        pass
    return None


def _enc_write(path, data):
    """Legacy (Wren-keyed) encrypted write — calendar/tool stores."""
    raw = _json.dumps(data, indent=2).encode("utf-8")
    fernet = _legacy_fernet()
    blob = fernet.encrypt(raw) if fernet else raw
    tmp = _tmp_path(path)
    with open(tmp, "wb") as f:
        f.write(blob)
    _os.replace(tmp, path)


def _enc_read(path, default):
    """Legacy (Wren-keyed) encrypted read — calendar/tool stores."""
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except FileNotFoundError:
        return default
    except Exception as e:
        raise StoreUnreadable("%s: unreadable (%s)" % (_os.path.basename(path), e))
    if not blob.strip():
        return default
    data = _decrypt(blob, _legacy_fernet())
    if data is not None:
        return data
    raise StoreUnreadable(
        "%s exists (%d bytes) but cannot be decrypted" % (_os.path.basename(path), len(blob)))


def write_store(path, data, steward, compact=True):
    """Per-steward encrypted write."""
    if compact:
        raw = _json.dumps(data, separators=(",", ":")).encode("utf-8")
    else:
        raw = _json.dumps(data, indent=2).encode("utf-8")
    blob = _fernet_for(steward).encrypt(raw)
    tmp = _tmp_path(path)
    with open(tmp, "wb") as f:
        f.write(blob)
    _os.replace(tmp, path)


def read_store(path, default, steward):
    """Per-steward encrypted read."""
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except FileNotFoundError:
        return default
    except Exception as e:
        raise StoreUnreadable("%s: unreadable (%s)" % (_os.path.basename(path), e))
    if not blob.strip():
        return default
    data = _decrypt(blob, _fernet_for(steward))
    if data is not None:
        return data
    raise StoreUnreadable(
        "%s exists (%d bytes) but cannot be decrypted" % (_os.path.basename(path), len(blob)))
