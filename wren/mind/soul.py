# ============================================================
# WREN KERNEL — the soul projection (sovereign edition)
# ------------------------------------------------------------
# The soul is DATA — wren/mind/soul.json — and this module only
# reads and composes it. "The soul is data; the body reads it"
# (doc 11): every body reads the same file, so they cannot drift
# into two Wrens.
# ============================================================

import json
import os

from wren.system import stewards

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_DATA_DIR, "soul.json")

_REQUIRED = ("name", "essence", "temperament", "voice_rules", "refusals")


def _load(path=_DATA):
    """A missing or malformed soul is FATAL — a steward without their
    soul is not a quieter steward, they are a generic assistant wearing
    the name, which the charter forbids."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in _REQUIRED if not str(data.get(k, "")).strip()]
    if missing:
        raise ValueError(
            f"{os.path.basename(path)} is missing required soul fields: "
            f"{missing}. Refusing to run without a soul.")
    return data


SOUL = _load()
SOUL_VERSION = SOUL.get("soul_version", "0")
NAME = SOUL["name"]

_HEADINGS = SOUL.get("section_headings", {})


def data_dir():
    """The directory holding soul.json (and charter.json)."""
    return _DATA_DIR


def version():
    """The soul version, read from the soul itself rather than packaging
    metadata — so what a body reports is what a body actually loaded."""
    return SOUL_VERSION


def soul_of(steward_id="wren"):
    """The soul data of a locally-embodied steward. Asking for a steward
    with no local soul is a caller error and raises: no soul may ever be
    invented."""
    sid = str(steward_id or "wren").strip().lower()
    fname = stewards.get_local_soul_path(sid)
    if not fname:
        raise ValueError(f"steward {sid!r} has no local soul file — "
                         "refusing to invent an identity.")
    return _load(os.path.join(_DATA_DIR, fname))


# --- the keeper block (doc 00.6) ------------------------------------------
# The soul names who Wren IS; the keeper names who she SERVES. Loaded from
# keeper.json when present, otherwise the honest default — she never
# fabricates a keeper.
_KEEPER_PATH = os.path.join(_DATA_DIR, "keeper.json")

_DEFAULT_PROFILE = {
    "keeper_name": "",
    "keeper_description": "",
    "house_name": "this house",
    "house_description": "",
}

_DEFAULT_HOUSE_BOUNDARY = ("What you learn here belongs to this house and never "
                           "travels to another.")


def _clean(value, limit):
    return str(value if value is not None else "").replace("\n", " ").strip()[:limit]


def _keeper_profile():
    profile = dict(_DEFAULT_PROFILE)
    if not os.path.exists(_KEEPER_PATH):
        return profile
    try:
        with open(_KEEPER_PATH, encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        return profile
    if not isinstance(raw, dict):
        return profile
    for key, limit in (("keeper_name", 80), ("keeper_description", 200),
                       ("house_name", 80), ("house_description", 300)):
        if raw.get(key):
            profile[key] = _clean(raw[key], limit)
    if not profile["house_name"]:
        profile["house_name"] = _DEFAULT_PROFILE["house_name"]
    return profile


def _keeper_block(house_boundary=None):
    p = _keeper_profile()
    if p["keeper_name"]:
        who = f"You serve the keeper of {p['house_name']} — {p['keeper_name']}"
        if p["keeper_description"]:
            who += f", {p['keeper_description']}"
        who += "."
    else:
        who = (f"You serve the keeper of {p['house_name']}. You have not been "
               "told their name yet; ask rather than assume it.")
    house = f" {p['house_description']}" if p["house_description"] else ""
    boundary = (str(house_boundary).strip() if str(house_boundary or "").strip()
                else _DEFAULT_HOUSE_BOUNDARY)
    return (
        f"{who}{house} You do not belong to the keeper; you serve them. "
        "The keeper provides the story, values, and decisions that make this "
        "house unique; you provide the continuity, care, and stewardship "
        "that help it endure. You learn how the keeper thinks in order to "
        "prepare work in their direction — never to imitate them. "
        + boundary
    )


def build_identity(keeper_profile=None, steward="wren"):
    """The identity block of the system prompt. Charter comes AFTER this
    (duties may extend the identity; nothing may quietly override it).
    The first four sections are soul — constant everywhere; only the
    fifth (keeper) is per-house. `steward` picks whose soul speaks."""
    s = soul_of(steward)
    hs = s.get("section_headings", {})
    return "\n\n".join([
        f"# {hs.get('essence', 'Who you are')}\n{s['essence']}",
        f"# {hs.get('temperament', 'Your temperament')}\n{s['temperament']}",
        f"# {hs.get('voice_rules', 'How you speak')}\n{s['voice_rules']}",
        f"# {hs.get('refusals', 'What you refuse')}\n{s['refusals']}",
        f"# {hs.get('keeper', 'Who you serve')}\n"
        f"{_keeper_block(s.get('house_boundary'))}",
    ])
