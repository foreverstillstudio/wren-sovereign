# ============================================================
# WREN KERNEL - what goes to the model, trimmed (Job 32)
# ------------------------------------------------------------
# Two pure functions that decide what a prompt carries. Neither writes anything and neither changes what it is
# given: they return NEW lists, so the stored conversation and the saved tool-turn state are exactly as they were.
#
#   trim_tool_results  the tool results inside ONE turn's working messages. The newest results stay whole; an
#                      older one is sent as a single line (tool name, arguments, size, "run it again to see it").
#   trim_history       the earlier messages of the recent-history window. A message over MESSAGE_CAP_CHARS is sent
#                      as a single line that says where the full text is kept - except the live message (the one
#                      being answered) and the newest few earlier turns, which always ride whole.
#
# Tool results are NOT part of the stored conversation (the store holds the words only); they exist only in the
# working messages of the turn that asked for them, which is why trim_tool_results is applied there.
# ============================================================
import json
import os
import re

DEFAULT_TOOL_RESULTS_KEPT = 2
DEFAULT_MESSAGE_CAP_CHARS = 3000
DEFAULT_RECENT_TURNS_KEPT = 2
ARGUMENT_CHARS_IN_STUB = 160


def _int_from_environment(name, default, minimum):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value >= minimum else default


# One named setting each; the environment can override (read once at import, after the .env is loaded).
TOOL_RESULTS_KEPT = _int_from_environment("WREN_TOOL_RESULTS_KEPT", DEFAULT_TOOL_RESULTS_KEPT, 1)
MESSAGE_CAP_CHARS = _int_from_environment("WREN_MESSAGE_CAP_CHARS", DEFAULT_MESSAGE_CAP_CHARS, 500)
RECENT_TURNS_KEPT = _int_from_environment("WREN_RECENT_TURNS_KEPT", DEFAULT_RECENT_TURNS_KEPT, 0)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _text_len(content):
    """Characters of text in a message's content (a string, or a list of parts)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                total += len(str(part.get("text") or ""))
            elif isinstance(part, str):
                total += len(part)
        return total
    return 0


def _one_line(text, limit):
    text = _CONTROL.sub(" ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _calls_by_id(messages):
    out = {}
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id"):
                    out[call["id"]] = call
    return out


def tool_result_stub(name, arguments, chars):
    """The one line that stands in for an old tool result. Names the tool, shows its arguments (cut short, one
    line), says how big the result was, and says how to see it again."""
    if isinstance(arguments, str):
        shown = arguments
    else:
        try:
            shown = json.dumps(arguments, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            shown = ""
    return ("[Earlier tool result left out of this prompt: %s %s returned %d characters. "
            "Run it again to see it.]" % (_one_line(name, 80) or "a tool", _one_line(shown, ARGUMENT_CHARS_IN_STUB)
                                          or "{}", chars))


def trim_tool_results(messages, keep=None):
    """Return (new_messages, stats). The newest `keep` tool results stay whole, and so does every result of the
    newest round (a round that asked for several things at once is never cut in half). Every older tool result is
    replaced by its one-line stub; the message itself, and its tool_call_id, stay in place.

    stats = {"tool_results": n, "kept": n, "stubbed": n, "kept_chars": n, "stubbed_chars": n (what the stubs
    replaced), "saved_chars": n (what the prompt no longer carries)}. Counts only."""
    keep = TOOL_RESULTS_KEPT if keep is None else max(int(keep), 1)
    messages = list(messages or [])
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    last_round_start = 0
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            last_round_start = i
    protected = set(tool_idx[-keep:]) | {i for i in tool_idx if i > last_round_start}
    calls = _calls_by_id(messages)
    out, stats = [], {"tool_results": len(tool_idx), "kept": 0, "stubbed": 0, "kept_chars": 0,
                      "stubbed_chars": 0, "saved_chars": 0}
    for i, m in enumerate(messages):
        if m.get("role") != "tool":
            out.append(m)
            continue
        size = _text_len(m.get("content"))
        if i in protected:
            stats["kept"] += 1
            stats["kept_chars"] += size
            out.append(m)
            continue
        function = (calls.get(m.get("tool_call_id")) or {}).get("function") or {}
        stub = tool_result_stub(function.get("name"), function.get("arguments"), size)
        out.append({**m, "content": stub})
        stats["stubbed"] += 1
        stats["stubbed_chars"] += size
        stats["saved_chars"] += max(size - len(stub), 0)
    return out, stats


def history_stub(role, chars, conversation, turn, can_recall):
    """The one line that stands in for a long earlier message."""
    who = "Chrissy" if role == "user" else "you" if role == "assistant" else str(role or "someone")
    where = ("It is kept in full as turn %d of conversation %s; read it back with recall_turns if you need it."
             % (turn, conversation) if can_recall and conversation and turn is not None else
             "It is kept in full in the stored conversation; ask for it again if you need it.")
    return "[Earlier message from %s left out of this prompt: %d characters. %s]" % (who, chars, where)


def trim_history(window_messages, indexes=None, conversation=None, can_recall=False, cap=None,
                 recent_kept=None, live_last=True):
    """Return (new_messages, stats). `window_messages` are the {"role", "content"} messages of the recent-history
    window, oldest first; `indexes` their turn numbers in the stored conversation (same length, or None).

    A message with more than `cap` characters is replaced by its stub, EXCEPT:
      - the last message when `live_last` (the live message being answered), and
      - the newest `recent_kept` messages before it (the latest exchange stays whole).
    Messages whose content is not plain text (a list of parts, i.e. a picture message) are never cut.

    stats = {"messages": n, "cut": n, "cut_chars": n, "saved_chars": n}. Counts only."""
    cap = MESSAGE_CAP_CHARS if cap is None else max(int(cap), 1)
    recent_kept = RECENT_TURNS_KEPT if recent_kept is None else max(int(recent_kept), 0)
    window_messages = list(window_messages or [])
    n = len(window_messages)
    exempt_from = n - (1 if live_last else 0) - recent_kept          # indices >= this stay whole
    out = []
    stats = {"messages": n, "cut": 0, "cut_chars": 0, "saved_chars": 0}
    for i, m in enumerate(window_messages):
        content = m.get("content")
        if i >= exempt_from or not isinstance(content, str) or len(content) <= cap:
            out.append(m)
            continue
        turn = indexes[i] if indexes is not None and i < len(indexes) else None
        stub = history_stub(m.get("role"), len(content), conversation, turn, can_recall)
        out.append({**m, "content": stub})
        stats["cut"] += 1
        stats["cut_chars"] += len(content)
        stats["saved_chars"] += max(len(content) - len(stub), 0)
    return out, stats
