"""Everything the Wren kernel reads from Fortress's config, and nothing else.

Fortress's config.py is 1040 lines of SMTP settings, colour accents, brand prose
and vault loaders. The kernel imports a handful of names from it. This file is
those names, carried across verbatim, plus the API keys read from the
environment instead of from a file on her desk.

The model registry below is copied byte-for-byte, comments included: which
engines exist is a decision with evaluation evidence behind it, not a list to
retype from memory.

Regenerate rather than hand-edit if Fortress's registry changes.
"""

import os

# Read from the environment where this runs. Never committed, and never copied
# out of the source tree.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

OLLAMA_URL          = "http://127.0.0.1:11434/api/chat"

GROQ_MODEL_MAP = {
    "Groq: Llama 3.1 8B (Instant)":  {"model": "llama-3.1-8b-instant",    "url": "https://api.groq.com/openai/v1/chat/completions"},
    "Groq: Llama 3.3 70B (Versatile)": {"model": "llama-3.3-70b-versatile", "url": "https://api.groq.com/openai/v1/chat/completions"},
}

CLOUD_MODEL_MAP = {
    # Gemma routed through Ollama Cloud instead — see MODEL_MAP. OpenRouter Gemma deprecated due to upstream rate limits.
    "GLM-5.1 (via OpenRouter)":       {"model": "z-ai/glm-5.1",           "url": "https://openrouter.ai/api/v1/chat/completions"},
    # deepseek/deepseek-coder was REMOVED from OpenRouter's catalog (verified
    # against the live model list, 2026-08-07) — every request answered
    # "upstream". V4 Flash is its current successor: fast, cheap, coder-capable.
    "DeepSeek V4 Flash (via OpenRouter)": {"model": "deepseek/deepseek-v4-flash", "url": "https://openrouter.ai/api/v1/chat/completions"},
    "Qwen Coder (via OpenRouter)":    {"model": "qwen/qwen-2.5-coder-32b-instruct", "url": "https://openrouter.ai/api/v1/chat/completions"},
    # "vision": True below = the old api_chat allowlist set, now carried as
    # registry metadata (2026-08-07). GLM/DeepSeek/Qwen stay unmarked until
    # someone verifies image input against the live model — never assume.
    "GPT-4o (via OpenRouter)":        {"model": "openai/gpt-4o",          "url": "https://openrouter.ai/api/v1/chat/completions", "vision": True},
    "GPT-4o Mini (via OpenRouter)":   {"model": "openai/gpt-4o-mini",     "url": "https://openrouter.ai/api/v1/chat/completions", "vision": True},
    "Claude Sonnet 4.5 (via OpenRouter)":  {"model": "anthropic/claude-sonnet-4.5", "url": "https://openrouter.ai/api/v1/chat/completions", "vision": True},
    "Claude Opus 4.5 (via OpenRouter)":    {"model": "anthropic/claude-opus-4.5",   "url": "https://openrouter.ai/api/v1/chat/completions", "vision": True},
    "Claude Opus 4.7 (via OpenRouter)":    {"model": "anthropic/claude-opus-4.7",   "url": "https://openrouter.ai/api/v1/chat/completions", "vision": True},
}

MODEL_MAP = {
    # Label says 14B because it IS the 14b tag — the old "(7B)" label lied.
    # Also installed locally but deliberately unregistered (Chunk A audit,
    # 2026-08-07): gpt-oss:20b, nomic-embed-text. Adding an engine is a
    # product decision that needs evaluation evidence (doc 16), not a default.
    "Local: Qwen2.5 Coder (14B)":      {"model": "qwen2.5-coder:14b",     "vibe": "The Toolsmith (14B)", "raw": True},
    # vision: both Gemmas VERIFIED live 2026-08-07 (fixture screenshot via
    # Ollama's message.images; both described it correctly). Qwen coder is
    # text-only — no flag.
    "Local: Gemma 4 (12B)":           {"model": "gemma4:12b",            "vibe": "The Diplomat", "raw": True, "vision": True},
    # Registered on Chrissy's explicit ask, 2026-08-17. Evidence: head-to-head
    # vs gpt-oss:20b (3-prompt bench, same machine) — clearly better agent
    # tool-planning, equal reasoning, comparable speed (33-46 tok/s; MoE, 3B
    # active of 30B). NOT battery-evaluated; her pick, recorded honestly.
    # No vision flag: image input unverified against the live model — never
    # assume. Thinking model: replies carry hidden reasoning tokens, so
    # capped num_predict would return empty content — _ollama() sets no cap.
    "Local: Nemotron 3.5 Lightning (30B)": {"model": "nemotron-3.5-lightning", "vibe": "The Dispatcher", "raw": True},
    # Ollama cloud-backed (requires `ollama signin`) — routed via local Ollama API
    "Ollama Cloud: Gemma 4 (31B)":    {"model": "gemma4:31b-cloud",      "vibe": "The Heavyweight", "raw": True, "vision": True},
    # Chrissy's pick for Ember (2026-10-18). Engine entry ONLY: no steward is
    # routed to it yet. Ollama names this tag ":cloud" (no "-cloud"), so
    # provider.is_local_engine() checks both spellings; it computes on Ollama's
    # servers and is NOT vault-approved. No vision flag: image input unverified.
    "Ollama Cloud: GLM 5.3 Flash":    {"model": "glm-5.3-flash:cloud",   "vibe": "The Quickhand", "raw": True},
}

# ─────────────────────────────────────────────────────────────────────────────
# DIRECT OPENAI (2026-07-30)
#
# Fortress previously reached every OpenAI model through OpenRouter. Going
# direct removes the reseller margin.
#
# PRICING (corrected 2026-08-08 — the 2026-07-30 "$0.20/$1.20" figure that
# used to live here is STALE; per Chrissy from OpenAI's current official
# price list): GPT-5.6 Luna $1/M input, $6/M output · Terra $2.50/$15 ·
# Sol $5/$30. Luna is still the cheapest tier of the family. Doc-16 law:
# prices get re-verified against the provider, with source and timestamp
# recorded, immediately before any paid evaluation run — never assumed
# from this comment.
#
# ⚠️ The model id must be 'gpt-5.6-luna'. The bare 'gpt-5.6' alias routes to
# Sol, the most expensive tier in the family — a silent and costly mistake.
#
# OPENAI_API_KEY already exists in .env; DALL·E has been using it.
# ─────────────────────────────────────────────────────────────────────────────
OPENAI_CHAT_URL = "https://api.openai.com/v1/responses"

OPENAI_MODEL_MAP = {
    "GPT-5.6 Wren (OpenAI)": {
        "model": "gpt-5.6-luna",
        "url": OPENAI_CHAT_URL,
        "vibe": "The Swift",
        "notes": "fast + cheapest tier; 1.05M context",
        # Capability metadata (doc 16: the registry is the single source of
        # truth — capability decisions live HERE, never as name checks in
        # handlers).
        "vision": True,   # official multimodal input (image reaches it via
                          # OpenAI-style content parts; verified live 2026-08-07)
        # OpenAI 400s any tool-bearing /v1/chat/completions call for
        # gpt-5.6-luna unless reasoning_effort is 'none' ("To use function
        # tools, use /v1/responses or set reasoning_effort to 'none'" —
        # captured live 2026-08-07, reproduced verbatim in suite R7). Pass 1
        # (2026-08-08) settled the scope question: Terra and Sol refused
        # every tool-bearing Ask call the same way (R13's sanitized refusal
        # evidence), so this is a FAMILY-wide chat/completions constraint,
        # not a Luna quirk — every gpt-5.6 entry carries the same tool-lane
        # pin. Still not an OpenAI-wide rule. The Responses-API migration
        # is a later doc-16 chunk.
        # 'none' was a chat/completions-only workaround; on /v1/responses tools
        # and reasoning coexist. High, her call 2026-10-11.
        "tools_params": {"reasoning_effort": "high"},
    },
    # Visual-seat default (Chunk C routing decision, Chrissy 2026-08-14).
    # Earned by Pass 2 T11 (2026-08-10, reports 20260810-16*): named the
    # render-only badge/title collision from the screenshot at the family's
    # cheapest passing tier. Family tool-lane pin applies (same law as Luna).
    "GPT-5.6 Terra (OpenAI)": {
        "model": "gpt-5.6-terra",
        "url": OPENAI_CHAT_URL,
        "vibe": "The Sighted",
        "notes": "mid tier; Visual seat — proven screenshot reasoning",
        "vision": True,
        # High, her call 2026-10-11 ('none' was a chat/completions workaround).
        "tools_params": {"reasoning_effort": "high"},
    },
    # Visual-seat FALLBACK ONLY (her ruling 2026-08-14: "terra-low
    # provisional with sol-med fallback"). Sol is the family's premium tier
    # ($5/$30) — it exists in the picker so the fallback names a real
    # engine, but no seat defaults to it and nothing routes here silently
    # (doc 16: no silent fallback). Pass 2 T11 evidence: Sol-medium 2/3,
    # cleanest diagnosis of the badge collision. Family tool-lane pin
    # applies.
    "GPT-5.6 Sol (OpenAI)": {
        "model": "gpt-5.6-sol",
        "url": OPENAI_CHAT_URL,
        "vibe": "The Beacon",
        "notes": "premium tier; Visual-seat fallback only — never a default",
        "vision": True,
        # 'none' was a chat/completions-only workaround; on /v1/responses tools
        # and reasoning coexist. Low, her call 2026-10-11.
        "tools_params": {"reasoning_effort": "low"},
        "extra_params": {
            "max_output_tokens": 1500,
            "instructions": "Be concise. Do not explain your code unless asked."
        }
    },
}

# ─── FORGE SEATS (doc 16, Chunk C — the routing record) ──────────────────────
# The evidence-based routing decisions, made by Chrissy 2026-08-14 from
# Pass 1 (2026-08-08, full 15-task battery) + targeted Pass 2 (2026-08-10).
# This is the RECORD the mode-first UI (Chunk D) will read — no routing
# behavior changes here. Laws: her explicit pick always overrides (unless
# privacy forbids), no silent fallback, Private NEVER falls back to cloud.
# One run never promotes; every seat below rests on the two-pass evidence.
FORGE_SEATS = {
    "quick": {
        "engine": "DeepSeek V4 Flash (via OpenRouter)",
        "fallback": "GPT-5.6 Wren (OpenAI)",
        "earned": "best of a weak field — Pass 1 Quick 53% vs Luna 47%",
        "weaknesses": "PROVISIONAL: whole field weak; Luna fallback is "
                      "fast but never investigates (0 agent steps)",
        "cost_class": "budget",
        "reeval": "2026-11-01",
    },
    "build": {
        "engine": "Claude Sonnet 4.5 (via OpenRouter)",
        "fallback": "DeepSeek V4 Flash (via OpenRouter)",
        "earned": "Pass 1 Build 85%, no errors",
        "weaknesses": "Terra 71% had 3 errors pre-fix-C; Build lanes not "
                      "rerun since — challenger candidate",
        "cost_class": "standard",
        "reeval": "2026-11-01",
    },
    "architect": {
        "engine": "Claude Opus 4.7 (via OpenRouter)",
        "fallback": "Claude Sonnet 4.5 (via OpenRouter)",
        "earned": "Pass 1 Architect 91%, investigates most (9-10 steps)",
        "weaknesses": "Sol-medium 17/19 on the Pass-2 subset is an open "
                      "challenge — full battery pending her word",
        "cost_class": "premium",
        "reeval": "2026-11-01",
    },
    "visual": {
        "engine": "GPT-5.6 Terra (OpenAI)",
        # Her ruling 2026-08-14: "seat terra-low provisional with sol-med
        # fallback". The reasoning fields record the EVIDENCED tiers (Pass 2
        # ran Terra at low, Sol at medium) — Chunk D wires them into
        # requests; until then tool-free production calls ride the provider
        # default and tool calls ride the family pin ('none'). Recorded so
        # the gap is honest, not hidden.
        "reasoning": "low",
        "fallback": "GPT-5.6 Sol (OpenAI)",
        "fallback_reasoning": "medium",
        "earned": "CONFIRMED by Chrissy 2026-08-14 after the first smoke "
                  "run: named all three render-only defects (T11 badge "
                  "collision, T16 nav wrap, T17 banner overlap) and dodged "
                  "every decoy — seeing 6/6 across four task-runs at the "
                  "family's cheapest passing tier (low)",
        "weaknesses": "surgical-fix quality: bulldozes decoy rules while "
                      "fixing (as every model did in Pass 2 — nobody "
                      "scored 3/3 on fix checks); Sol-medium diagnosed "
                      "cleaner in Pass 2",
        "cost_class": "standard",
        "reeval": "2026-11-01",
    },
    "private": {
        "engine": "Local: Gemma 4 (12B)",
        # Fallback swapped Qwen2.5-coder -> Nemotron on Chrissy's explicit
        # ask 2026-08-17 ("get nemotron a seat"). LOCAL ONLY — the
        # never-cloud law holds: nemotron-3.5-lightning runs on this machine.
        "fallback": "Local: Nemotron 3.5 Lightning (30B)",
        "earned": "engine: Pass 1 Private 73% vs Qwen 63%; fallback: her "
                  "pick 2026-08-17 + bench vs gpt-oss:20b (best agent "
                  "tool-planning of the local field) — battery pending",
        "weaknesses": "failed T11 (0/3, fell for the decoy) — private "
                      "VISUAL work has no qualified model; Nemotron "
                      "fallback is bench-evidenced only, not "
                      "battery-evaluated",
        "cost_class": "free-local",
        "reeval": "2026-11-01",
    },
}

# The engine used when a caller sends none. Must exist in a map — the previous
# default ('Local: Gemma 2 (9B)') did not, so every such call returned an error.
DEFAULT_ENGINE = "GPT-5.6 Sol (OpenAI)"

# ── which engines may see her private material ──────────────────────────────
# The vault used to mean "must never leave this machine". It no longer does.
# It means PRIVATE TO CHRISSY -- available inside Wren's own context, and not
# automatically shareable into the shared spaces Architecture of Us will add.
#
# So the wall stops asking "does this run locally?" and starts asking "did she
# approve this engine for her private material?". Local engines qualify by
# running in her house. Everything else has to be named here, one at a time.
#
# Deliberately NOT every cloud engine in the registry. Adding one is a decision
# about who gets to read her private conversations, and it should look like one.
VAULT_APPROVED_ENGINES = frozenset({
    # Moved with DEFAULT_ENGINE 2026-08-27, her call. Approving an engine for
    # her private material is a decision about who reads her private
    # conversations -- this one moved it from Anthropic to OpenAI.
    "GPT-5.6 Sol (OpenAI)",
    # Added 2026-09-06, her call: explicitly-marked private context must stay
    # continuous when she switches between Sol and Luna, not silently vanish.
    # ("Luna" is the tier name; the registry key for it is "GPT-5.6 Wren".)
    "GPT-5.6 Wren (OpenAI)",
})

# ── Reflection (Wren remembers, docs/intelligence/03) ────────────────────────
# How long a conversation must be QUIET before Wren reviews it for anything
# worth keeping. Reflection never runs inside a reply -- it waits for the
# conversation to settle, so nothing it does can slow her down.
# 10 -> 120 on Chrissy's ask: allow conversations to breathe naturally (2 hours)
# before declaring quiet and running reflection.
REFLECT_QUIET_MINUTES = 120

# ── Tool rollout, Wave 1 (Chrissy, 2026-10-18) ───────────────────────────────
# ONE switch for the fifteen registry-derived read-only tools (wren/offer.py).
# OFF by default; with it off the offered-tools list, the argument checks and
# the result checks are exactly what they were. Set the environment variable
# OFFER_WAVE1=1 (or true/yes/on) to turn it on -- and only once the desktop
# executor that handles signed grants implements these tools.
OFFER_WAVE1 = os.environ.get("OFFER_WAVE1", "").strip().lower() in ("1", "true", "yes", "on")
# WHICH companions get the Wave 1 tools once OFFER_WAVE1 is on (Chrissy, 2026-10-19: "Wave 1 gets switched
# on Wren only"). OFFER_WAVE1_COMPANIONS is a comma-separated list of wren, ember, maeve, rowan. Not set =
# Wren only. Set but empty = nobody. Names the kernel does not know are ignored. It has no effect while
# OFFER_WAVE1 is off.
_w1_raw = os.environ.get("OFFER_WAVE1_COMPANIONS")
OFFER_WAVE1_COMPANIONS = frozenset(
    n.strip().lower() for n in (["wren"] if _w1_raw is None else _w1_raw.split(","))
    if n.strip().lower() in ("wren", "ember", "maeve", "rowan"))
# WHICH companions are offered her own-memory tools, search_my_memories and recall_turns (Job 21, 2026-10-19:
# "offered to Wren only for now"). Comma-separated wren, ember, maeve, rowan. Not set = Wren only. Set but
# empty = nobody (the off switch). Each companion who is offered them reads ONLY her own store.
_mt_raw = os.environ.get("MEMORY_TOOLS_COMPANIONS")
MEMORY_TOOLS_COMPANIONS = frozenset(
    n.strip().lower() for n in (["wren"] if _mt_raw is None else _mt_raw.split(","))
    if n.strip().lower() in ("wren", "ember", "maeve", "rowan"))
# ── The vault wall switch (Chrissy, 2026-10-18) ──────────────────────────────
# "All companions see everything on any engine." While this is on (the default)
# provider.is_vault_approved() approves every REGISTERED engine, so vault-flagged
# turns and the Core room reach any engine. Set VAULT_WALL_OPEN=0 to bring back
# the named-engine wall (VAULT_APPROVED_ENGINES above) with no code change.
# This switch is NOT what keeps credentials out of prompts: wren/credfilter.py
# does that, for every engine, whatever this says.
VAULT_WALL_OPEN = os.environ.get("VAULT_WALL_OPEN", "1").strip().lower() not in ("0", "false", "no", "off")