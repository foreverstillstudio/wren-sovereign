# ============================================================
# WREN KERNEL — the Intelligence Gateway
# ------------------------------------------------------------
# ONE composition path for every conversation with Wren. The system
# prompt is assembled in constitutional order — soul, then charter
# (identity may extend the law, never override it), then the standing
# untrusted-content rule, then the room profile, then what the keeper
# has taught, then memory — and the completion routes through the
# provider, which owns the vault wall.
#
# The gateway has NO execute paths. Tool execution stays with the
# existing guarded tool layer; consequential kinds are refused by the
# charter gate wherever execution is attempted.
# ============================================================

import json
import os
import re
import threading

from wren.mind import soul, charter
from wren.system import permissions
from wren.core import provider, continuity
from wren.tools import provenance
from wren import rooms as room_registry
from wren.system import stewards as _stewards
from wren.mind.lessons import lessons_to_prompt
from wren.mind.memory import active_memories, memory_line
from wren.tools import offer
from wren.tools import toolsection
from wren.system import steward_stores
from wren.mind import conversations as convo_store
from wren.core import context_trim
from wren.senses import pictures as pictures_mod
from wren.senses import sanitize

GATEWAY_VERSION = "0.3.2"


def resolve_speaker(room, speaker=None):
    """Whose soul speaks (ported from the desktop gateway 0.4.0, the
    2026-08-29 identity-routing fix).

    The ROOM keeps deciding tools, capabilities, memory scopes, vault
    posture, and context. The SPEAKER decides only which established
    companion identity is projected — so Wren's companion panel walking
    into the Forge stays Wren, while Ember's own surfaces (which send no
    speaker) keep resolving to the room's steward exactly as before.

    `speaker` is UNTRUSTED client input: it must name a roster steward
    that is embodied with a local soul, or this raises — an unknown or
    unspeakable identity fails closed, never falls back."""
    rid = permissions.normalize_room(room)
    if speaker is None or str(speaker).strip() == "":
        return room_registry.get_room(rid)["steward"]
    sid = str(speaker).strip().lower()
    s = _stewards.get(sid)
    if not (s and s["embodied"] and s["soul_file"]):
        raise ValueError(f"unknown speaker {sid!r} — no such locally-embodied "
                         "steward; refusing to invent an identity.")
    return sid

# ── the global relationship profile (2026-09-06) ────────────────────────────
_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "wren_profile.md")


def profile_text():
    try:
        with open(_PROFILE_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


_ABOUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "about_chrissy.md")


def about_text():
    try:
        with open(_ABOUT_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def build_system_prompt(room="general", memories=None, lessons=None,
                        memory_section=None, extra_context="", today=None,
                        speaker=None, split_cache=False, tool_notes=None,
                        tool_section=None, machine=None):
    current_speaker = resolve_speaker(room, speaker)
    owner = steward_stores.storage_steward(current_speaker)
    if current_speaker == "wren" and profile_text():
        identity_part = profile_text()
    elif owner == "wren":
        identity_part = soul.build_identity(steward=current_speaker)
        if profile_text():
            identity_part = f"{identity_part}\n\n{profile_text()}"
    else:
        identity_part = soul.build_identity(steward=current_speaker)
        if about_text():
            identity_part = f"{identity_part}\n\n{about_text()}"

    where = f"# Where you are\n{room_registry.room_frame(permissions.normalize_room(room))}"
    if machine and str(machine).strip():
        where += f"\n# Which machine\n{str(machine).strip()}"
    parts = [
        identity_part,
        charter.build_charter(),
        continuity.format_continuity_block(),
        f"# Standing rule on outside text\n{sanitize.TRUST_BOUNDARY_RULE}",
        where,
    ]
    lp = lessons_to_prompt(lessons)
    if lp:
        parts.append(lp)
    section = str(tool_section or "").strip()
    if section:
        parts.append(section)
    notes = [str(n).strip() for n in (tool_notes or []) if str(n).strip()]
    if notes:
        parts.append("# Tools withheld this turn\n" + "\n".join("- " + n for n in notes))
        
    stable_text = "\n\n".join(parts)
    
    dynamic_parts = []
    if memory_section:
        dynamic_parts.append(str(memory_section))
    else:
        mems = active_memories(memories, today) if memories else []
        if mems:
            lines = "\n".join(f"- {memory_line(m)}" for m in mems)
            dynamic_parts.append("# What you remember\nEach line carries its own status — "
                                 "rely on facts, respect expiries, treat unconfirmed "
                                 "preferences as hypotheses.\n" + lines)
    if extra_context:
        raw_extra = str(extra_context).strip()
        if raw_extra:
            dynamic_parts.append(
                "# Supplied room context\n"
                "This context was supplied to Wren; it is not independently verified by Wren.\n" +
                raw_extra
            )
        
    dynamic_text = "\n\n".join(dynamic_parts)
    
    if split_cache:
        return stable_text, dynamic_text
    return stable_text + ("\n\n" + dynamic_text if dynamic_text else "")


def _entry(m):
    content = m.get("content", "")
    e = {"role": m.get("role"),
         "content": content if isinstance(content, list) else str(content)}
    if m.get("images"):
        e["images"] = m["images"]
    return e


def _speaker_gate(room, speaker, conversation):
    try:
        resolved = resolve_speaker(room, speaker)
    except ValueError as e:
        return False, {"ok": False, "reason": str(e), "status": 400}
    if speaker is not None and str(speaker).strip() and conversation:
        try:
            from wren.mind import conversations as convo_store
            with steward_stores.steward_scope(steward_stores.storage_steward(resolved)):
                conv = convo_store.get(str(conversation))
        except Exception as e:
            return False, {
                "ok": False, "status": 503,
                "reason": ("this companion's conversation store could not be read "
                           f"({type(e).__name__}) — refusing the turn rather than guess "
                           "which conversation it belongs to.")}
        established = (conv or {}).get("speaker")
        if established and established != resolved:
            return False, {
                "ok": False, "status": 409,
                "reason": (f"this conversation is {established}'s — "
                           f"refusing to continue it as {resolved}. "
                           "Start a new conversation for a different "
                           "companion.")}
    return True, resolved


def _strip_client_manifests(messages):
    cleaned = []
    for m in (messages or []):
        m = dict(m)
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            text = m["content"]
            if text.lstrip().startswith("[SYSTEM CONTEXT]") and "[END SYSTEM CONTEXT]" in text:
                m["content"] = text.split("[END SYSTEM CONTEXT]", 1)[1].strip()
        cleaned.append(m)
    return cleaned


_PRIVATE_NOTE = "(not written to disk: private to {who})"
COMPOSED_DIR = None


def _capture_composed(room, speaker, engine, stable_sys, dynamic_sys, memory_section, convo,
                      private=()):
    try:
        import json
        import os
        import re
        import time
        who = re.sub(r"[^a-z0-9_-]", "", str(speaker or "").lower()) or "unknown"
        note = _PRIVATE_NOTE.format(who=who)
        stable = stable_sys or ""
        for frag in private or ():
            if frag and frag in stable:
                stable = stable.replace(frag, note)
        snapshot = {
            "at": time.time(),
            "room": room,
            "speaker": speaker,
            "engine": engine,
            "message_count": len(convo or []),
            "stable_system": stable,
            "dynamic_system": note,
            "memory_section": note,
            "dynamic_system_chars": len(dynamic_sys or ""),
            "memory_section_chars": len(memory_section or ""),
            "private_withheld": True,
        }
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        out_dir = COMPOSED_DIR or os.path.join(repo_root, "data")
        for name in ("last_composed.%s.json" % who, "last_composed.json"):
            path = os.path.join(out_dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
    except Exception as e:
        print(f"[wren] composed-context capture failed ({e})")


def _compose(scope, room, engine, messages, extra_context, today, conversation,
             speaker=None, evidence_events=None, client_turn_id=None, tool_notes=None,
             tool_section=None, pictures=None, picture_words=True, machine=None):
    messages = _strip_client_manifests(messages)
    rid = permissions.normalize_room(room)
    resolved_speaker = resolve_speaker(room, speaker)
    vault = room_registry.room_vault_scope(rid)
    if vault:
        scope = vault
    memory_section, sources, lessons = "", [], []
    try:
        from wren.core import assembler
        from wren.mind import memory_store
        query = ""
        for m in reversed(messages or []):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                query = m["content"]
                break
        asm = assembler.assemble(room_registry.room_memory_scopes(rid),
                                 query=query, today=today,
                                 current_conversation=str(conversation) if conversation else None)
        memory_section, sources = asm["prompt_section"], asm["sources"]
        lessons = memory_store.lessons()
    except steward_stores.StewardStoreError:
        raise
    except Exception as e:
        print(f"[wren] governed store unreadable ({e}) — composing without memory")
    stable_sys, dynamic_sys = build_system_prompt(room=room, lessons=lessons,
                                 memory_section=memory_section,
                                 extra_context="", today=today,
                                 speaker=speaker, split_cache=True,
                                 tool_notes=tool_notes,
                                 tool_section=tool_section,
                                 machine=machine)

    conv_id, omitted_vault, context = None, 0, None
    evidence = []
    counts = {}
    if conversation is not None:
        try:
            from wren.mind import conversations as convo_store
            new_user = next((m for m in reversed(messages or [])
                             if m.get("role") == "user"), None)
            born_vault = bool(room_registry.room_vault_scope(rid))
            challenge = provenance.attribution_challenge(
                (new_user or {}).get("content", ""))
            if challenge and conversation:
                existing = convo_store.get(str(conversation))
                prior = next((t for t in reversed((existing or {}).get("turns", []))
                              if t.get("role") == "assistant"), None)
                if prior:
                    convo_store.dispute_turn_provenance(
                        str(conversation), prior.get("id"), challenge)
            if new_user and new_user.get("disputes_turn_id"):
                convo_store.dispute_turn_provenance(
                    conversation, str(new_user["disputes_turn_id"]),
                    str(new_user.get("dispute_reason") or
                        "Chris disputed this source attribution"))
            conv_rec, _turn = convo_store.append_turn(
                conversation or None, "user",
                (new_user or {}).get("content", ""), rid, engine,
                vault=born_vault,
                provenance=(new_user or {}).get("provenance"),
                client_turn_id=client_turn_id)
            conv_id = conv_rec["id"]
            if speaker is not None and str(speaker).strip():
                convo_store.bind_speaker(conv_id,
                                         resolve_speaker(room, speaker))
            exclude_vault = not provider.is_vault_approved(engine)
            win = convo_store.window(conv_id, exclude_vault, current_room=rid)
            omitted_vault = win["omitted_vault"]
            context = context_meter(win)
            note = convo_store.vault_exclusion_note(omitted_vault)
            if note:
                dynamic_sys = dynamic_sys + "\n\n" + note if dynamic_sys else note
            earlier = convo_store.summary_section(conv_id, win.get("start", 0))
            if earlier:
                dynamic_sys = dynamic_sys + "\n\n" + earlier if dynamic_sys else earlier
            try:
                from wren.mind import memory_tools
                can_recall = "recall_turns" in memory_tools.names_for(rid, resolved_speaker)
            except Exception:
                can_recall = False
            window_msgs, cut = context_trim.trim_history(
                win["messages"], indexes=win.get("indexes"), conversation=conv_id, can_recall=can_recall)
            sent_chars = sum(len(m.get("content") or "") if isinstance(m.get("content"), str) else 0
                             for m in window_msgs)
            context = context_meter(win)
            counts.update({"window_chars_stored": int(win.get("chars") or 0), "window_chars_sent": sent_chars,
                           "window_turns": len(window_msgs), "dropped_turns": int(win.get("dropped") or 0),
                           "history_messages_cut": cut["cut"], "history_chars_saved": cut["saved_chars"],
                           "summary_chars": int(win.get("summary_chars") or 0)})
            evidence = list(win.get("evidence") or [])
            if new_user is not None and window_msgs:
                window_msgs[-1] = _entry(new_user)
            convo = [{"role": "developer", "content": [
                {"type": "input_text", "text": stable_sys, "prompt_cache_breakpoint": {"mode": "explicit"}},
                {"type": "input_text", "text": dynamic_sys}
            ]}] + window_msgs
        except Exception as e:
            print(f"[wren] conversation store unavailable ({e}) — "
                  "this turn will not persist")
            conversation, conv_id = None, None
    if conversation is None:
        convo = [{"role": "developer", "content": [
            {"type": "input_text", "text": stable_sys, "prompt_cache_breakpoint": {"mode": "explicit"}},
            {"type": "input_text", "text": dynamic_sys}
        ]}]
        for m in messages or []:
            if m.get("role") not in ("user", "assistant"):
                continue
            convo.append(_entry(m))
            evidence.append(provenance.for_turn(
                m.get("role"), m.get("content", ""),
                supplied=m.get("provenance")))

    current_turn_events = [
        provenance.normalize({k: v for k, v in e.items() if k != "verification_events"},
                             trusted=True)
        for e in (evidence_events or []) if isinstance(e, dict)
    ]
    evidence.extend(current_turn_events)
    turn_verification_events = [
        e for e in current_turn_events
        if e.get("source_type") == "tool_result" and e.get("verified_by_wren") is True
    ]
    if extra_context:
        raw_extra = str(extra_context).strip()
        if raw_extra:
            evidence.append(provenance.make(
                content=raw_extra,
                source_actor="Forge" if rid == "forge" else "other",
                source_type="agent_report", observed_by_wren=True,
                provenance_confidence="partial"))
    eblock = provenance.evidence_block(evidence)
    if eblock:
        dynamic_sys = dynamic_sys + "\n\n" + eblock if dynamic_sys else eblock
    if extra_context:
        raw_extra = str(extra_context).strip()
        if raw_extra:
            extra_ctx_str = ("\n\n# Supplied room context\nThis context was supplied to "
                       "Wren; it is not independently verified by Wren.\n" +
                       raw_extra)
            dynamic_sys = dynamic_sys + extra_ctx_str if dynamic_sys else extra_ctx_str
    
    convo[0]["content"][1]["text"] = dynamic_sys

    _capture_composed(rid, resolved_speaker, engine, stable_sys, dynamic_sys,
                      memory_section, convo, private=[lessons_to_prompt(lessons)])
    counts.update({"stable_chars": len(stable_sys or ""), "dynamic_chars": len(dynamic_sys or ""),
                   "memory_chars": len(memory_section or "")})
    pic_info = None
    if pictures:
        pic_info = {"key": pictures_mod.hold(pictures), "slot": len(convo) - 1, "count": len(pictures),
                    "words": bool(picture_words)}
        counts["pictures"] = len(pictures)
    _record_context_counts("compose", resolved_speaker, engine, counts)

    return {"scope": scope, "rid": rid, "speaker": resolved_speaker,
            "convo": convo, "sources": sources, "evidence": evidence,
            "turn_verification_events": turn_verification_events,
            "conv_id": conv_id, "omitted_vault": omitted_vault, "context": context, "pictures": pic_info}


def _grace_from_environment(default=0.75):
    try:
        return max(0.0, float(os.environ.get("WREN_SUMMARY_GRACE_SECONDS", default)))
    except (TypeError, ValueError):
        return default


SUMMARY_GRACE_SECONDS = _grace_from_environment()


class _SummaryWorker:
    def __init__(self):
        self._cond = threading.Condition()
        self._pending = {}
        self._thread = None
        self._busy = False
        self.stats = {"ran": 0, "failed": 0, "last_error": None, "last_ok_at": None}

    def submit(self, key, engine, delay=0.0):
        import time as _time
        with self._cond:
            self._pending[key] = (engine, _time.monotonic() + delay)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="wren-summary-worker",
                                                daemon=True)
                self._thread.start()
            self._cond.notify()

    def idle(self):
        with self._cond:
            return not self._pending and not self._busy

    def wait_idle(self, timeout=10.0):
        import time as _time
        end = _time.time() + timeout
        while _time.time() < end:
            if self.idle():
                return True
            _time.sleep(0.01)
        return False

    def _loop(self):
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                key = next(iter(self._pending))
                engine, not_before = self._pending.pop(key)
                self._busy = True
            try:
                import time as _time
                wait = not_before - _time.monotonic()
                if wait > 0:
                    _time.sleep(wait)
                self._run_one(key, engine)
            except BaseException as e:
                self._failed(key, e)
            finally:
                with self._cond:
                    self._busy = False

    def _run_one(self, key, engine):
        from wren.mind import conversations as convo_store
        from wren.system import summarize
        steward, conv_id = key
        with steward_stores.steward_scope(steward), convo_store.turn_snapshot():
            if _summary_is_due(conv_id):
                out = summarize.update(conv_id, engine, ahead_chars=summarize.LOOKAHEAD_TARGET_CHARS)
                if out and out.get("error"):
                    raise RuntimeError("summary pass returned an error: %s" % out["error"])
        import time as _time
        self.stats["ran"] += 1
        self.stats["last_ok_at"] = _time.strftime("%Y-%m-%d %H:%M:%S")

    def _failed(self, key, error):
        import traceback
        self.stats["failed"] += 1
        self.stats["last_error"] = "%s: %s" % (type(error).__name__, error)
        print("[wren] SUMMARY FAILED for %s/%s (%s); the chat turn is unaffected and the "
              "summary stays due.\n%s" % (key[0], key[1], self.stats["last_error"],
                                          traceback.format_exc().rstrip()))
        _write_summary_failure(key, error)


_DEFAULT_SUMMARY_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "summary_worker.log")
SUMMARY_LOG_PATH = None
_OWN_ERROR_PREFIX = "summary pass returned an error: "


def enable_durable_logs():
    global SUMMARY_LOG_PATH, CONTEXT_COUNTS_PATH
    SUMMARY_LOG_PATH = _DEFAULT_SUMMARY_LOG_PATH
    CONTEXT_COUNTS_PATH = _DEFAULT_CONTEXT_COUNTS_PATH


def _write_summary_failure(key, error):
    try:
        if not SUMMARY_LOG_PATH:
            return
        import time as _time
        text = str(error)
        line = {"at": _time.strftime("%Y-%m-%dT%H:%M:%S"), "steward": key[0], "conversation": key[1],
                "error_type": type(error).__name__,
                "reason": text[len(_OWN_ERROR_PREFIX):][:80] if text.startswith(_OWN_ERROR_PREFIX) else None}
        with open(SUMMARY_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
    except Exception:
        pass


_summary_worker = _SummaryWorker()


class SummaryGate:
    _local = threading.local()

    def __init__(self):
        self._held = []
        self._open = False

    def __enter__(self):
        self._previous = getattr(self._local, "gate", None)
        self._local.gate = self
        return self

    def __exit__(self, *exc):
        self._local.gate = self._previous
        return False

    def release(self):
        held, self._held = self._held, []
        self._open = True
        for key, engine in held:
            _summary_worker.submit(key, engine, delay=SUMMARY_GRACE_SECONDS)

    @classmethod
    def request(cls, key, engine):
        gate = getattr(cls._local, "gate", None)
        if gate is not None and not gate._open:
            gate._held.append((key, engine))
        else:
            _summary_worker.submit(key, engine)


def _summary_is_due(conv_id):
    from wren.mind import conversations as convo_store
    from wren.system import summarize
    conv = convo_store.get(conv_id)
    if not conv:
        return False
    covers = int(conv.get("summary_covers") or 0)
    if summarize.window_start(conv_id, summarize.LOOKAHEAD_TRIGGER_CHARS) > covers:
        return True
    total_chars = sum(len(t.get("content", "")) for t in conv.get("turns", []))
    return summarize.window_start(conv_id) == 0 and total_chars > summarize.long_thread_chars()


def _schedule_summary_after_reply(conv_id, engine):
    try:
        steward = steward_stores.current()
    except Exception as e:
        print(f"[wren] summary not requested ({e})")
        return
    SummaryGate.request((steward, conv_id), engine)


def _persist_reply(comp, engine, content, stopped=False):
    if not comp["conv_id"]:
        return
    if stopped:
        content = (content or "") + "\n\n[reply stopped by the keeper mid-stream]"
    try:
        from wren.mind import conversations as convo_store
        speaker = comp.get("speaker")
        reply_provenance = provenance.make(
            content=content,
            source_actor=("Wren" if speaker == "wren" else
                          "other" if speaker else "unknown"),
            source_type="inference" if speaker else "unknown",
            original_source=None if speaker == "wren" else speaker,
            provenance_confidence="known" if speaker else "partial")
        for ev in comp.get("turn_verification_events") or []:
            if ev.get("source_type") == "tool_result" and ev.get("verified_by_wren") is True:
                reply_provenance = provenance.with_verification(reply_provenance, ev)
        convo_store.append_turn(
            comp["conv_id"], "assistant", content, comp["rid"], engine,
            vault=bool(room_registry.room_vault_scope(comp["rid"])),
            provenance=reply_provenance, trusted_provenance=True)
        _schedule_summary_after_reply(comp["conv_id"], engine)
    except Exception as e:
        print(f"[wren] conversation store write failed ({e}) — "
              "the reply was delivered but not persisted")


def context_meter(win):
    summary_chars = int(win.get("summary_chars") or 0)
    return {"window_chars": int(win.get("chars") or 0),
            "window_budget_chars": int(win.get("budget_chars") or 0),
            "window_turns": len(win.get("messages") or []),
            "dropped_turns": int(win.get("dropped") or 0),
            "summary_present": summary_chars > 0,
            "summary_chars": summary_chars}


_DEFAULT_CONTEXT_COUNTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                            "context_counts.jsonl")
CONTEXT_COUNTS_PATH = None
CONTEXT_COUNTS_MAX_BYTES = 8 * 1024 * 1024


def _record_context_counts(kind, speaker, engine, counts, reason=None):
    try:
        import time as _time
        if not CONTEXT_COUNTS_PATH:
            return
        if os.path.exists(CONTEXT_COUNTS_PATH) and os.path.getsize(CONTEXT_COUNTS_PATH) > CONTEXT_COUNTS_MAX_BYTES:
            return
        line = {"at": _time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "speaker": speaker, "engine": engine}
        line.update({k: v for k, v in counts.items() if isinstance(v, (int, float))})
        if isinstance(reason, str) and re.fullmatch(r"[a-z0-9-]{1,40}", reason):
            line["reason"] = reason
        with open(CONTEXT_COUNTS_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
    except Exception:
        pass


def _result_meta(comp, room, engine):
    out = {
        "room": permissions.normalize_room(room),
        "engine": engine,
        "kernel": GATEWAY_VERSION,
        "sources": comp["sources"],
        "evidence": comp.get("evidence", []),
    }
    if comp["conv_id"]:
        out["conversation"] = comp["conv_id"]
        out["omitted_vault"] = comp["omitted_vault"]
        if comp.get("context"):
            out["context"] = comp["context"]
    return out


def _chat(scope, room, engine, messages,
         extra_context="", today=None, tools=None, conversation=None,
         speaker=None, evidence_events=None, client_turn_id=None, machine=None):
    ok, resolved = _speaker_gate(room, speaker, conversation)
    if not ok:
        return resolved
    last_user_msg = next((m.get("content") for m in reversed(messages or [])
                          if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
    if continuity.is_reanchor_request(last_user_msg):
        reanchor_res = continuity.execute_reanchor(conversation_id=conversation)
        return {
            "ok": True,
            "content": reanchor_res["content"],
            "room": permissions.normalize_room(room),
            "engine": engine,
            "kernel": GATEWAY_VERSION,
            "sources": [],
            "evidence": [],
            "diagnostics": reanchor_res["diagnostics"],
            **({"conversation": conversation} if conversation else {}),
        }

    steward = steward_stores.storage_steward(resolved)
    with steward_stores.steward_scope(steward):
        comp = _compose(scope, room, engine, messages, extra_context, today,
                        conversation, speaker=speaker,
                        evidence_events=evidence_events,
                        client_turn_id=client_turn_id, machine=machine)
        result, comp = _run_local_tool_loop(comp, engine, comp["convo"], tools, room, resolved)
        if not result.get("ok"):
            return result
        content = result.get("content") or ""
        if comp.get("speaker") == "wren":
            content, violations = provenance.guard_response(
                content, comp.get("evidence"))
            content, drift_violations = continuity.check_response_drift(
                content, evidence_events=comp.get("evidence"))
        else:
            violations, drift_violations = [], []
        _persist_reply(comp, engine, content)
        out = {"ok": True, "content": content, **_result_meta(comp, room, engine)}
        total_corrections = len(violations) + len(drift_violations)
        if total_corrections:
            out["integrity_corrections"] = total_corrections
            if drift_violations:
                out["drift_corrections"] = len(drift_violations)
        return out


def _chat_stream(scope, room, engine, messages,
                extra_context="", today=None, tools=None, conversation=None,
                speaker=None, evidence_events=None, client_turn_id=None, machine=None):
    ok, resolved = _speaker_gate(room, speaker, conversation)
    if not ok:
        yield {"error": resolved["reason"], "status": resolved["status"]}
        return
    steward = steward_stores.storage_steward(resolved)
    with steward_stores.steward_scope(steward):
        comp = _compose(scope, room, engine, messages, extra_context, today,
                        conversation, speaker=speaker,
                        evidence_events=evidence_events,
                        client_turn_id=client_turn_id, machine=machine)
        result, comp = _run_local_tool_loop(comp, engine, comp["convo"], tools, room, resolved)
        if not result.get("ok"):
            yield {"error": result.get("reason", "error"), "status": result.get("status", 500)}
            return
        content = result.get("content") or ""
        if comp.get("speaker") == "wren":
            content, violations = provenance.guard_response(content, comp.get("evidence"))
            content, drift_violations = continuity.check_response_drift(
                content, evidence_events=comp.get("evidence"))
        else:
            violations, drift_violations = [], []
        _persist_reply(comp, engine, content)
        chunk = 240
        for i in range(0, len(content), chunk):
            yield {"delta": content[i:i + chunk]}
        meta = {"done": True, **_result_meta(comp, room, engine)}
        if violations or drift_violations:
            meta["integrity_corrections"] = len(violations) + len(drift_violations)
        yield meta


def _begin_desktop_tool_turn(scope, room, engine, messages, tools,
                            extra_context="", today=None, conversation=None,
                            speaker=None, evidence_events=None,
                            client_turn_id=None, pictures=None, picture_words=True,
                            machine=None):
    ok, gate = _speaker_gate(room, speaker, conversation)
    if not ok:
        return gate
    notes = offer.withheld_notes(room, gate)
    section = toolsection.build_tool_section(tools)
    comp = _compose(scope, room, engine, messages, extra_context, today,
                    conversation, speaker=speaker,
                    evidence_events=evidence_events,
                    client_turn_id=client_turn_id, tool_notes=notes,
                    tool_section=section, pictures=pictures, picture_words=picture_words,
                    machine=machine)
    pic = comp.get("pictures")
    to_send, gone = pictures_mod.attach(comp["convo"], pic)
    if gone:
        return {"ok": False, "reason": gone, "status": 409}
    result = provider.complete(comp["scope"], engine, to_send, tools=tools,
                               timeout=60)
    if not result.get("ok"):
        if pic:
            pictures_mod.drop(pic["key"])
        return result
    calls = result.get("tool_calls") or []
    if not calls and pic:
        pictures_mod.drop(pic["key"])
    if calls:
        assistant = {"role": "assistant", "content": result.get("content"),
                     "tool_calls": calls}
        state = {
            "messages": comp["convo"] + [assistant],
            "comp": {**{k: comp.get(k) for k in
                        ("scope", "rid", "speaker", "sources", "evidence",
                         "turn_verification_events", "conv_id", "omitted_vault", "context")},
                     **({"pictures": pic} if pic else {})},
            "engine": engine,
            "room": room,
        }
        return {"ok": True, "kind": "tool_calls", "tool_calls": calls,
                "provider_state": state}
    if comp.get("speaker") == "wren":
        content, violations = provenance.guard_response(
            result.get("content") or "", comp.get("evidence"))
        content, drift_violations = continuity.check_response_drift(
            content, evidence_events=comp.get("evidence"))
    else:
        content, violations = result.get("content") or "", []
        drift_violations = []
    _persist_reply(comp, engine, content)
    out = {"ok": True, "kind": "final", "content": content,
           **_result_meta(comp, room, engine)}
    total_corrections = len(violations) + len(drift_violations)
    if total_corrections:
        out["integrity_corrections"] = total_corrections
        if drift_violations:
            out["drift_corrections"] = len(drift_violations)
    return out


def _continue_desktop_tool_turn(provider_state, tools, tool_results):
    if not isinstance(provider_state, dict):
        return {"ok": False, "reason": "invalid-tool-state", "status": 500}
    messages = list(provider_state.get("messages") or [])
    from wren.senses import sanitize
    call_by_id = {}
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            call_by_id = {c.get("id"): c for c in message.get("tool_calls") or []}
            break
    new_evidence = []
    for item in tool_results or []:
        raw_result = item.get("result") or {}
        call = call_by_id.get(item.get("tool_call_id")) or {}
        function = call.get("function") or {}
        new_evidence.append(provenance.tool_result(
            function.get("name") or "desktop_tool",
            json.dumps(raw_result, ensure_ascii=False, sort_keys=True),
            target=raw_result.get("target"),
            successful=raw_result.get("status") == "succeeded",
            authorized=True, timestamp=raw_result.get("finished_at")))
        messages.append({
            "role": "tool",
            "tool_call_id": item.get("tool_call_id"),
            "content": sanitize.Sanitizer.wrap_json_data(
                raw_result, label="local tool result", max_len=200_000),
        })
    engine = provider_state.get("engine")
    comp = provider_state.get("comp") or {}
    comp.setdefault("evidence", []).extend(new_evidence)
    comp.setdefault("turn_verification_events", []).extend(
        ev for ev in new_evidence
        if ev.get("source_type") == "tool_result" and ev.get("verified_by_wren") is True
    )
    result = provider.complete(comp["scope"], engine, messages, tools=tools,
                               timeout=60)
    if not result.get("ok"):
        return result
    calls = result.get("tool_calls") or []
    if calls:
        assistant = {"role": "assistant", "content": result.get("content"),
                     "tool_calls": calls}
        state = {
            "messages": messages + [assistant],
            "comp": comp,
            "engine": engine,
            "room": provider_state.get("room"),
        }
        return {"ok": True, "kind": "tool_calls", "tool_calls": calls,
                "provider_state": state}
    if comp.get("speaker") == "wren":
        content, violations = provenance.guard_response(
            result.get("content") or "", comp.get("evidence"))
        content, drift_violations = continuity.check_response_drift(
            content, evidence_events=comp.get("evidence"))
    else:
        content, violations = result.get("content") or "", []
        drift_violations = []
    _persist_reply(comp, engine, content)
    out = {"ok": True, "kind": "final", "content": content,
           **_result_meta(comp, provider_state.get("room"), engine)}
    total_corrections = len(violations) + len(drift_violations)
    if total_corrections:
        out["integrity_corrections"] = total_corrections
        if drift_violations:
            out["drift_corrections"] = len(drift_violations)
    return out


def _run_local_tool_loop(comp, engine, messages, tools, room, speaker, max_steps=16):
    """Execute tool calls locally (kernel + memory tools) and keep calling the
    model until it produces a final answer. Returns (result, comp)."""
    from wren.mind import memory_tools
    from wren.tools import kernel_tools, fortress_tools

    convo = list(messages or [])
    for _ in range(max_steps):
        result = provider.complete(comp["scope"], engine, convo, tools=tools, timeout=120)
        if not result.get("ok"):
            return result, comp
        calls = result.get("tool_calls") or []
        if not calls:
            return {"ok": True, "kind": "final", "content": result.get("content") or ""}, comp

        convo.append({"role": "assistant", "content": result.get("content") or "",
                      "tool_calls": calls})
        for call in calls:
            if not isinstance(call, dict) or call.get("type") != "function":
                continue
            cid = str(call.get("id") or "")
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except Exception:
                    args = {}
            if name in memory_tools.TOOL_NAMES:
                res = memory_tools.execute_tool_call(
                    speaker=speaker, room=room, engine=engine,
                    tool_call_id=cid, tool_name=name, tool_arguments=args)
            elif name in kernel_tools.TOOL_NAMES:
                res = kernel_tools.execute_tool_call(
                    speaker=speaker, room=room, engine=engine,
                    tool_call_id=cid, tool_name=name, tool_arguments=args)
            elif name in fortress_tools.TOOL_NAMES:
                res = fortress_tools.execute_tool_call(
                    speaker=speaker, room=room, engine=engine,
                    tool_call_id=cid, tool_name=name, tool_arguments=args)
            else:
                res = {"status": "failed", "error": "unknown-tool", "data": None}
            # Record the tool-execution trace so completion claims can be verified.
            try:
                target = ""
                data = res.get("data") if isinstance(res, dict) else None
                if isinstance(data, dict):
                    out = data.get("output") if isinstance(data.get("output"), dict) else data
                    target = str(out.get("path") or out.get("url") or "")
                comp.setdefault("evidence", []).append(provenance.tool_result(
                    name, json.dumps(res, ensure_ascii=False, sort_keys=True),
                    target=target, successful=res.get("status") == "succeeded",
                    authorized=True))
            except Exception:
                pass
            convo.append({"role": "tool", "tool_call_id": cid,
                          "content": json.dumps(res, ensure_ascii=False)})
    return {"ok": False, "reason": "tool-loop-limit", "status": 409}, comp


# --- PUBLIC BRIDGE (the names server.py calls) ---

chat = _chat
chat_stream = _chat_stream
begin_desktop_tool_turn = _begin_desktop_tool_turn
continue_desktop_tool_turn = _continue_desktop_tool_turn


def _store_steward(room, speaker):
    """Resolve the store-owning steward for a room + optional speaker."""
    sid = resolve_speaker(room, speaker)
    return steward_stores.storage_steward(sid)


def _store_refusal(e):
    """The JSON refusal for an invalid/unavailable steward store."""
    status = 503 if isinstance(e, steward_stores.StewardStoreError) else 400
    return {"reason": str(e), "status": status}
