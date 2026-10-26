# ============================================================
# WREN KERNEL — the calendar envelope store (Slice 1)
# ------------------------------------------------------------
# THIS MODULE NEVER READS HER CALENDAR. It cannot: the content
# key lives only on her devices, is never sent here, never put
# in a bundle, and never held by Fly.
#
# Its whole responsibility is to VALIDATE AND STORE AN OPAQUE
# ENVELOPE plus the few clear fields the server genuinely needs
# to synchronise and, later, to schedule:
#
#   id                stable record identity
#   rev               the compare-and-swap counter
#   remind_at         when to fire. A future reminder thread
#                     needs a clock, not a title.
#   reminders_active  the ONE bit needed to stop firing for a
#                     finished or cancelled item. The real
#                     status -- inbox, planned, waiting, done,
#                     cancelled, someday -- is meaning, and
#                     rides inside the envelope.
#   updated_at        server-stamped, for sync ordering
#   key_id            WHICH device key sealed this. Never a key.
#   envelope          the ciphertext. Opaque here, forever.
#
# Everything she would recognise as her life -- title, notes,
# life area, client, who she is waiting on, whether it is a task
# or an event, whether it is consequential -- is sealed before
# it leaves her device. No server-side function needs any of it,
# so none of it is here.
#
# Minimisation is ENFORCED, not documented: an unknown field is
# a refusal (_CLIENT_FIELDS below), and the stored shape is
# asserted against the allowlist on every write. A field cannot
# creep into the clear because someone added it to a payload.
#
# This layers ON TOP OF the kernel's at-rest encryption, not
# instead of it: the file goes through fortress_store's Fernet
# like every other store here. That key is the SERVER'S and
# protects the volume and its R2 backups. The envelope key is
# HERS and protects the meaning from the server. Losing the
# server key would expose reminder timestamps. It could never
# expose a word she wrote.
# ============================================================

import base64
import binascii
import json
import os
import re
import uuid
from datetime import datetime

# Named calendar_store, not calendar: a top-level calendar.py here would
# shadow the standard library's calendar module for every import in this
# process, including the ones datetime and email make.
STORE_FILENAME = "calendar_store.json"

# The complete set of fields the server may hold in the clear.
_META_FIELDS = ("id", "rev", "remind_at", "reminders_active",
                "updated_at", "key_id", "envelope")

# What a caller may send. rev and updated_at are the server's to set; a
# client that tries to set them is refused rather than silently ignored,
# because a client that believes it controls rev has misunderstood the CAS.
_CLIENT_FIELDS = ("id", "remind_at", "reminders_active", "key_id", "envelope")

# A Fernet token over even a short record runs to hundreds of characters.
# The floor catches a caller who sent something that is not ciphertext at
# all; the ceiling stops one record ballooning the store.
MIN_ENVELOPE_CHARS = 40
MAX_ENVELOPE_CHARS = 64000

MAX_REMINDERS = 32
MAX_KEY_ID_CHARS = 64

# Replay memory for idempotent retries. A phone that loses signal mid-write
# resends; the resend must not create a second record or burn a revision.
MAX_OPS_REMEMBERED = 500

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
                      r"-[0-9a-f]{4}-[0-9a-f]{12}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,%d}$" % MAX_KEY_ID_CHARS)

# Reminders are absolute UTC instants. A local wall-clock string would make
# the server guess a timezone, and a guessed timezone is a missed reminder.
_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class Refused(Exception):
    """The payload is malformed. The caller is told what; nothing partial
    is ever written."""


def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def store_path():
    # Beside the other kernel stores. server.py rebinds this to the mounted
    # volume at boot, exactly as it does for the conversation and memory
    # stores -- one pattern, not a second convention.
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        STORE_FILENAME)


def _blank():
    return {"records": [], "ops": []}


def _load():
    from fortress_store import _enc_read
    data = _enc_read(store_path(), _blank())
    if not isinstance(data, dict):
        data = _blank()
    data.setdefault("records", [])
    data.setdefault("ops", [])
    return data


def _save(data):
    from fortress_store import _enc_write
    _enc_write(store_path(), data)


# --- validation -------------------------------------------------------------

def _looks_like_cleartext(envelope):
    """True when the 'envelope' is something the server could read.

    The privacy promise is that the kernel CANNOT know what a record says.
    A caller that sends plain JSON -- in a hurry, in a test, in a future
    refactor -- would quietly break that promise and nothing would notice.
    So the store checks, and refuses.
    """
    probe = envelope.strip()
    try:
        json.loads(probe)
        return True
    except (ValueError, TypeError):
        pass
    try:
        raw = base64.urlsafe_b64decode(probe + "=" * (-len(probe) % 4))
    except (binascii.Error, ValueError):
        # Not base64 at all: malformed rather than leaky. _validate rejects
        # it separately, with a message that says which problem it is.
        return False
    try:
        json.loads(raw.decode("utf-8"))
        return True
    except (ValueError, UnicodeDecodeError):
        return False


def _validate(payload):
    """Return the clean client fields, or raise Refused.

    Unknown fields are refused, never dropped. Dropping would let a caller
    believe the server is holding something it is not, and would make the
    minimisation promise depend on nobody making a mistake.
    """
    if not isinstance(payload, dict):
        raise Refused("a record must be an object")

    allowed = set(_CLIENT_FIELDS) | {"expected_rev", "op_id"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise Refused(
            "these fields are not stored in the clear: %s. Everything that "
            "carries meaning belongs inside the envelope."
            % ", ".join(unknown))

    rec_id = payload.get("id")
    if not isinstance(rec_id, str) or not _UUID_RE.match(rec_id):
        raise Refused("id must be a lowercase uuid4 string")

    envelope = payload.get("envelope")
    if not isinstance(envelope, str):
        raise Refused("envelope must be a string")
    if not (MIN_ENVELOPE_CHARS <= len(envelope) <= MAX_ENVELOPE_CHARS):
        raise Refused("envelope must be between %d and %d characters"
                      % (MIN_ENVELOPE_CHARS, MAX_ENVELOPE_CHARS))
    try:
        base64.urlsafe_b64decode(envelope + "=" * (-len(envelope) % 4))
    except (binascii.Error, ValueError):
        raise Refused("envelope must be urlsafe-base64 ciphertext")
    if _looks_like_cleartext(envelope):
        raise Refused("envelope is readable -- the kernel must never receive "
                      "content it can decode. Seal it on the device first.")

    key_id = payload.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID_RE.match(key_id):
        raise Refused("key_id must be a short opaque identifier")

    remind_at = payload.get("remind_at", [])
    if not isinstance(remind_at, list):
        raise Refused("remind_at must be a list")
    if len(remind_at) > MAX_REMINDERS:
        raise Refused("at most %d reminders per record" % MAX_REMINDERS)
    for r in remind_at:
        if not isinstance(r, str) or not _INSTANT_RE.match(r):
            raise Refused("each reminder must be an absolute UTC instant, "
                          "YYYY-MM-DDTHH:MM:SSZ")

    active = payload.get("reminders_active", True)
    if not isinstance(active, bool):
        raise Refused("reminders_active must be true or false")

    return {"id": rec_id, "envelope": envelope, "key_id": key_id,
            "remind_at": sorted(remind_at), "reminders_active": active}


# --- reads ------------------------------------------------------------------

def list_records():
    """Every record: metadata plus sealed envelope. The caller decrypts."""
    from fortress_store import store_lock
    with store_lock():
        return list(_load()["records"])


def get(record_id):
    from fortress_store import store_lock
    with store_lock():
        for r in _load()["records"]:
            if r.get("id") == record_id:
                return dict(r)
    return None


def due_reminders(now_iso=None):
    """Records with a reminder at or before `now` that are still active.

    Slice 1 ships this read so a future reminder thread has a tested seam to
    stand on. It returns metadata only -- it could not compose a message if
    it wanted to.
    """
    from fortress_store import store_lock
    cutoff = now_iso or _now_iso()
    out = []
    with store_lock():
        for r in _load()["records"]:
            if not r.get("reminders_active"):
                continue
            for t in (r.get("remind_at") or []):
                if t <= cutoff:
                    out.append({"id": r["id"], "remind_at": t,
                                "rev": r["rev"], "key_id": r["key_id"]})
                    break
    return out


# --- the write --------------------------------------------------------------

def apply(payload, expected_rev=None, op_id=None):
    """Create or update one record under compare-and-swap.

    Returns (status, body):
      ("stored",    record)  applied; rev incremented
      ("duplicate", record)  this op_id already ran; nothing applied
      ("conflict",  record)  expected_rev is stale. NOTHING was overwritten;
                             the current record comes back so the caller can
                             merge instead of clobbering.

    A create is expected_rev 0 or None. Two devices editing the same record
    cannot silently lose one another's work: the loser is told.
    """
    from fortress_store import store_lock

    clean = _validate(payload)
    if op_id is not None and (not isinstance(op_id, str)
                              or not _UUID_RE.match(op_id)):
        raise Refused("op_id must be a uuid4 string")
    if expected_rev is not None and (isinstance(expected_rev, bool)
                                     or not isinstance(expected_rev, int)
                                     or expected_rev < 0):
        raise Refused("expected_rev must be a non-negative integer")

    with store_lock():
        data = _load()

        if op_id:
            for op in data["ops"]:
                if op.get("op_id") == op_id:
                    for r in data["records"]:
                        if r.get("id") == op.get("id"):
                            return "duplicate", dict(r)
                    return "duplicate", None

        current = None
        index = None
        for i, r in enumerate(data["records"]):
            if r.get("id") == clean["id"]:
                current, index = r, i
                break

        have = current["rev"] if current else 0
        want = 0 if (expected_rev is None and current is None) else expected_rev
        if want is None or want != have:
            return "conflict", (dict(current) if current else None)

        record = dict(clean)
        record["rev"] = have + 1
        record["updated_at"] = _now_iso()

        # The stored shape is exactly the allowlist. Asserted, not assumed:
        # this is the line the whole privacy claim rests on.
        assert set(record) == set(_META_FIELDS), sorted(set(record))

        if index is None:
            data["records"].append(record)
        else:
            data["records"][index] = record

        if op_id:
            data["ops"].append({"op_id": op_id, "id": record["id"],
                                "rev": record["rev"]})
            if len(data["ops"]) > MAX_OPS_REMEMBERED:
                data["ops"] = data["ops"][-MAX_OPS_REMEMBERED:]

        _save(data)
        return "stored", dict(record)


def new_id():
    return str(uuid.uuid4())
