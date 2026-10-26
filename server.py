"""The always-on Wren kernel.
Sovereign Edition: Architecture updated to Cognitive Map lobes.
Lock requirements removed for safe recovery boot.
"""

import os
import re
import sys
import threading
import time
import hashlib
import functools
import subprocess  # Added missing import for start_backup
from flask import Flask, Response, g, jsonify, make_response, request

BRIDGE_URL = "http://192.168.40.96:5002"

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- LOBE WIRING ---
import calendar_store
from wren.mind import soul as wren_soul

# Mind Lobe
from wren.mind import conversations as convo_store
from wren.mind import memory_store
from wren.mind import memory_tools

# Core Lobe
from wren.core import gateway
from wren.core import continuity

# Tools Lobe
from wren.tools import sanctuary_adapter
from wren.tools import tool_protocol

# System Lobe
from wren.system import permissions
from wren.system import reflect
from wren.system import steward_stores
from wren.system import steward_status

# Senses Lobe
from wren.senses import pictures as pictures_mod

# Environment/Rooms
from wren import rooms 

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
OWNER_SUB = os.environ.get("WREN_OWNER_SUB", "")
DEVICE_TOKEN = os.environ.get("WREN_DEVICE_TOKEN", "").strip()
from config import DEFAULT_ENGINE

ENGINE = os.environ.get("WREN_ENGINE") or DEFAULT_ENGINE
STORE_DIR = os.environ.get("WREN_STORE_DIR", "")
IDLE_BEFORE_REFLECTING = 120       

# Move LOG_DIR and _log_path up so they are available to all routes
LOG_DIR = os.environ.get("WREN_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))

def _log_path(name):
    return os.path.join(LOG_DIR, name)

def bind_stores():
    if not STORE_DIR:
        return                                  
    convo_store.store_path = lambda: os.path.join(STORE_DIR, convo_store.STORE_FILENAME)
    memory_store.store_path = lambda: os.path.join(STORE_DIR, memory_store.STORE_FILENAME)
    calendar_store.store_path = lambda: os.path.join(STORE_DIR, calendar_store.STORE_FILENAME)
    tool_protocol.store_path = lambda: os.path.join(STORE_DIR, tool_protocol.STORE_FILENAME)

_LAST_CHAT_AT = 0.0

def preflight():
    """Everything that must be true before this process is allowed to serve."""
    problems = []

    if not os.environ.get("GUARDIAN_ENCRYPTION_KEY", "").strip():
        problems.append("GUARDIAN_ENCRYPTION_KEY is not set")

    from config import OPENAI_MODEL_MAP as _openai_engines
    voice_key = "OPENAI_API_KEY" if ENGINE in _openai_engines else "ANTHROPIC_API_KEY"
    if not os.environ.get(voice_key, "").strip():
        problems.append("%s is not set -- Wren has no voice" % voice_key)

    if not SUPABASE_URL:
        problems.append("SUPABASE_URL is not set")

    if not OWNER_SUB:
        problems.append("WREN_OWNER_SUB is not set")

    if STORE_DIR and not os.path.isdir(STORE_DIR):
        problems.append("WREN_STORE_DIR=%s does not exist" % STORE_DIR)

    if steward_stores.test_default_active():
        problems.append("a test-only default steward is installed")

    for name, state in steward_stores.key_status().items():
        if name != "wren" and state != "ok":
            print("[wren] WARNING: %s's store is unavailable — %s" % (name, state))

    if problems:
        print("[wren] refusing to start:")
        for p in problems:
            print("  - %s" % p)
        sys.exit(1)

    print("[wren] soul %s, store at %s"
          % (wren_soul.version(), convo_store.store_path()))

# ── the door ─────────────────────────────────────────────────────────────────

_jwks = None

def _jwk_client():
    global _jwks
    if _jwks is None:
        from jwt import PyJWKClient
        _jwks = PyJWKClient(SUPABASE_URL + "/auth/v1/.well-known/jwks.json")
    return _jwks

def caller_context(refresh=False):
    cached = getattr(g, "wren_caller", None)
    if cached is not None and not refresh:
        return cached

    import hmac
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()

    if DEVICE_TOKEN and hmac.compare_digest(token, DEVICE_TOKEN):
        g.wren_caller = {"owner": OWNER_SUB, "auth_kind": "device"}
        return g.wren_caller
    try:
        import jwt
        key = _jwk_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["ES256", "RS256"],
                            audience="authenticated")
    except Exception:
        return None
    if claims.get("sub") != OWNER_SUB:
        return None
    g.wren_caller = {"owner": OWNER_SUB, "auth_kind": "owner"}
    return g.wren_caller

def _refresh_tool_principal(expected):
    current = caller_context(refresh=True)
    if not current or current != expected:
        raise tool_protocol.ProtocolError("desktop-identity-stale", 403)
    return current

def caller():
    context = caller_context()
    return context.get("owner") if context else None

def guarded(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*a, **kw):
        if not caller():
            return jsonify({"error": "Not signed in.", "status": 401}), 401
        return fn(*a, **kw)
    return wrapper

def desktop_tool_guarded(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        context = caller_context()
        if not context:
            return jsonify({"error": "Not signed in.", "status": 401}), 401
        return fn(*args, **kwargs)
    return wrapper

def one_store_read_per_request(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with convo_store.turn_snapshot(), gateway.SummaryGate() as gate:
            try:
                response = app.make_response(fn(*args, **kwargs))
            except BaseException:
                gate.release()
                raise
        response.call_on_close(gate.release)
        return response
    return wrapper

# ── routes ───────────────────────────────────────────────────────────────────

ALLOWED_ORIGINS = {
    "http://127.0.0.1:5001",
    "http://localhost:5001",
    "https://wren-3r7.pages.dev",
    "file://",
    "null",
}

@app.after_request
def allow_her_bodies(response):
    origin = request.headers.get("Origin", "")
    with open(_log_path("cors.log"), "a") as f:
        f.write(f"Origin: {origin}  {time.strftime('%H:%M:%S')} {request.remote_addr} "
                f"{request.method} {request.path} -> {response.status_code}\n")
    if origin in ALLOWED_ORIGINS or origin.startswith("file://") or origin.startswith("app://"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = (
            "authorization, content-type, x-wren-desktop-signature")
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, PATCH, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response

@app.route("/test-cors")
def test_cors():
    return "ok"

@app.route("/api/<path:_rest>", methods=["OPTIONS"])
def cors_preflight(_rest):
    return ("", 204)

@app.route("/health")
def health():
    with open(_log_path("health.log"), "a") as f: f.write("Hit health\n")
    try:
        signed_in = caller_context() is not None
    except Exception:
        signed_in = False
    return jsonify({"ok": True, "soul": wren_soul.version(),
                    "stewards": steward_status.health_view(signed_in)})

# ── her presence ─────────────────────────────────────────────────────────────

COMPANION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             os.pardir, "companion")
COMPANION_FILES = {
    "manifest.webmanifest", "sw.js", "caveat.woff2",
    "icon-192.png", "icon-512.png", "icon-maskable-512.png",
}
COMPANION_NO_CACHE = {"index.html", "sw.js", "manifest.webmanifest"}

def _companion(filename):
    from flask import send_from_directory
    response = send_from_directory(COMPANION_DIR, filename)
    if filename.endswith(".woff2"):
        response.headers["Content-Type"] = "font/woff2"
    if filename in COMPANION_NO_CACHE:
        response.headers["Cache-Control"] = "no-cache"
    return response

@app.route("/")
def presence():
    return _companion("index.html")

@app.route("/<path:asset>")
def companion_asset(asset):
    print("COMPANION ASSET HIT: " + asset, flush=True)
    if asset in COMPANION_FILES:
        return _companion(asset)
    return ("", 404)

# ── her eyes on the web ──────────────────────────────────────────────────────

WEB_DECIDER_ENGINE = "GPT-5.6 Wren (OpenAI)"      
WEB_DECIDER_PROMPT = (
    "You route web lookups for an assistant in mid-conversation. Look at the "
    "user's latest message. If answering it well needs CURRENT web content, "
    "reply with ONLY a JSON object: "
    '{"urls": ["https://..."]} or '
    '{"query": "search terms"}. '
    "If no web content is needed, reply with exactly {}. "
    "No prose, no markdown -- JSON only."
)

WEB_CAPABILITY_CONTEXT = (
    "Runtime capability: you can search the live public web and read current "
    "pages through Wren's server-side web pre-pass."
)
_WEB_CAPABILITY_QUESTION = re.compile(
    r"^\s*(?:(?:can|could)\s+(?:you|ya)\s+(search|browse|access|use)\s+"
    r"(?:the\s+)?(?:live\s+)?(?:web|internet|online)(?:\s+access)?|"
    r"do\s+you\s+have\s+(?:live\s+)?(?:web|internet)\s+access|"
    r"are\s+you\s+able\s+to\s+(?:search|browse)\s+the\s+)?\s*$", re.IGNORECASE)

def _strip_html(html):
    import re
    txt = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = re.sub(r"&[a-zA-Z#0-9]+;", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()

def _fetch_page(url):
    import requests as rq
    if not url.startswith(("http://", "https://")):
        return None
    try:
        r = rq.get(url, timeout=12, allow_redirects=True,
                   headers={"User-Agent": "Mozilla/5.0 (compatible; Wren/1.0)"})
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or not ("html" in ctype or "text" in ctype or "json" in ctype):
            return None
        return _strip_html(r.text)[:8000]
    except Exception:
        return None

def _search_links(query):
    import re
    import requests as rq
    from urllib.parse import unquote, urlparse, parse_qs
    try:
        r = rq.get("https://html.duckduckgo.com/html/", params={"q": query},
                   timeout=12,
                   headers={"User-Agent": "Mozilla/5.0 (compatible; Wren/1.0)"})
        if r.status_code != 200:
            return []
        links = []
        for href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', r.text):
            if "uddg=" in href:
                q = parse_qs(urlparse(href).query)
                real = unquote((q.get("uddg") or [""])[0])
            else:
                real = href
            if real.startswith("http"):
                links.append(real)
            if len(links) >= 6:
                break
        return links
    except Exception:
        return []

def _speaking_companion(room, speaker):
    try:
        return gateway.resolve_speaker(room, speaker)
    except Exception:
        return ""

def _web_context_for(messages, room, speaker):
    from wren.senses import web_gate
    if not web_gate.allowed_for(_speaking_companion(room, speaker)):
        return ""
    return _web_context(messages)

def _mail_context_for(messages, room, speaker, conversation, steward):
    from wren.system import mail_gate
    from wren.senses import mail_prepass as _mail
    if not mail_gate.allowed_for(_speaking_companion(room, speaker)):
        return ""
    return _mail.mail_context(messages, history=_recent_turns(conversation, steward))

def _web_context(messages):
    import json as _json
    from wren.core import provider

    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
            last = str(c or "")
            break
    if not last.strip():
        return ""
    if _WEB_CAPABILITY_QUESTION.fullmatch(last):
        return WEB_CAPABILITY_CONTEXT

    from wren.senses import web_gate
    if web_gate.prefilter_on() and not web_gate.looks_like_web(last):
        return ""

    try:
        probe = [{"role": "system", "content": WEB_DECIDER_PROMPT},
                 {"role": "user", "content": last[:2000]}]
        r = provider.complete(None, WEB_DECIDER_ENGINE, probe, timeout=20)
        if not r.get("ok"):
            return ""
        raw = (r.get("content") or "").strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        want = _json.loads(raw) if raw else {}
    except Exception:
        return ""

    explicit_urls = [u for u in (want.get("urls") or [])
                     if isinstance(u, str)][:2]
    candidates = explicit_urls
    if not candidates and want.get("query"):
        candidates = _search_links(str(want["query"])[:200])
    if not candidates:
        return ""

    pieces = []
    for u in candidates:
        text = _fetch_page(u)
        if text:
            pieces.append("From %s :\n%s" % (u, text))
        if len(pieces) >= 2:
            break
    if not pieces:
        return ""
    return ("Web content fetched moments ago for this turn. Use it as "
            "current, cite the page naturally when it matters:\n\n"
            + "\n\n----\n\n".join(pieces))

def _recent_turns(conversation, steward):
    if not conversation or steward is None:
        return ""
    try:
        with steward_stores.steward_scope(steward):
            conv = convo_store.full(conversation) or {}
        lines = []
        for t in (conv.get("turns") or [])[-6:]:
            c = t.get("content")
            if isinstance(c, list):
                c = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
            lines.append("%s: %s" % (t.get("role", "?"), str(c or "")[:300]))
        return "\n".join(lines)
    except Exception:
        return ""

@app.route("/api/wren/chat", methods=["POST"])
@guarded
@one_store_read_per_request
def chat():
    global _LAST_CHAT_AT
    _LAST_CHAT_AT = time.time()

    body = request.get_json(silent=True) or {}
    messages = body.get("messages") or []
    room = body.get("room") or "general"
    conversation = body.get("conversation")
    engine = body.get("engine") or ENGINE
    speaker = body.get("speaker")
    machine = str(body.get("machine") or "").strip().replace("\r", " ").replace("\n", " ")[:80] or None
    raw_client_turn_id = body.get("client_turn_id")
    client_turn_id = None
    if raw_client_turn_id is not None:
        candidate_turn_id = str(raw_client_turn_id).strip()
        if candidate_turn_id:
            if not tool_protocol._ID.fullmatch(candidate_turn_id):
                return jsonify({"ok": False, "error": "malformed-client-turn-id",
                                "status": 400}), 400
            client_turn_id = candidate_turn_id

    try:
        steward = gateway._store_steward(room, speaker)
    except (ValueError, steward_stores.StewardStoreError) as e:
        return jsonify(gateway._store_refusal(e))

    project = str(body.get("project") or "").strip()
    if not conversation and project:
        with steward_stores.steward_scope(steward):
            conversation = convo_store.create(project)

    from wren.senses import mail_prepass as _mail
    extra = "\n\n".join(p for p in (
        body.get("extra_context"),
        _web_context_for(messages, room, speaker),
        _mail_context_for(messages, room, speaker, conversation, steward)) if p)

    from wren.tools import kernel_tools
    active_schemas = kernel_tools.active_local_schemas(room=room, speaker=steward)

    if not body.get("stream"):
        return jsonify(gateway.chat(None, room, engine, messages,
                                    extra_context=extra,
                                    conversation=conversation,
                                    speaker=speaker,
                                    client_turn_id=client_turn_id,
                                    tools=active_schemas,
                                    machine=machine))

    import json as _json
    def frames():
        for event in gateway.chat_stream(None, room, engine, messages,
                                         extra_context=extra,
                                         conversation=conversation,
                                         speaker=speaker,
                                         client_turn_id=client_turn_id,
                                         tools=active_schemas,
                                         machine=machine):
            yield "data: " + _json.dumps(event) + "\n\n"

    return Response(frames(), mimetype="text/event-stream",
                    headers={"cache-control": "no-cache"})

def _tool_sse(events, status=200):
    import json as _json
    def frames():
        for event in events:
            yield "data: " + _json.dumps(event, ensure_ascii=False) + "\n\n"
    return Response(frames(), status=status, mimetype="text/event-stream",
                    headers={"cache-control": "no-cache"})

def _tool_error(reason, status=400, assistant_turn_id=None, message=None):
    event = {"type": "error", "error": str(reason), "status": int(status)}
    if message:
        event["message"] = str(message)
    if assistant_turn_id:
        event["assistant_turn_id"] = assistant_turn_id
    return _tool_sse([event], status=status)

def _picture_refusal(body, error):
    clean = lambda v: re.sub(r"[^a-z0-9 ._()+-]", "", str(v or "").lower())[:40]
    gateway._record_context_counts(
        "pictures_refused", clean((body or {}).get("speaker")), clean((body or {}).get("engine")),
        {"pictures": error.pictures, "bytes": error.size}, reason=error.code)
    return _tool_error(error.code, error.status, message=error.message)

def _audit_tool_refusal(principal, envelope, error):
    reason = str(getattr(error, "reason", "tool-authority-refused"))
    if reason == "desktop-session-expired":
        event = "session_expiration"
    elif reason == "workspace-binding-mismatch":
        event = "workspace_mismatch"
    elif reason == "desktop-document-stale":
        event = "document_mismatch"
    elif reason == "desktop-authority-generation-stale":
        event = "stale_authority"
    elif reason in ("execution-grant-replay", "execution-grant-invalid"):
        event = "execution_grant_replay"
    elif reason == "tool-turn-canceled":
        event = "cancellation"
    else:
        event = "authority_refusal"
    try:
        tool_protocol.record_security_refusal(
            principal.get("owner", ""), principal.get("auth_kind", ""),
            event, reason, envelope)
    except Exception:
        pass

def _derive_trusted_turn_speaker(principal, verified_room, conversation, body):
    if not isinstance(principal, dict):
        return ""
    owner = str(principal.get("owner") or "").strip()
    auth_kind = str(principal.get("auth_kind") or "").strip()
    if not owner or owner != OWNER_SUB or auth_kind not in ("device", "owner"):
        return ""

    norm_room = str(verified_room or "").strip().lower()
    if norm_room not in permissions.ROOMS:
        return ""
    room_steward = str(rooms.get_room(norm_room).get("steward") or "").strip().lower()
    if room_steward != "wren":
        return room_steward

    if conversation:
        try:
            with steward_stores.steward_scope("wren"):
                conv_rec = convo_store.get(str(conversation)) or {}
            established = str(conv_rec.get("speaker") or "").strip().lower()
            if established and established not in ("wren", "chrissy"):
                return established
        except Exception:
            pass

    if isinstance(body, dict) and "speaker" in body:
        raw_speaker = body.get("speaker")
        if raw_speaker is None or not isinstance(raw_speaker, str):
            return ""
        candidate = raw_speaker.strip().lower()
        if not candidate:
            return ""
        if candidate not in ("wren", "chrissy"):
            return candidate
        return candidate

    return room_steward

def _context_error_status(reason):
    if reason in (
        "desktop-identity-stale",
        "speaker-tool-capability-denied",
        "room-tool-capability-denied",
        "identity-in-model-arguments-forbidden",
        "capability-override-forbidden",
        "state-mutation-forbidden",
        "untrusted-invocation-context",
        "desktop-authority-binding-mismatch",
    ):
        return 403
    if reason in (
        "desktop-conversation-binding-stale",
        "tool-turn-canceled",
        "tool-call-not-executable",
        "tool-call-binding-mismatch",
        "desktop-document-stale",
        "workspace-binding-mismatch",
        "desktop-authority-generation-stale",
        "tool-loop-limit",
    ):
        return 409
    if reason == "unknown-assistant-turn":
        return 404
    return 400

DONE_EVENT_FIELDS = ("conversation", "room", "engine", "kernel", "sources",
                     "evidence", "integrity_corrections", "omitted_vault", "context")

MIXED_STEP_ERROR = "mixed-step-call-tools-separately"

def _calls_are_well_formed(raw_calls):
    seen = set()
    for raw in raw_calls:
        if not isinstance(raw, dict) or raw.get("type") != "function" or not isinstance(raw.get("function"), dict):
            return False
        call_id = str(raw.get("id") or "")
        if not tool_protocol._ID.fullmatch(call_id) or call_id in seen:
            return False
        seen.add(call_id)
    return True

def _mixed_step_is_recoverable(raw_calls, in_kernel):
    known = in_kernel | tool_protocol.TOOL_NAMES | frozenset(tool_protocol.offer.WAVE1_TOOLS)
    return (_calls_are_well_formed(raw_calls)
            and all(str(raw["function"].get("name") or "") in known for raw in raw_calls))

def _resolve_sanctuary_tool_calls(principal, desktop_session_id,
                                  assistant_turn_id, outcome,
                                  trusted_speaker, start_round=0):
    import json as _json
    in_kernel = sanctuary_adapter.SANCTUARY_TOOL_NAMES | memory_tools.TOOL_NAMES

    round_idx = int(start_round)
    while outcome.get("ok") and outcome.get("kind") == "tool_calls":
        raw_calls = outcome.get("tool_calls") or []
        if not raw_calls:
            break
        call_names = [
            str((c.get("function") if isinstance(c.get("function"), dict) else {}).get("name") or "")
            for c in raw_calls if isinstance(c, dict)
        ]
        if not call_names or not any(name in in_kernel for name in call_names):
            break
        if not _calls_are_well_formed(raw_calls):
            raise tool_protocol.ProtocolError("malformed-tool-call", 502)
        mixed = not all(name in in_kernel for name in call_names)
        if mixed and not _mixed_step_is_recoverable(raw_calls, in_kernel):
            raise tool_protocol.ProtocolError("malformed-tool-call", 502)
        if round_idx >= tool_protocol.MAX_TOOL_STEPS:
            raise tool_protocol.ProtocolError("tool-loop-limit", 409)

        principal = _refresh_tool_principal(principal)
        state = outcome["provider_state"]
        comp = state.get("comp") or {}
        conversation_id = str(comp.get("conv_id") or "")

        try:
            invocation_ctx = sanctuary_adapter.build_trusted_invocation_context(
                principal=principal,
                expected_owner_sub=OWNER_SUB,
                assistant_turn_id=assistant_turn_id,
                desktop_session_id=desktop_session_id,
                resolved_speaker=trusted_speaker,
                round_index=round_idx,
                conversation_override=conversation_id,
            )
        except sanctuary_adapter.TrustedContextError as exc:
            raise tool_protocol.ProtocolError(
                exc.reason, _context_error_status(exc.reason)
            ) from exc

        seen_ids = set()
        sanctuary_results = []
        for raw in raw_calls:
            if not isinstance(raw, dict) or raw.get("type") != "function":
                raise tool_protocol.ProtocolError("malformed-tool-call", 502)
            call_id = str(raw.get("id") or "")
            fn = raw.get("function")
            # FIXED SYNTAX ERROR HERE
            if (not tool_protocol._ID.fullmatch(call_id)
                    or call_id in seen_ids
                    or not isinstance(fn, dict)):
                raise tool_protocol.ProtocolError("malformed-tool-call", 502)
            seen_ids.add(call_id)
            tool_name = str(fn.get("name") or "")
            if mixed:
                now = tool_protocol._now()
                result = sanctuary_adapter._format_protocol_tool_result(
                    status="denied", started_at=now, finished_at=now, error=MIXED_STEP_ERROR)
                sanctuary_adapter._record_actor_audit(invocation_ctx, call_id, tool_name, result)
                sanctuary_results.append({
                    "tool_call_id": call_id,
                    "result": tool_protocol.validate_result(result, tool_name=tool_name),
                })
                continue
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    parsed_args = _json.loads(raw_args) if raw_args.strip() else {}
                except ValueError:
                    parsed_args = None
            elif isinstance(raw_args, dict):
                parsed_args = dict(raw_args)
            elif raw_args is None:
                parsed_args = {}
            else:
                parsed_args = None

            if tool_name in memory_tools.TOOL_NAMES:
                result = memory_tools.execute_tool_call(
                    speaker=invocation_ctx.speaker,
                    room=invocation_ctx.actual_room or invocation_ctx.room,
                    engine=state.get("engine"),
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    tool_arguments=parsed_args,
                )
                sanctuary_adapter._record_actor_audit(invocation_ctx, call_id, tool_name, result)
            else:
                result = sanctuary_adapter.execute_sanctuary_tool_call(
                    invocation_context=invocation_ctx,
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    tool_arguments=parsed_args,
                )
            validated_result = tool_protocol.validate_result(result, tool_name=tool_name)
            sanctuary_results.append({
                "tool_call_id": call_id,
                "result": validated_result,
            })

        active_schemas = tool_protocol.active_tool_schemas(
            room=invocation_ctx.room,
            speaker=invocation_ctx.speaker,
        )
        outcome = gateway.continue_desktop_tool_turn(
            state, active_schemas, sanctuary_results
        )
        round_idx += 1

    return principal, outcome

@app.route("/api/wren/tool-turn", methods=["POST"])
@desktop_tool_guarded
@one_store_read_per_request
def desktop_tool_turn():
    global _LAST_CHAT_AT
    _LAST_CHAT_AT = time.time()
    if request.content_length is not None and request.content_length > pictures_mod.max_request_bytes():
        return _picture_refusal({}, pictures_mod.PictureError(
            "request-too-large", pictures_mod.message_for("request-too-large"), status=413, size=request.content_length))
    body = request.get_json(silent=True) or {}
    principal = caller_context()
    try:
        verified_session = tool_protocol.verify_session_request(
            principal["owner"], principal["auth_kind"], body,
            request.headers.get("X-Wren-Desktop-Signature", ""))
        desktop_session_id = tool_protocol.validate_session(
            verified_session.get("desktop_session_id"))
    except tool_protocol.ProtocolError as e:
        _audit_tool_refusal(principal, body, e)
        return _tool_error(e.reason, e.status)
    if body.get("protocol") != tool_protocol.PROTOCOL_VERSION:
        return _tool_error("unsupported-tool-protocol", 400)
    messages = body.get("messages")
    if not (isinstance(messages, list) and len(messages) == 1
            and isinstance(messages[0], dict)
            and messages[0].get("role") == "user"
            and isinstance(messages[0].get("content"), (str, list))):
        return _tool_error("malformed-tool-turn", 400)

    images, picture_words = [], True
    if isinstance(messages[0].get("content"), list):
        try:
            words, images, _picture_bytes = pictures_mod.split_user_content(messages[0]["content"])
        except pictures_mod.PictureError as error:
            return _picture_refusal(body, error)
        if images:
            from config import OPENAI_MODEL_MAP
            if (OPENAI_MODEL_MAP.get(body.get("engine") or ENGINE) or {}).get("vision") is not True:
                return _picture_refusal(body, pictures_mod.PictureError(
                    "engine-cannot-see-pictures", pictures_mod.message_for("engine-cannot-see-pictures"), pictures=len(images)))
        picture_words = bool(words.strip())
        messages = [{"role": "user", "content": words if picture_words or not images else "[image]"}]

    requested_room = str(body.get("room") or "").strip().lower()
    if requested_room not in permissions.ROOMS:
        return _tool_error("unknown-tool-room", 403)
    if not all(permissions.can_use_tool(requested_room, name, permissions.TOOL_CAPS)
               for name in tool_protocol.TOOL_NAMES):
        return _tool_error("room-tool-capability-denied", 403)
    room = str(verified_session.get("room") or "").strip().lower()
    if requested_room != room:
        _audit_tool_refusal(
            principal, body,
            tool_protocol.ProtocolError("desktop-authority-binding-mismatch", 403))
        return _tool_error("desktop-authority-binding-mismatch", 403)
    conversation = body.get("conversation")
    engine = body.get("engine") or ENGINE
    speaker = body.get("speaker")
    machine = str(body.get("machine") or "").strip().replace("\r", " ").replace("\n", " ")[:80] or None
    trusted_speaker = _derive_trusted_turn_speaker(principal, room, conversation, body)
    try:
        steward, steward_refusal = gateway._store_steward(room, speaker), None
    except (ValueError, steward_stores.StewardStoreError) as e:
        steward, steward_refusal = None, gateway._store_refusal(e)
    client_turn_id = str(body.get("client_turn_id") or "")
    workspace_binding = str(body.get("workspace_binding") or "")
    project = str(body.get("project") or "").strip()

    digest_body = {k: v for k, v in body.items() if k != "desktop_session_id"}
    request_digest = hashlib.sha256(tool_protocol.canonical_bytes(digest_body)).hexdigest()
    try:
        reserved = tool_protocol.reserve_initial(
            principal["owner"], principal["auth_kind"], desktop_session_id,
            client_turn_id, workspace_binding, body.get("document_nonce"),
            body.get("authority_generation"),
            request_digest, conversation, room, speaker=trusted_speaker)
    except tool_protocol.ProtocolError as e:
        _audit_tool_refusal(principal, body, e)
        return _tool_error(e.reason, e.status)
    if not reserved["claimed"]:
        if reserved.get("events"):
            return _tool_sse(reserved["events"])
        active = int(reserved.get("lease_expires_at") or 0) >= int(time.time())
        return _tool_error("initial-turn-in-progress" if active
                           else "initial-turn-recovery-required", 409,
                           reserved.get("assistant_turn_id"))
    if not conversation and project:
        if steward_refusal:
            try:
                tool_protocol.fail_continuation(
                    principal["owner"], principal["auth_kind"],
                    reserved["assistant_turn_id"],
                    {"type": "error", "error": steward_refusal["reason"],
                     "status": steward_refusal["status"]})
            except tool_protocol.ProtocolError:
                pass
            return _tool_error(steward_refusal["reason"], steward_refusal["status"],
                               reserved["assistant_turn_id"])
        with steward_stores.steward_scope(steward):
            conversation = convo_store.create(project)

    from wren.senses import mail_prepass as _mail
    extra = "\n\n".join(p for p in (
        body.get("extra_context"),
        _web_context_for(messages, room, speaker),
        _mail_context_for(messages, room, speaker, conversation, steward)) if p)

    user_content = messages[0].get("content", "")
    if continuity.is_reanchor_request(user_content):
        reanchor_res = continuity.execute_reanchor(conversation_id=conversation)
        events = [
            {"type": "delta", "delta": reanchor_res["content"]},
            {"type": "done", "done": True, "conversation": conversation,
             "room": room, "engine": engine, "kernel": gateway.GATEWAY_VERSION,
             "sources": [], "evidence": [], "diagnostics": reanchor_res["diagnostics"]},
        ]
        saved = tool_protocol.finish_initial(
            principal["owner"], principal["auth_kind"],
            reserved["assistant_turn_id"], conversation,
            final_events=events)
        return _tool_sse(saved["events"])

    active_schemas = tool_protocol.active_tool_schemas(
        room=room, speaker=trusted_speaker)
    outcome = gateway.begin_desktop_tool_turn(
        None, room, engine, messages, active_schemas,
        extra_context=extra, conversation=conversation, speaker=speaker,
        client_turn_id=client_turn_id, machine=machine,
        **({"pictures": images, "picture_words": picture_words} if images else {}))
    if outcome.get("ok") and outcome.get("kind") == "tool_calls":
        try:
            principal, outcome = _resolve_sanctuary_tool_calls(
                principal, desktop_session_id,
                reserved["assistant_turn_id"], outcome,
                trusted_speaker=trusted_speaker, start_round=0)
        except tool_protocol.ProtocolError as e:
            try:
                tool_protocol.fail_continuation(
                    principal["owner"], principal["auth_kind"],
                    reserved["assistant_turn_id"],
                    {"type": "error", "error": e.reason, "status": e.status})
            except tool_protocol.ProtocolError:
                pass
            return _tool_error(e.reason, e.status, reserved["assistant_turn_id"])
    if not outcome.get("ok"):
        try:
            tool_protocol.fail_continuation(
                principal["owner"], principal["auth_kind"],
                reserved["assistant_turn_id"],
                {"type": "error", "error": outcome.get("reason", "upstream"),
                 "status": outcome.get("status", 502)})
        except tool_protocol.ProtocolError:
            pass
        return _tool_error(outcome.get("reason", "upstream"), outcome.get("status", 502))
    if outcome.get("kind") == "final":
        events = [
            {"type": "delta", "delta": outcome.get("content", "")},
            {"type": "done", "done": True,
             **{k: outcome[k] for k in
                DONE_EVENT_FIELDS
                if k in outcome}},
        ]
        try:
            saved = tool_protocol.finish_initial(
                principal["owner"], principal["auth_kind"],
                reserved["assistant_turn_id"], outcome.get("conversation") or conversation,
                final_events=events)
        except tool_protocol.ProtocolError as e:
            return _tool_error(e.reason, e.status, reserved["assistant_turn_id"])
        return _tool_sse(saved["events"])

    state = outcome["provider_state"]
    conversation_id = state["comp"].get("conv_id") or str(conversation or "")
    try:
        principal = _refresh_tool_principal(principal)
        registered = tool_protocol.finish_initial(
            principal["owner"], principal["auth_kind"],
            reserved["assistant_turn_id"], conversation_id,
            provider_state=state, raw_calls=outcome.get("tool_calls"))
    except tool_protocol.ProtocolError as e:
        try:
            tool_protocol.fail_continuation(
                principal["owner"], principal["auth_kind"],
                reserved["assistant_turn_id"],
                {"type": "error", "error": e.reason, "status": e.status})
        except tool_protocol.ProtocolError:
            pass
        return _tool_error(e.reason, e.status)
    return _tool_sse(registered["events"])

@app.route("/api/wren/tool-execution-grant", methods=["POST"])
@desktop_tool_guarded
def desktop_tool_execution_grant():
    body = request.get_json(silent=True) or {}
    principal = caller_context()
    try:
        tool_protocol.verify_session_request(
            principal["owner"], principal["auth_kind"], body,
            request.headers.get("X-Wren-Desktop-Signature", ""))
        grant = tool_protocol.issue_execution_grant(
            principal["owner"], principal["auth_kind"], body)
        return jsonify(grant)
    except tool_protocol.ProtocolError as e:
        _audit_tool_refusal(principal, body, e)
        return jsonify({"error": e.reason, "status": e.status}), e.status

@app.route("/api/wren/tool-result", methods=["POST"])
@desktop_tool_guarded
@one_store_read_per_request
def desktop_tool_result():
    envelope = request.get_json(silent=True) or {}
    principal = caller_context()
    assistant_turn_id = str(envelope.get("assistant_turn_id") or "")
    try:
        verified_session = tool_protocol.verify_session_request(
            principal["owner"], principal["auth_kind"], envelope,
            request.headers.get("X-Wren-Desktop-Signature", ""))
        recorded = tool_protocol.record_result(
            principal["owner"], principal["auth_kind"], envelope)
    except tool_protocol.ProtocolError as e:
        _audit_tool_refusal(principal, envelope, e)
        return _tool_error(e.reason, e.status, assistant_turn_id)

    if recorded["duplicate"] and not recorded["ready"]:
        events = recorded.get("events") or [{
            "type": "tool_result_ack", "duplicate": True,
            "assistant_turn_id": assistant_turn_id,
            "state": recorded.get("state"),
        }]
        return _tool_sse(events)
    if not recorded["ready"]:
        return _tool_sse([{
            "type": "tool_result_ack", "duplicate": False,
            "assistant_turn_id": assistant_turn_id,
            "state": recorded.get("state"),
        }])

    try:
        claimed = tool_protocol.claim_continuation(
            principal["owner"], principal["auth_kind"], assistant_turn_id,
            verified_session.get("desktop_session_id"),
            verified_session.get("workspace_binding"), envelope.get("document_nonce"))
    except tool_protocol.ProtocolError as e:
        return _tool_error(e.reason, e.status, assistant_turn_id)
    if not claimed["claimed"]:
        return _tool_sse(claimed.get("events") or [{
            "type": "tool_result_ack", "duplicate": True,
            "assistant_turn_id": assistant_turn_id,
            "state": claimed.get("state"),
        }])

    claimed_state = claimed["state"]
    claimed_comp = claimed_state.get("comp") or {}
    claimed_room = str(verified_session.get("room") or claimed_state.get("room") or "").strip().lower()
    claimed_speaker = _derive_trusted_turn_speaker(
        principal, claimed_room, claimed_comp.get("conv_id"),
        {"speaker": claimed_comp.get("speaker")} if "speaker" in claimed_comp else {})
    active_schemas = tool_protocol.active_tool_schemas(
        room=claimed_room, speaker=claimed_speaker)
    outcome = gateway.continue_desktop_tool_turn(
        claimed["state"], active_schemas, claimed["results"])
    if outcome.get("ok") and outcome.get("kind") == "tool_calls":
        try:
            principal, outcome = _resolve_sanctuary_tool_calls(
                principal, verified_session.get("desktop_session_id"),
                assistant_turn_id, outcome,
                trusted_speaker=claimed_speaker, start_round=1)
        except tool_protocol.ProtocolError as e:
            event = {"type": "error", "error": e.reason, "status": e.status,
                     "assistant_turn_id": assistant_turn_id}
            try:
                tool_protocol.fail_continuation(
                    principal["owner"], principal["auth_kind"],
                    assistant_turn_id, event)
            except tool_protocol.ProtocolError:
                pass
            return _tool_error(e.reason, e.status, assistant_turn_id)
    if not outcome.get("ok"):
        event = {"type": "error", "error": outcome.get("reason", "upstream"),
                 "status": outcome.get("status", 502),
                 "assistant_turn_id": assistant_turn_id}
        try:
            tool_protocol.fail_continuation(
                principal["owner"], principal["auth_kind"],
                assistant_turn_id, event)
        except tool_protocol.ProtocolError:
            pass
        return _tool_sse(event, status=event["status"])

    try:
        if outcome.get("kind") == "tool_calls":
            principal = _refresh_tool_principal(principal)
            saved = tool_protocol.save_continuation(
                principal["owner"], principal["auth_kind"], assistant_turn_id,
                outcome["provider_state"], raw_calls=outcome.get("tool_calls"))
        else:
            events = [
                {"type": "delta", "delta": outcome.get("content", ""),
                 "assistant_turn_id": assistant_turn_id},
                {"type": "done", "done": True,
                 **{k: outcome[k] for k in
                    DONE_EVENT_FIELDS
                    if k in outcome}},
            ]
            saved = tool_protocol.save_continuation(
                principal["owner"], principal["auth_kind"], assistant_turn_id,
                None, final_events=events)
    except tool_protocol.ProtocolError as e:
        event = {"type": "error", "error": e.reason, "status": e.status,
                 "assistant_turn_id": assistant_turn_id}
        try:
            tool_protocol.fail_continuation(
                principal["owner"], principal["auth_kind"],
                assistant_turn_id, event)
        except tool_protocol.ProtocolError:
            pass
        return _tool_sse(event, status=e.status)
    return _tool_sse(saved["events"])

@app.route("/api/wren/tool-recover", methods=["POST"])
@desktop_tool_guarded
def desktop_tool_recover():
    body = request.get_json(silent=True) or {}
    principal = caller_context()
    try:
        verified_session = tool_protocol.verify_session_request(
            principal["owner"], principal["auth_kind"], body,
            request.headers.get("X-Wren-Desktop-Signature", ""))
        recovered = tool_protocol.recover(
            principal["owner"], principal["auth_kind"],
            body.get("desktop_session_id"), body.get("client_turn_id"),
            body.get("workspace_binding"), body.get("document_nonce"))
        return _tool_sse(recovered["events"])
    except tool_protocol.ProtocolError as e:
        _audit_tool_refusal(principal, body, e)
        return _tool_error(e.reason, e.status)

@app.route("/api/wren/tool-cancel", methods=["POST"])
@desktop_tool_guarded
def desktop_tool_cancel():
    body = request.get_json(silent=True) or {}
    if not (isinstance(body, dict) and set(body) == {
            "protocol", "desktop_session_id", "workspace_binding",
            "document_nonce", "authority_generation", "client_turn_id"}
            or body.get("protocol") != tool_protocol.PROTOCOL_VERSION):
        return _tool_error("malformed-tool-cancel", 400)
    principal = caller_context()
    try:
        verified_session = tool_protocol.verify_session_request(
            principal["owner"], principal["auth_kind"], body,
            request.headers.get("X-Wren-Desktop-Signature", ""))
        canceled = tool_protocol.cancel_turn(
            principal["owner"], principal["auth_kind"],
            body.get("desktop_session_id"), body.get("client_turn_id"),
            body.get("workspace_binding"), body.get("document_nonce"),
            body.get("authority_generation"))
        return jsonify(canceled)
    except tool_protocol.ProtocolError as e:
        _audit_tool_refusal(principal, body, e)
        return _tool_error(e.reason, e.status)

@app.route("/api/wren/voice", methods=["POST"])
@guarded
def voice():
    import requests as rq
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "nothing to say"}), 400
    r = rq.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "")},
        json={
            "model": "gpt-4o-mini-tts",
            "voice": os.environ.get("WREN_VOICE", "marin"),
            "input": text[:4000],
            "instructions": "Talk like a real person chatting comfortably. Casual, warm, low-key.",
            "response_format": "mp3",
        },
        timeout=60,
    )
    if r.status_code != 200:
        return jsonify({"error": "voice failed"}), 502
    return Response(r.content, mimetype="audio/mpeg")

@app.route("/api/wren/hear", methods=["POST"])
@guarded
def hear():
    import requests as rq
    audio = request.get_data()
    if not audio or len(audio) > 15 * 1024 * 1024:
        return jsonify({"error": "no audio"}), 400
    r = rq.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "")},
        files={"file": ("turn.m4a", audio, "audio/mp4")},
        data={"model": "gpt-4o-mini-transcribe"},
        timeout=60,
    )
    if r.status_code != 200:
        return jsonify({"error": "could not hear"}), 502
    return jsonify({"text": (r.json().get("text") or "").strip()})

PANEL_DEFAULT_STEWARD = "wren"

def panel_scope(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        raw = request.args.get("steward") or request.headers.get("X-Wren-Steward")
        defaulted = raw is None or not str(raw).strip()
        try:
            steward = PANEL_DEFAULT_STEWARD if defaulted else steward_stores.normalize(raw)
            steward_stores.require_openable(steward)
        except steward_stores.UnknownStewardStore as e:
            return jsonify({"error": "unknown-steward", "detail": str(e), "status": 400}), 400
        except steward_stores.StewardStoreError as e:
            return jsonify({"error": "steward-unavailable", "detail": str(e), "status": 503}), 503
        g.steward, g.steward_defaulted = steward, defaulted
        with steward_stores.steward_scope(steward):
            response = make_response(view(*a, **kw))
        response.headers["X-Wren-Steward"] = steward
        response.headers["X-Wren-Steward-Defaulted"] = "1" if defaulted else "0"
        return response
    return wrapped

@app.route("/api/wren/conversations", methods=["GET"])
@guarded
@panel_scope
def list_conversations():
    archived = str(request.args.get("archived") or "").lower() in ("1", "true", "yes")
    return jsonify({"conversations": convo_store.list_conversations(archived=archived),
                    "steward": g.steward, "steward_defaulted": g.steward_defaulted})

@app.route("/api/wren/conversations/<cid>", methods=["GET", "PATCH", "DELETE"])
@guarded
@panel_scope
def one_conversation(cid):
    if request.method == "DELETE":
        if not convo_store.delete(cid):
            return jsonify({"error": "No such conversation.", "status": 404}), 404
        return jsonify({"ok": True, "deleted": cid})
    if request.method == "PATCH":
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip().lower()
        if action == "rename":
            conv = convo_store.rename(cid, body.get("title"))
        elif action == "archive":
            conv = convo_store.set_archived(cid, True)
        elif action == "restore":
            conv = convo_store.set_archived(cid, False)
        else:
            return jsonify({"error": "invalid action", "status": 400}), 400
        if not conv:
            return jsonify({"error": "No such conversation.", "status": 404}), 404
        return jsonify({"ok": True, "id": cid, "title": conv.get("title", ""),
                        "archived": bool(conv.get("archived"))})
    conv = convo_store.full(cid)
    if not conv:
        return jsonify({"error": "No such conversation.", "status": 404}), 404
    return jsonify(conv)

@app.route("/api/calendar", methods=["GET"])
@guarded
def calendar_list():
    return jsonify({"records": calendar_store.list_records()})

@app.route("/api/calendar/<rid>", methods=["GET"])
@guarded
def calendar_one(rid):
    rec = calendar_store.get(rid)
    if not rec:
        return jsonify({"error": "No such record.", "status": 404}), 404
    return jsonify(rec)

@app.route("/api/calendar", methods=["POST"])
@guarded
def calendar_put():
    body = request.get_json(silent=True) or {}
    try:
        status, record = calendar_store.apply(
            body,
            expected_rev=body.get("expected_rev"),
            op_id=body.get("op_id"))
    except calendar_store.Refused as why:
        return jsonify({"error": str(why), "status": 400}), 400
    if status == "conflict":
        return jsonify({"error": "Revision conflict.", "status": 409,
                        "current": record}), 409
    return jsonify({"status": status, "record": record})

@app.route("/api/memory", methods=["GET"])
@guarded
@panel_scope
def memory():
    return jsonify({
        "records": memory_store.all_records(include_deleted=False),
        "candidates": memory_store.candidates("pending"),
        "steward": g.steward, "steward_defaulted": g.steward_defaulted,
    })

@app.route("/api/memory", methods=["POST"])
@guarded
@panel_scope
def add_memory_route():
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    mem_type = body.get("type", "personal")
    scope = body.get("scope", "global")
    source = body.get("source", "conversation")
    kind = body.get("kind", "fact")
    confidence = body.get("confidence", "stated")
    vault = bool(body.get("vault", False))
    why = body.get("why")
    guardrail = body.get("guardrail")

    if not text or not str(text).strip():
        return jsonify({"error": "Empty memory", "status": 400}), 400

    rec, errors = memory_store.add(
        text=str(text).strip(),
        type=mem_type,
        scope=scope,
        source=source or "conversation",
        confidence=confidence,
        kind=kind,
        vault=vault,
        why=why,
        guardrail=guardrail,
    )
    if errors:
        return jsonify({"error": errors, "status": 400}), 400
    return jsonify({"status": "ok", "record": rec}), 201

def _review_one(steward, quiet_minutes):
    try:
        from wren.system import summarize
        for s in summarize.run_due(engine=ENGINE):
            if s.get("error"):
                print("[wren] summary (%s): %s" % (steward, s["error"]))
    except Exception as e:
        print("[wren] summary pass failed for %s (%s)" % (steward, e))
    try:
        if time.time() - _LAST_CHAT_AT >= IDLE_BEFORE_REFLECTING:
            began = time.time()
            runs = reflect.reflect_due(
                quiet_minutes=quiet_minutes,
                engine=ENGINE,
                should_stop=lambda: _LAST_CHAT_AT > began)
            for r in runs:
                if r.get("error"):
                    print("[wren] reflection (%s): %s" % (steward, r["error"]))
    except Exception as e:
        print("[wren] reflection pass failed for %s (%s)" % (steward, e))

def review_all_stewards(quiet_minutes):
    done = []
    for steward in steward_stores.STORE_STEWARDS:
        try:
            steward_stores.require_openable(steward)
        except steward_stores.StewardStoreError as e:
            continue
        with steward_stores.steward_scope(steward):
            _review_one(steward, quiet_minutes)
        done.append(steward)
    return done

def start_reflection():
    from config import REFLECT_QUIET_MINUTES
    if os.environ.get("WREN_BACKGROUND_MODEL_CALLS", "") != "1":
        print("[wren] reflection DISABLED (cost freeze)")
        return

    def loop():
        time.sleep(60)
        while True:
            interval = max(REFLECT_QUIET_MINUTES, 1) * 15
            review_all_stewards(REFLECT_QUIET_MINUTES)
            time.sleep(max(interval, 60))

    threading.Thread(target=loop, name="wren-reflection", daemon=True).start()

def start_backup():
    if not os.environ.get("R2_ACCESS_KEY_ID", "").strip():
        return

    here = os.path.dirname(os.path.abspath(__file__))
    def loop():
        while True:
            time.sleep(3600 - (time.time() % 3600) + 5)
            try:
                subprocess.run([sys.executable, os.path.join(here, "backup.py")],
                               capture_output=True, text=True, timeout=600)
            except Exception as e:
                print("[wren] backup failed: %s" % e)

    threading.Thread(target=loop, name="wren-backup", daemon=True).start()

def start_tool_protocol_janitor():
    def loop():
        while True:
            time.sleep(60)
            try:
                tool_protocol.expire_records()
            except Exception as error:
                print("[wren] tool protocol expiry failed")
    threading.Thread(target=loop, name="wren-tool-expiry", daemon=True).start()

if __name__ == "__main__":
    bind_stores()
    preflight()
    start_reflection()
    start_backup()
    start_tool_protocol_janitor()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
