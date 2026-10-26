# ============================================================
# WREN KERNEL — model-provider abstraction + THE VAULT WALL
# ------------------------------------------------------------
# Port of vale/core/provider.js, carrying Fortress's constitutional
# privacy rule (docs/intelligence/01, Article II): vault scopes are
# LOCAL-MODEL-ONLY. The wall lives here, beneath every prompt — a
# jailbroken voicebox still cannot route vault material to a cloud,
# because the transport refuses.
#
# One method: complete(scope, engine, messages, tools=None) →
#   { ok: True, content, tool_calls, raw } |
#   { ok: False, reason, status }
# reason ∈ auth | rate-limited | no-credits | upstream |
#          invalid-output | vault-wall | unknown-engine | error |
#          eval-config (an eval-only reasoning setting outside the
#          isolated eval server, or outside the allowlist — refused
#          loudly, never sent, never silently defaulted)
#
# Transport is injectable (set _post for tests) — no test ever
# touches the network.
# ============================================================

import json
import re
import requests as _requests_mod

# FIX: Absolute import to resolve Lobe Misalignment
from wren.system import credfilter

from config import (
    OPENAI_MODEL_MAP, CLOUD_MODEL_MAP, GROQ_MODEL_MAP, MODEL_MAP,
    OPENAI_API_KEY, OPENROUTER_KEY, GROQ_KEY, OLLAMA_URL,
    VAULT_APPROVED_ENGINES,
)
import os as _os

ANTHROPIC_API_KEY = _os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

ANTHROPIC_MODEL_MAP = {
    "Claude Sonnet (Anthropic direct)": {"model": "claude-sonnet-5", "vibe": "The Partner"},
    "Claude Haiku (Anthropic direct)":  {"model": "claude-haiku-4-5-20251001", "vibe": "The Sprinter"},
}

VAULT_SCOPES = ("core", "aura_prompt", "aura_synthesis")

def is_vault_scope(scope):
    return str(scope or "") in VAULT_SCOPES

def is_local_engine(engine):
    spec = MODEL_MAP.get(engine)
    model = str(spec.get("model", "")) if spec else ""
    return bool(spec) and "-cloud" not in model and not model.endswith(":cloud")

def is_vault_approved(engine):
    if wall_is_open() and is_registered_engine(engine):
        return True
    return is_local_engine(engine) or str(engine or "") in VAULT_APPROVED_ENGINES

def wall_is_open():
    import config as _cfg
    return bool(getattr(_cfg, "VAULT_WALL_OPEN", True))

def is_registered_engine(engine):
    name = str(engine or "")
    return any(name in registry for registry in (
        MODEL_MAP, CLOUD_MODEL_MAP, GROQ_MODEL_MAP, OPENAI_MODEL_MAP, ANTHROPIC_MODEL_MAP))

_post = _requests_mod.post

def _stream_transport(url, **kw):
    return _requests_mod.post(url, stream=True, **kw)

_post_stream = _stream_transport

import hashlib as _hashlib
import threading as _threading
import time as _time
import traceback as _traceback

SPEND_LOG = _os.environ.get("WREN_SPEND_LOG") or _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "wren_spend.jsonl")
_spend_lock = _threading.Lock()

def _flat_ints(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}{k}"
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out[key] = v
            elif isinstance(v, dict):
                out.update(_flat_ints(v, key + "."))
    return out

def _call_site():
    here = _os.path.abspath(__file__)
    frames = []
    for f in reversed(_traceback.extract_stack()[:-3]):
        fn = _os.path.abspath(f.filename)
        if fn == here or "site-packages" in fn or "\\lib\\" in fn.lower():
            continue
        frames.append(f"{_os.path.basename(fn)}:{f.name}:{f.lineno}")
        if len(frames) >= 5:
            break
    return " < ".join(frames)

def _spend_record(url, kw, status, elapsed, usage, stream, error=None):
    try:
        pl = kw.get("json") or {}
        tools = pl.get("tools")
        rec = {
            "ts": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": pl.get("model"),
            "endpoint": str(url).split("://", 1)[-1],
            "stream": stream,
            "status": status,
            "ms": int(elapsed * 1000),
            "usage": usage,
            "tools": len(tools) if isinstance(tools, list) else 0,
            "tools_hash": _hashlib.md5(json.dumps(tools, sort_keys=True).encode()).hexdigest()[:10] if tools else None,
            "prompt_chars": len(json.dumps(pl.get("input") or pl.get("messages") or [])) + len(str(pl.get("system") or "")),
            "cache_opts": pl.get("prompt_cache_options"),
            "thread": _threading.current_thread().name,
            "caller": _call_site(),
        }
        if error:
            rec["error"] = error
        with _spend_lock, open(SPEND_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass

def _logged_post(url, **kw):
    t0 = _time.time()
    try:
        r = _requests_mod.post(url, **kw)
    except Exception as e:
        _spend_record(url, kw, None, _time.time() - t0, None, False, type(e).__name__)
        raise
    usage = None
    try:
        body = r.json()
        usage = _flat_ints(body.get("usage")) or _flat_ints(
            {k: body.get(k) for k in ("prompt_eval_count", "eval_count")}) or None
    except Exception:
        pass
    _spend_record(url, kw, getattr(r, "status_code", None), _time.time() - t0, usage, False)
    return r

def _logged_stream(url, **kw):
    t0 = _time.time()
    try:
        r = _requests_mod.post(url, stream=True, **kw)
    except Exception as e:
        _spend_record(url, kw, None, _time.time() - t0, None, True, type(e).__name__)
        raise
    _spend_record(url, kw, getattr(r, "status_code", None), _time.time() - t0, None, True)
    return r

_post = _logged_post
_post_stream = _logged_stream

def _err(reason, status, detail=None):
    e = {"ok": False, "reason": reason, "status": status}
    if detail:
        e["provider_error"] = detail
    return e

_EVAL_LANE_ENV = "FORGE_EVAL_MODELS"
_PROVIDER_ERROR_CAP = 300
_ECHO_SPAN = 40
_QUOTED_MAX = 60
_REDACTED = "[redacted]"
_ECHO_MARK = "[request-content-removed]"

_KEYISH = re.compile(
    r"sk-[A-Za-z0-9_\-]{8,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{8,}"
    r"|\b[A-Fa-f0-9]{20,}\b"
    r"|\b[A-Za-z0-9+/]{24,}={0,2}"
)
_QUOTED = re.compile(r"([\"'])(.{%d,}?)\1" % (_QUOTED_MAX + 1), re.S)
_TAG_OK = re.compile(r"^[A-Za-z0-9_.\[\]\-]{1,48}$")
_TAG_MAX = 3

def _eval_lane_active():
    return _os.environ.get(_EVAL_LANE_ENV, "") == "1"

def _strip_request_echo(msg, payload_text):
    if not payload_text or len(msg) < _ECHO_SPAN:
        return msg
    covered = [False] * len(msg)
    hit = False
    for i in range(len(msg) - _ECHO_SPAN + 1):
        if msg[i:i + _ECHO_SPAN] in payload_text:
            hit = True
            for j in range(i, i + _ECHO_SPAN):
                covered[j] = True
    if not hit:
        return msg
    out, i = [], 0
    while i < len(msg):
        if covered[i]:
            while i < len(msg) and covered[i]:
                i += 1
            out.append(_ECHO_MARK)
        else:
            out.append(msg[i])
            i += 1
    return "".join(out)

def _request_texts(payload):
    if payload is None:
        return "", ""
    try:
        full = json.dumps(payload)
    except Exception:
        full = str(payload)
    parts = []
    if isinstance(payload, dict):
        sysmsg = payload.get("system")
        if isinstance(sysmsg, str):
            parts.append(sysmsg)
        for m in payload.get("messages") or []:
            c = m.get("content") if isinstance(m, dict) else None
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        parts.append(part["text"])
    return full, "\n".join(parts)

def _safe_tag(value, content_text):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or not _TAG_OK.match(s):
        return None
    if _KEYISH.search(s):
        return None
    if content_text and s.lower() in content_text.lower():
        return None
    return s

def _sanitize_provider_error(resp, payload=None):
    try:
        body = resp.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        tags = [(k, err.get(k)) for k in ("type", "code", "param")]
    elif isinstance(err, str):
        msg, tags = err, []
    else:
        msg, tags = body.get("message"), []
    msg = msg if isinstance(msg, str) else ""
    full_text, content_text = _request_texts(payload)
    msg = _KEYISH.sub(_REDACTED, msg)
    msg = _QUOTED.sub(lambda m: m.group(1) + _REDACTED + m.group(1), msg)
    msg = _strip_request_echo(msg, full_text)
    bits = []
    for k, v in tags:
        safe = _safe_tag(v, content_text)
        if safe is not None:
            bits.append(f"{k}={safe}")
        if len(bits) >= _TAG_MAX:
            break
    out = msg.strip()
    if bits:
        out = (out + " " if out else "") + "(" + "; ".join(bits) + ")"
    out = " ".join(out.split())
    if not out:
        return None
    return out[:_PROVIDER_ERROR_CAP]

EVAL_REASONING_ALLOWED = ("none", "low", "medium", "high")

def _eval_extra(spec, tools, reasoning=None):
    extra = dict(spec.get("tools_params") or {}) if tools else {}
    if reasoning is not None:
        if reasoning not in EVAL_REASONING_ALLOWED:
            return None, _err("reasoning-config", 400)
        extra.setdefault("reasoning_effort", reasoning)
    ev = spec.get("eval_reasoning")
    if ev is not None:
        if _os.environ.get("FORGE_EVAL_MODELS", "") != "1":
            return None, _err("eval-config", 403)
        if ev not in EVAL_REASONING_ALLOWED:
            return None, _err("eval-config", 400)
        extra.setdefault("reasoning_effort", ev)
    return (extra or None), None

def _from_status(code, resp=None, payload=None):
    detail = None
    if resp is not None and _eval_lane_active():
        detail = _sanitize_provider_error(resp, payload)
    if code in (401, 403):
        return _err("auth", 503, detail)
    if code == 429:
        return _err("rate-limited", 429, detail)
    if code == 402:
        return _err("no-credits", 402, detail)
    return _err("upstream", 502, detail)

def _text_parts_to_string(messages):
    if not isinstance(messages, list):
        return messages
    out = []
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if (isinstance(c, list) and c
                and all(isinstance(p, dict) and p.get("type") in ("input_text", "text")
                        and isinstance(p.get("text"), str) for p in c)):
            m = {**m, "content": "\n\n".join(p["text"] for p in c if p["text"])}
        out.append(m)
    return out

def _developer_to_system(messages):
    if not isinstance(messages, list):
        return messages
    return [{**m, "role": "system"} if isinstance(m, dict) and m.get("role") == "developer" else m
            for m in messages]

def complete(scope, engine, messages, tools=None, timeout=180, reasoning=None):
    if is_vault_scope(scope) and not is_vault_approved(engine):
        return _err("vault-wall", 403)
    messages = credfilter.scrub_messages(messages)
    if engine not in OPENAI_MODEL_MAP:
        messages = _developer_to_system(_text_parts_to_string(messages))
    try:
        if reasoning is not None and engine not in OPENAI_MODEL_MAP:
            return _err("reasoning-config", 400)
        if engine in ANTHROPIC_MODEL_MAP:
            return _anthropic(engine, messages, tools, timeout)
        if engine in OPENAI_MODEL_MAP:
            spec = OPENAI_MODEL_MAP[engine]
            extra, everr = _eval_extra(spec, tools, reasoning=reasoning)
            if everr:
                return everr
            return _openai_compatible(
                spec["url"], OPENAI_API_KEY, spec["model"], messages, tools,
                timeout, extra=extra)
        if engine in GROQ_MODEL_MAP:
            return _openai_compatible(
                GROQ_MODEL_MAP[engine]["url"], GROQ_KEY,
                GROQ_MODEL_MAP[engine]["model"], messages, tools, min(timeout, 120))
        if engine in CLOUD_MODEL_MAP:
            return _openai_compatible(
                "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY,
                CLOUD_MODEL_MAP[engine]["model"], messages, tools, timeout)
        if engine in MODEL_MAP:
            return _ollama(MODEL_MAP[engine]["model"], messages, tools)
        return _err("unknown-engine", 400)
    except Exception:
        return _err("error", 500)

def complete_stream(scope, engine, messages, timeout=180, cancel=None):
    if is_vault_scope(scope) and not is_vault_approved(engine):
        yield {"error": "vault-wall", "status": 403}
        return
    messages = credfilter.scrub_messages(messages)
    if engine not in OPENAI_MODEL_MAP:
        messages = _developer_to_system(_text_parts_to_string(messages))
    try:
        if engine in ANTHROPIC_MODEL_MAP:
            yield from _anthropic_stream(engine, messages, timeout)
        elif engine in OPENAI_MODEL_MAP:
            if OPENAI_MODEL_MAP[engine].get("eval_reasoning") is not None:
                yield {"error": "eval-config", "status": 400}
                return
            yield from _openai_compatible_stream(
                OPENAI_MODEL_MAP[engine]["url"], OPENAI_API_KEY,
                OPENAI_MODEL_MAP[engine]["model"], messages, timeout)
        elif engine in GROQ_MODEL_MAP:
            yield from _openai_compatible_stream(
                GROQ_MODEL_MAP[engine]["url"], GROQ_KEY,
                GROQ_MODEL_MAP[engine]["model"], messages, timeout)
        elif engine in CLOUD_MODEL_MAP:
            yield from _openai_compatible_stream(
                "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY,
                CLOUD_MODEL_MAP[engine]["model"], messages, timeout)
        elif engine in MODEL_MAP:
            yield from _ollama_stream(MODEL_MAP[engine]["model"], messages,
                                      cancel=cancel)
        else:
            yield {"error": "unknown-engine", "status": 400}
    except GeneratorExit:
        raise
    except Exception:
        yield {"error": "error", "status": 500}

def _stream_err(e):
    ev = {"error": e["reason"], "status": e["status"]}
    if e.get("provider_error"):
        ev["provider_error"] = e["provider_error"]
    return ev

def _sse_data_lines(resp):
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if line.startswith("data:"):
            yield line[5:].strip()

def _responses_content(role, content):
    if not isinstance(content, list):
        return content
    text_type = "output_text" if role == "assistant" else "input_text"
    out = []
    for part in content:
        if isinstance(part, str):
            out.append({"type": text_type, "text": part})
            continue
        kind = part.get("type") if isinstance(part, dict) else None
        if kind == "text" and isinstance(part.get("text"), str):
            out.append({"type": text_type, "text": part["text"]})
        elif kind == "image_url":
            if role == "assistant":
                continue
            ref = part.get("image_url")
            url = ref.get("url") if isinstance(ref, dict) else ref
            if not isinstance(url, str) or not url:
                continue
            image = {"type": "input_image", "image_url": url}
            detail = ref.get("detail") if isinstance(ref, dict) else None
            if detail in ("low", "high", "auto"):
                image["detail"] = detail
            out.append(image)
        else:
            out.append(part)
    return out

def _has_invalid_image_part(messages):
    for m in messages or []:
        if not (isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), list)):
            continue
        for part in m["content"]:
            if isinstance(part, dict) and part.get("type") == "image_url":
                ref = part.get("image_url")
                url = ref.get("url") if isinstance(ref, dict) else ref
                if not isinstance(url, str) or not url:
                    return True
    return False

def _for_responses(m):
    if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), list):
        return {**m, "content": _responses_content(m["role"], m["content"])}
    return m

def _openai_compatible_stream(url, key, model, messages, timeout):
    is_responses_api = "/responses" in url
    if is_responses_api and _has_invalid_image_part(messages):
        yield {"error": "invalid-image-part", "status": 400}
        return
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    pl = {"model": model, "stream": True}
    if is_responses_api:
        mapped_input = []
        for m in messages:
            role = m.get("role")
            if role in ("system", "developer", "user"):
                mapped_input.append(_for_responses(m))
            elif role == "assistant":
                if m.get("tool_calls"):
                    if m.get("content"):
                        mapped_input.append({"role": "assistant",
                                             "content": _responses_content("assistant", m.get("content"))})
                    for tc in m.get("tool_calls"):
                        fn = tc.get("function", {})
                        mapped_input.append({
                            "type": "function_call",
                            "call_id": tc.get("id"),
                            "name": fn.get("name"),
                            "arguments": fn.get("arguments")
                        })
                else:
                    mapped_input.append(_for_responses(m))
            elif role == "tool":
                mapped_input.append({
                    "type": "function_call_output",
                    "call_id": m.get("tool_call_id"),
                    "output": m.get("content")
                })
        pl["input"] = mapped_input
    else:
        pl["messages"] = messages

    def _has_breakpoint(items):
        for m in items or []:
            c = m.get("content") if isinstance(m, dict) else None
            if isinstance(c, list) and any(isinstance(p, dict) and "prompt_cache_breakpoint" in p
                                           for p in c):
                return True
        return False

    if is_responses_api and _has_breakpoint(pl.get("input")):
        pl["prompt_cache_options"] = {"mode": "explicit", "ttl": "30m"}

    resp = _post_stream(url, headers=hdr, json=pl, timeout=timeout)
    try:
        if getattr(resp, "status_code", 200) >= 400:
            yield _stream_err(_from_status(resp.status_code, resp, pl))
            return
        for data in _sse_data_lines(resp):
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
            except ValueError:
                continue
            if is_responses_api:
                ev_type = j.get("type")
                if ev_type == "response.output_text.delta":
                    delta = j.get("delta")
                    if delta:
                        yield {"delta": delta}
                elif ev_type == "response.completed":
                    break
                elif ev_type == "error":
                    yield {"error": "upstream", "status": 502}
                    return
            else:
                delta = ((j.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    yield {"delta": delta}
        yield {"done": True}
    finally:
        try:
            resp.close()
        except Exception:
            pass

def _anthropic_stream(engine, messages, timeout):
    if not ANTHROPIC_API_KEY:
        yield {"error": "auth", "status": 503}
        return
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    convo = [{"role": m["role"], "content": _anthropic_blocks(m.get("content"))}
             for m in messages if m.get("role") != "system"]
    pl = {"model": ANTHROPIC_MODEL_MAP[engine]["model"], "max_tokens": 2048,
          "messages": convo, "stream": True}
    if system_parts:
        pl["system"] = "\n\n".join(str(s) for s in system_parts)
    hdr = {"x-api-key": ANTHROPIC_API_KEY,
           "anthropic-version": ANTHROPIC_VERSION,
           "Content-Type": "application/json"}
    resp = _post_stream(ANTHROPIC_URL, headers=hdr, json=pl, timeout=timeout)
    try:
        if getattr(resp, "status_code", 200) >= 400:
            yield _stream_err(_from_status(resp.status_code, resp, pl))
            return
        for data in _sse_data_lines(resp):
            try:
                j = json.loads(data)
            except ValueError:
                continue
            t = j.get("type")
            if t == "content_block_delta":
                text = (j.get("delta") or {}).get("text")
                if text:
                    yield {"delta": text}
            elif t == "message_stop":
                break
            elif t == "error":
                yield {"error": "upstream", "status": 502}
                return
        yield {"done": True}
    finally:
        try:
            resp.close()
        except Exception:
            pass

def _cancel_watch(cancel, resp, finished, cancelled):
    is_event = hasattr(cancel, "wait")
    while not finished.is_set():
        if is_event:
            if cancel.wait(0.5):
                break
        else:
            try:
                if cancel():
                    break
            except Exception:
                return
            if finished.wait(0.5):
                return
    if finished.is_set():
        return
    cancelled.set()
    try:
        resp.close()
    except Exception:
        pass

def _ollama_stream(model, messages, cancel=None):
    pl = {"model": model, "messages": messages, "stream": True,
          "options": {"num_ctx": 131072}}
    resp = _post_stream(OLLAMA_URL, json=pl, timeout=300)
    finished = cancelled = None
    if cancel is not None:
        import threading as _t
        finished, cancelled = _t.Event(), _t.Event()
        _t.Thread(target=_cancel_watch, args=(cancel, resp, finished, cancelled),
                  name="ollama-cancel", daemon=True).start()
    try:
        if getattr(resp, "status_code", 200) >= 400:
            yield _stream_err(_from_status(resp.status_code, resp, pl))
            return
        try:
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) \
                    else str(raw)
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                delta = (j.get("message") or {}).get("content")
                if delta:
                    yield {"delta": delta}
                if j.get("done"):
                    break
        except Exception:
            if cancelled is not None and cancelled.is_set():
                yield {"error": "cancelled", "status": 499}
                return
            raise
        yield {"done": True}
    finally:
        if finished is not None:
            finished.set()
        try:
            resp.close()
        except Exception:
            pass

def normalize_usage(raw):
    if not isinstance(raw, dict):
        return None
    u = raw.get("usage")
    src = u if isinstance(u, dict) else {}
    out = {}
    for s, d in (("prompt_tokens", "input_tokens"),
                 ("input_tokens", "input_tokens"),
                 ("completion_tokens", "output_tokens"),
                 ("output_tokens", "output_tokens"),
                 ("total_tokens", "total_tokens")):
        v = src.get(s)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and d not in out:
            out[d] = int(v)
    for s, d in (("prompt_eval_count", "input_tokens"),
                 ("eval_count", "output_tokens")):
        v = raw.get(s)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and d not in out:
            out[d] = int(v)
    return out or None

def _openai_compatible(url, key, model, messages, tools, timeout, extra=None):
    import json
    import hashlib
    is_responses_api = "/responses" in url
    if is_responses_api and _has_invalid_image_part(messages):
        return _err("invalid-image-part", 400)
    
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    pl = {"model": model}
    if is_responses_api:
        mapped_input = []
        for m in messages:
            role = m.get("role")
            if role in ("system", "developer", "user"):
                mapped_input.append(_for_responses(m))
            elif role == "assistant":
                if m.get("tool_calls"):
                    if m.get("content"):
                        mapped_input.append({"role": "assistant",
                                             "content": _responses_content("assistant", m.get("content"))})
                    for tc in m.get("tool_calls"):
                        fn = tc.get("function", {})
                        mapped_input.append({
                            "type": "function_call",
                            "call_id": tc.get("id"),
                            "name": fn.get("name"),
                            "arguments": fn.get("arguments")
                        })
                else:
                    mapped_input.append(_for_responses(m))
            elif role == "tool":
                mapped_input.append({
                    "type": "function_call_output",
                    "call_id": m.get("tool_call_id"),
                    "output": m.get("content")
                })
        pl["input"] = mapped_input
    else:
        pl["messages"] = messages
        
    if tools:
        if is_responses_api:
            tools = [{"type": "function", **t["function"]}
                     if isinstance(t, dict) and isinstance(t.get("function"), dict) else t
                     for t in tools]
        pl["tools"] = tools
    if extra:
        extra = dict(extra)
        if is_responses_api and "reasoning_effort" in extra:
            pl["reasoning"] = {"effort": extra.pop("reasoning_effort")}
        pl.update(extra)
        
    def _has_breakpoint(items):
        for m in items or []:
            c = m.get("content") if isinstance(m, dict) else None
            if isinstance(c, list) and any(isinstance(p, dict) and "prompt_cache_breakpoint" in p
                                           for p in c):
                return True
        return False

    if _has_breakpoint(pl.get("input") or pl.get("messages")):
        pl["prompt_cache_options"] = {"mode": "explicit", "ttl": "30m"}
    
    tools_hash = hashlib.md5(json.dumps(tools).encode()).hexdigest() if tools else "none"
    prompt_size = len(json.dumps(messages))
    
    r = _post(url, headers=hdr, json=pl, timeout=timeout)
    if getattr(r, "status_code", 200) >= 400:
        return _from_status(r.status_code, r, pl)
    jr = r.json()
    
    if is_responses_api:
        if "output" not in jr:
            return _err("invalid-output", 502)
        out_items = jr.get("output", [])
        content = ""
        tool_calls = []
        for item in out_items:
            if item.get("type") in ("message", "reasoning"):
                for block in item.get("content", []):
                    if block.get("type") in ("text", "output_text"):
                        content += block.get("text", "")
            elif item.get("type") == "function_call":
                tool_calls.append({
                    "id": item.get("call_id"),
                    "type": "function",
                    "function": {
                        "name": item.get("name"),
                        "arguments": item.get("arguments")
                    }
                })
        m = {"content": content, "tool_calls": tool_calls or None}
    else:
        if "choices" not in jr or not jr["choices"]:
            return _err("invalid-output", 502)
        m = (jr["choices"][0] or {}).get("message", {}) or {}
    
    u = jr.get("usage", {})
    details = u.get("prompt_tokens_details", u.get("input_tokens_details", {}))
    print(f"\n--- API CACHE LOG ---")
    print(f"Model: {model}")
    print(f"Tools Hash: {tools_hash}")
    print(f"Prompt Size: {prompt_size} chars")
    print(f"usage.input_tokens: {u.get('prompt_tokens', u.get('input_tokens', 0))}")
    print(f"usage.input_tokens_details.cached_tokens: {details.get('cached_tokens', 0)}")
    print(f"usage.input_tokens_details.cache_write_tokens: {details.get('cache_write_tokens', 0)}")
    print(f"---------------------\n")
    
    return {"ok": True, "content": m.get("content"), "tool_calls": m.get("tool_calls"),
            "usage": normalize_usage(jr), "raw": jr}

def _ollama(model, messages, tools):
    pl = {"model": model, "messages": messages, "stream": False,
          "options": {"num_ctx": 131072}}
    if tools:
        pl["tools"] = tools
    r = _post(OLLAMA_URL, json=pl, timeout=300)
    if getattr(r, "status_code", 200) >= 400:
        return _from_status(r.status_code, r, pl)
    jr = r.json()
    m = jr.get("message") or {}
    if not m:
        return _err("invalid-output", 502)
    return {"ok": True, "content": m.get("content"), "tool_calls": m.get("tool_calls"),
            "usage": normalize_usage(jr), "raw": jr}

def _anthropic_blocks(content):
    if not isinstance(content, list):
        return content
    blocks = []
    for part in content:
        t = (part or {}).get("type")
        if t == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif t == "image_url":
            url = ((part.get("image_url") or {}).get("url")) or ""
            if url.startswith("data:") and "," in url:
                head, data = url.split(",", 1)
                media = head[5:].split(";", 1)[0] or "image/png"
                blocks.append({"type": "image", "source":
                               {"type": "base64", "media_type": media, "data": data}})
            elif url:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    return blocks or ""

def _anthropic(engine, messages, tools, timeout):
    if not ANTHROPIC_API_KEY:
        return _err("auth", 503)
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    convo = [{"role": m["role"], "content": _anthropic_blocks(m.get("content"))}
             for m in messages if m.get("role") != "system"]
    pl = {
        "model": ANTHROPIC_MODEL_MAP[engine]["model"],
        "max_tokens": 2048,
        "messages": convo,
    }
    if system_parts:
        pl["system"] = "\n\n".join(str(s) for s in system_parts)
    hdr = {"x-api-key": ANTHROPIC_API_KEY,
           "anthropic-version": ANTHROPIC_VERSION,
           "Content-Type": "application/json"}
    r = _post(ANTHROPIC_URL, headers=hdr, json=pl, timeout=timeout)
    if getattr(r, "status_code", 200) >= 400:
        body = ""
        try:
            body = json.dumps(r.json())
        except Exception:
            pass
        if r.status_code == 400 and "credit" in body.lower():
            return _err("no-credits", 402,
                        _sanitize_provider_error(r, pl)
                        if _eval_lane_active() else None)
        return _from_status(r.status_code, r, pl)
    jr = r.json()
    blocks = jr.get("content") or []
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        return _err("invalid-output", 502)
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return {"ok": True, "content": text, "tool_calls": None,
            "usage": normalize_usage(jr), "raw": jr}
