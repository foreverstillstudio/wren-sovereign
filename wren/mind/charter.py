# ============================================================
# WREN KERNEL — the charter (port of vale/core/charter.js)
# ------------------------------------------------------------
# Like the soul, the charter is DATA (wren/data/charter.json) and this
# module only reads and enforces it. Two halves:
#   1. The register — machine-readable. The refusal gate reads it, so
#      "consequential" is one list, not a list plus a paragraph that
#      slowly disagrees with it.
#   2. The text — assembled FROM the register, so the prose the model
#      reads can never drift from the rule the code enforces.
#
# Adding a kind to the register does not create an ability. Abilities
# live in the tool layer; anything unregistered is refused by default.
# ============================================================

import json
import os

# The charter is data too, loaded from the same directory as the soul.
from wren.mind.soul import data_dir as _soul_data_dir

_DATA = os.path.join(_soul_data_dir(), "charter.json")


def _load():
    """A missing or malformed charter is FATAL. Running without the law
    is worse than not running — an unlawed Wren would still sound like
    her while refusing nothing."""
    with open(_DATA, encoding="utf-8") as f:
        data = json.load(f)
    for key in ("consequential_actions", "internal_actions", "escalation_triggers", "text"):
        if not data.get(key):
            raise ValueError(f"wren/data/charter.json is missing '{key}'. Refusing to run without the charter.")
    return data


CHARTER = _load()

CHARTER_VERSION = CHARTER.get("charter_version", "0")
CONSEQUENTIAL_ACTIONS = CHARTER["consequential_actions"]
INTERNAL_ACTIONS = CHARTER["internal_actions"]
ESCALATION_TRIGGERS = CHARTER["escalation_triggers"]

_CONSEQUENTIAL_KINDS = {a["kind"] for a in CONSEQUENTIAL_ACTIONS}
_INTERNAL_KINDS = {a["kind"] for a in INTERNAL_ACTIONS}


def is_consequential(kind):
    return str(kind or "") in _CONSEQUENTIAL_KINDS


def is_executable(kind):
    """May this action kind execute once a human has approved it?"""
    return str(kind or "") in _INTERNAL_KINDS


def action_refusal_reason(kind):
    """The gate the executor calls. Returns why an action may not run, or
    None when it may. Consequential actions are refused OUTRIGHT — approval
    records the keeper's decision; it does not grant Wren a send button
    that does not exist."""
    k = str(kind or "")
    if not k:
        return "No action kind was given."
    if is_consequential(k):
        entry = next(a for a in CONSEQUENTIAL_ACTIONS if a["kind"] == k)
        return (f"{entry['label']} is a consequential action. Wren prepares it; "
                f"a person performs it. {entry['why']}")
    if not is_executable(k):
        return f'"{k}" is not a recognized action. Unrecognized actions are refused by default.'
    return None


def build_charter():
    """Assemble the charter text, filling the register into the prose so
    the two cannot disagree."""
    t = CHARTER["text"]
    body = t["body"].format(
        consequential="; ".join(a["label"].lower() for a in CONSEQUENTIAL_ACTIONS),
        escalations="\n".join(f"- {x}" for x in ESCALATION_TRIGGERS),
    )
    return f"{t['title']}\n{body}"


STEWARD_CHARTER = build_charter()
