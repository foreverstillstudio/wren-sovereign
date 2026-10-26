# ============================================================
# WREN KERNEL — Chrissy's publish rules, enforced on the signed path
# ------------------------------------------------------------
# Chrissy, 2026-10-18: nothing is published, pushed, deployed or sent without
# her yes. Her rules:
#     destroys                       irreversible destruction
#     spends                         spending money
#     speaks_as_her                  sending or posting as her (mail, SMS, forms,
#                                    calendar invites to other people)
#     publishes                      publishing, pushing, deploying
#     moves_credentials_off_machine  credential logins and secret edits
#
# Two things are checked on EVERY model tool call, before the call is accepted
# (tool_protocol.normalize_model_calls):
#   1. the tool's own `rule` in tools.registry.json (with its `rule_when`);
#   2. the text of any argument that carries a COMMAND, against the red patterns
#      carried over from the desktop executor (wren-autonomous-tools.js
#      RED_PATTERNS): git push, gh pr/issue/release/repo, vercel --prod,
#      wrangler deploy, npm publish, destructive deletes, credential edits.
# A hit is refused ("approval-required", 403) unless the call carries a valid
# APPROVAL TOKEN.
#
# A token is never supplied by the model: it is passed in by the trusted client
# after Chrissy has said yes. It is an HMAC over {tool, rules, sha256 of the
# arguments, expiry, nonce} with WREN_APPROVAL_SECRET (kernel environment, 32+
# characters), single-use, short-lived, and bound to those exact arguments. With
# no secret configured nothing can validate: it fails closed.
# ============================================================

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

RULES = ("destroys", "spends", "speaks_as_her", "publishes", "moves_credentials_off_machine")

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "tools" / "tools.registry.json"

# Carried over, pattern for pattern, from the desktop's RED_PATTERNS. Each is
# mapped to the nearest of her five rules.
_RED = [
    (r"\bgit\s+(-C\s+\S+\s+)?push\b", "git push", "publishes"),
    (r"\bgit\s+(-C\s+\S+\s+)?reset\s+--hard\b", "git reset --hard", "destroys"),
    (r"\bgit\s+(-C\s+\S+\s+)?clean\s+-[a-zA-Z]*f", "git clean -f", "destroys"),
    (r"\bgit\s+(-C\s+\S+\s+)?rebase\b", "git rebase", "destroys"),
    (r"\bgit\s+(-C\s+\S+\s+)?filter-branch\b", "git filter-branch", "destroys"),
    (r"\bgit\s+(-C\s+\S+\s+)?branch\s+(-D|-d)\b", "git branch deletion", "destroys"),
    (r"\b(rmdir|rd)\s+/s", "destructive rmdir /s", "destroys"),
    (r"\bdel\s+/s", "destructive del /s", "destroys"),
    (r"\brm\s+-r?[fF]", "destructive rm -rf", "destroys"),
    (r"\bRemove-Item\b.*-Recurse.*-Force", "destructive Remove-Item -Recurse -Force", "destroys"),
    (r"\bvercel\s+(deploy\s+)?--prod\b", "vercel production deployment", "publishes"),
    (r"\bvercel\s+(promote|rollback|remove|rm|env\s+(add|rm))\b", "vercel deployment or mutation", "publishes"),
    (r"\bwrangler\s+(deploy|publish|delete|secret|kv:key\s+(put|delete)|d1\s+execute|r2\s+object\s+(put|delete))\b",
     "cloudflare/wrangler deployment or mutation", "publishes"),
    (r"\bgh\s+(pr|issue|release|repo)\s+(create|merge|close|delete|edit|archive)\b",
     "github PR/issue/repo mutation", "publishes"),
    (r"\b(npm|pnpm|yarn)\s+(run\s+)?publish\b", "package publish", "publishes"),
    (r"\b(auth\s+login|wrangler\s+login|vercel\s+login)\b", "credential login mutation",
     "moves_credentials_off_machine"),
    (r"(Set-Content|Add-Content|Out-File|Clear-Content)\s+.*(\.fsb-tokens\.env|\.env)"
     r"|(\.fsb-tokens\.env|\.env)\b.*(>|>>|Set-Content|Add-Content|Out-File)",
     "credential/secret alteration", "moves_credentials_off_machine"),
    (r"\b(drop\s+database|drop\s+table)\b", "database drop", "destroys"),
    # Added here (not in the desktop list): the desktop pattern only catches `.env` BEFORE a
    # redirect, so `echo X=1 >> .env` slipped past it.
    (r">>?\s*\S*\.env\b", "credential/secret alteration (redirect into .env)",
     "moves_credentials_off_machine"),
]
RED_PATTERNS = [(re.compile(p, re.I), reason, rule) for p, reason, rule in _RED]

# Argument names that carry command text on any tool, registered or not.
COMMAND_ARG_NAMES = frozenset({"command", "cmd", "shell", "powershell", "commandline", "command_line"})
_INVITE_KEYS = frozenset({"attendees", "attendee", "guests", "invitees", "invite", "invites",
                          "participants", "emails", "to", "cc", "bcc"})
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


class ApprovalHit:
    __slots__ = ("rule", "reason")

    def __init__(self, rule, reason):
        self.rule, self.reason = rule, reason

    def __repr__(self):
        return "ApprovalHit(%s: %s)" % (self.rule, self.reason)


def classify_command(text):
    """[(rule, reason)] for every red pattern the command text trips."""
    if not isinstance(text, str):
        return []
    return [(rule, reason) for rx, reason, rule in RED_PATTERNS if rx.search(text)]


# ── registry (cached by modification time) ──────────────────

_cache = {"mtime": None, "reg": None}


def _registry():
    try:
        mtime = REGISTRY_PATH.stat().st_mtime_ns
    except OSError:
        return {"tools": {}, "aliases": {}}
    if _cache["mtime"] != mtime:
        _cache["reg"] = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
    return _cache["reg"]


def _as_dict(arguments):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def invites_others(arguments):
    """A calendar call invites other people when it names attendees, or when any
    of its text carries an email address."""
    args = _as_dict(arguments)
    for key, value in args.items():
        if str(key).lower() in _INVITE_KEYS and value not in (None, "", [], {}):
            return True

    def strings(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                yield from strings(x)
    return any(_EMAIL.search(s) for s in strings(args))


def hits_for_call(name, arguments):
    """Which of Chrissy's rules this exact call trips. [] means no approval needed."""
    reg = _registry()
    canonical = reg.get("aliases", {}).get(name, name)          # an alias cannot dodge its tool's rule
    entry = reg.get("tools", {}).get(canonical) or {}
    args = _as_dict(arguments)
    hits = []
    rule = entry.get("rule")
    when = entry.get("rule_when", "always")
    if rule in RULES and (when == "always" or (when == "invites_others" and invites_others(args))):
        hits.append(ApprovalHit(rule, "%s (%s)" % (canonical, when)))
    elif entry.get("requires_approval") and not rule:
        hits.append(ApprovalHit("speaks_as_her", "%s requires approval" % canonical))
    command_args = set(COMMAND_ARG_NAMES)
    if entry.get("command_arg"):
        command_args.add(entry["command_arg"])
    for key, value in args.items():
        if str(key).lower() in command_args or key in command_args:
            for r, reason in classify_command(value):
                hits.append(ApprovalHit(r, reason))
    return hits


# ── approval tokens ─────────────────────────────────────────

_USED = {}          # nonce -> expiry (single use; pruned as it goes)


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _args_digest(arguments):
    canon = json.dumps(_as_dict(arguments), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _secret():
    value = os.environ.get("WREN_APPROVAL_SECRET", "").strip()
    return value.encode("utf-8") if len(value) >= 32 else None


def issue_approval(secret, name, arguments, rules, ttl=300, now=None):
    """Make a token for ONE call. Used by the approval step that follows
    Chrissy's yes (and by tests); the model never sees or makes one."""
    now = int(now if now is not None else time.time())
    payload = {"v": 1, "tool": name, "rules": sorted(set(rules)),
               "args": _args_digest(arguments), "exp": now + int(ttl),
               "nonce": secrets.token_urlsafe(16)}
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(secret if isinstance(secret, bytes) else secret.encode("utf-8"),
                        body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + sig


def verify_approval(token, name, arguments, rules, now=None, secret=None):
    """True only for an unexpired, unused token signed with the configured
    secret for exactly this tool, these arguments, and at least these rules."""
    key = secret if secret is not None else _secret()
    if not key or not isinstance(token, str) or token.count(".") != 1:
        return False
    body, sig = token.split(".")
    want = hmac.new(key if isinstance(key, bytes) else key.encode("utf-8"),
                    body.encode("ascii"), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(want, _unb64(sig)):
            return False
        payload = json.loads(_unb64(body))
    except Exception:
        return False
    now = int(now if now is not None else time.time())
    for nonce, exp in list(_USED.items()):
        if exp < now:
            del _USED[nonce]
    if (payload.get("v") != 1 or payload.get("tool") != name
            or payload.get("args") != _args_digest(arguments)
            or not set(rules) <= set(payload.get("rules", []))
            or int(payload.get("exp", 0)) < now
            or payload.get("nonce") in _USED or not payload.get("nonce")):
        return False
    _USED[payload["nonce"]] = int(payload["exp"])
    return True


def enforce(name, arguments, approval=None, now=None):
    """Refuse a call that trips one of her rules unless it carries a valid
    approval token. Raises tool_protocol.ProtocolError("approval-required", 403)."""
    hits = hits_for_call(name, arguments)
    if not hits:
        return
    rules = sorted({h.rule for h in hits})
    if approval and verify_approval(approval, name, arguments, rules, now=now):
        return
    from wren.tools.tool_protocol import ProtocolError
    err = ProtocolError("approval-required", 403)
    err.rules = rules
    err.reasons = [h.reason for h in hits]
    raise err
