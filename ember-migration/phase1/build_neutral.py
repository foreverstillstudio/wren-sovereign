#!/usr/bin/env python3
"""Phase 1 build: copy the kernel implementation into an identity-neutral tree.

Copies .py implementation only (never souls, profiles, prompts, stores, logs,
credentials). Applies an explicit, listed set of neutralizations, then writes a
manifest with the pre- and post-change hash of every file.

  python build_neutral.py --src C:\foreverstill\systems\wren_sovereign --dst C:\foreverstill\systems\ember_sovereign\sovereign_core\kernel
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import time

SKIP_DIRS = {"__pycache__", ".git", "archive", "_quarantine", "data", "ember-migration"}
TOP_FILES = ["server.py", "fortress_store.py", "calendar_store.py"]
# Shared implementation data the kernel loads at import. Identity-neutral: a tool
# catalog and its argument schemas — no persona, no sister, no credential.
DATA_FILES = ["wren/tools/tools.registry.json", "wren/tools/verb_schemas.v1.json"]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def patch(text, old, new, note, applied, rel):
    if old not in text:
        raise SystemExit("PATCH MISS in %s: %s" % (rel, note))
    applied.append({"file": rel, "patch": note})
    return text.replace(old, new, 1)


def patch_re(text, pattern, new, note, applied, rel):
    out, n = re.subn(pattern, new, text, count=1)
    if n != 1:
        raise SystemExit("PATCH MISS in %s: %s" % (rel, note))
    applied.append({"file": rel, "patch": note})
    return out


DEFAULT_DST = r"C:\foreverstill\systems\ember_sovereign\sovereign_core\kernel"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", default=DEFAULT_DST)
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()
    src, dst = args.src, args.dst
    if os.path.exists(dst) and os.listdir(dst):
        raise SystemExit("refusing: destination is not empty: %s" % dst)

    files = []
    for name in TOP_FILES:
        p = os.path.join(src, name)
        if os.path.exists(p):
            files.append(name)
    for name in DATA_FILES:
        p = os.path.join(src, name)
        if os.path.exists(p):
            files.append(name)
    for base, dirs, names in os.walk(os.path.join(src, "wren")):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in sorted(names):
            if n.endswith(".py"):
                files.append(os.path.relpath(os.path.join(base, n), src))

    entries, applied = [], []
    for rel in files:
        s = os.path.join(src, rel)
        d = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        before = sha(s)
        text = open(s, encoding="utf-8").read()
        relposix = rel.replace("\\", "/")

        if relposix == "wren/mind/soul.py":
            text = patch(text,
                         '_DATA_DIR = os.path.dirname(os.path.abspath(__file__))\n'
                         '_DATA = os.path.join(_DATA_DIR, "soul.json")',
                         '_DATA_DIR = os.environ.get("SOUL_DIR", "").rstrip("\\\\/") or '
                         'os.path.dirname(os.path.abspath(__file__))\n'
                         '_DATA = os.path.join(_DATA_DIR, os.environ.get("SOUL_FILE", "soul.json"))',
                         "soul dir/file come from SOUL_DIR/SOUL_FILE, not __file__", applied, rel)
            text = patch_re(text, r"(?ms)^_SOUL_PINS = \{.*?^\}",
                            'try:\n    _SOUL_PINS = json.loads(os.environ.get("SOUL_PINS_JSON", "{}"))\n'
                            'except Exception:\n    _SOUL_PINS = {}',
                            "soul pins come from SOUL_PINS_JSON, not a hardcoded sister map", applied, rel)

        elif relposix == "wren/system/stewards.py":
            text = patch(text, "from typing import (",
                         "import json\nimport os\n\nfrom typing import (",
                         "roster becomes data", applied, rel)
            text = patch_re(text, r"(?ms)^STEWARDS: Final = MappingProxyType\(\{.*?^\}\)",
                            'try:\n    _ROSTER = json.loads(os.environ.get("STEWARDS_JSON", "{}"))\n'
                            'except Exception:\n    _ROSTER = {}\n'
                            'STEWARDS: Final = MappingProxyType(_ROSTER)',
                            "steward roster comes from STEWARDS_JSON, not a hardcoded list", applied, rel)

        elif relposix == "wren/system/steward_stores.py":
            text = patch(text, "import contextlib\nimport contextvars\nimport os\nimport threading",
                         "import contextlib\nimport contextvars\nimport json\nimport os\nimport threading",
                         "json import", applied, rel)
            text = patch(text, 'STORE_STEWARDS: Final = ("wren", "ember", "maeve", "rowan")',
                         'STORE_STEWARDS: Final = tuple(json.loads(os.environ.get("STORE_STEWARDS_JSON", "[]")))',
                         "store stewards come from STORE_STEWARDS_JSON", applied, rel)
            text = patch_re(text, r"(?ms)^STEWARD_CONFIGS: Final = MappingProxyType\(\{.*?^\}\)",
                            'STEWARD_CONFIGS: Final = MappingProxyType('
                            'json.loads(os.environ.get("STEWARD_KEY_ENVS_JSON", "{}")))',
                            "key env names come from STEWARD_KEY_ENVS_JSON", applied, rel)
            text = patch(text, 'GUEST_ROOM_KEEPERS: Final = MappingProxyType({"vale": "wren"})',
                         'GUEST_ROOM_KEEPERS: Final = MappingProxyType('
                         'json.loads(os.environ.get("GUEST_KEEPERS_JSON", "{}")))',
                         "guest keepers come from GUEST_KEEPERS_JSON", applied, rel)
            text = patch(text,
                         '        steward = steward or StewardshipContext.current()\n'
                         '        if steward == "wren":\n            return base_path',
                         '        steward = steward or StewardshipContext.current()\n'
                         '        if steward == os.environ.get("HOME_STEWARD", "wren"):\n            return base_path',
                         "the home steward owns the root; no stewards/<name> nesting", applied, rel)

        elif relposix == "wren/core/gateway.py":
            text = patch(text,
                         '_PROFILE_PATH = os.path.join(\n'
                         '    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),\n'
                         '    "wren_profile.md")',
                         '_PROFILE_PATH = os.environ.get("PROFILE_PATH", "")',
                         "profile path from PROFILE_PATH, default none", applied, rel)
            text = patch(text,
                         '_ABOUT_PATH = os.path.join(\n'
                         '    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),\n'
                         '    "about_chrissy.md")',
                         '_ABOUT_PATH = os.environ.get("ABOUT_PATH", "")',
                         "about path from ABOUT_PATH, default none", applied, rel)


        elif relposix == "server.py":
            text = patch(text,
                         '"servable": provider.servable("gemma4:31b-cloud")})',
                         '"servable": provider.servable(provider.MODEL_MAP[DEFAULT_ENGINE]["model"])})',
                         "health probe asks HER model, not Wren's gemma tag", applied, rel)
            text = patch(text,
                         "try:\n    from dotenv import load_dotenv\n    load_dotenv()\nexcept ImportError:\n    pass",
                         "# neutralised: no .env autoload (environment is explicit)",
                         "no .env autoload from CWD", applied, rel)
            text = patch(text, '    room = body.get("room") or "wren"',
                         '    room = body.get("room") or os.environ.get("DEFAULT_ROOM", "wren")',
                         "default room from DEFAULT_ROOM", applied, rel)
            text = patch(text,
                         '    if not os.environ.get("GUARDIAN_ENCRYPTION_KEY", "").strip():\n'
                         '        problems.append("GUARDIAN_ENCRYPTION_KEY is not set")',
                         '    _store_key_env = os.environ.get("STORE_KEY_ENV", "GUARDIAN_ENCRYPTION_KEY")\n'
                         '    if not os.environ.get(_store_key_env, "").strip():\n'
                         '        problems.append("%s is not set" % _store_key_env)',
                         "preflight checks STORE_KEY_ENV, not GUARDIAN_ENCRYPTION_KEY", applied, rel)
            text = patch(text,
                         '    from config import OPENAI_MODEL_MAP as _openai_engines\n'
                         '    voice_key = "OPENAI_API_KEY" if ENGINE in _openai_engines else "ANTHROPIC_API_KEY"\n'
                         '    if not os.environ.get(voice_key, "").strip():\n'
                         '        problems.append("%s is not set -- Wren has no voice" % voice_key)',
                         '    _voice_key = os.environ.get("VOICE_KEY_ENV", "")\n'
                         '    if _voice_key and not os.environ.get(_voice_key, "").strip():\n'
                         '        problems.append("%s is not set -- no voice" % _voice_key)',
                         "preflight voice key is optional (VOICE_KEY_ENV)", applied, rel)

        touched = any(p["file"] == rel for p in applied)
        if touched:
            open(d, "w", encoding="utf-8", newline="\n").write(text)
        else:
            shutil.copyfile(s, d)          # byte-identical: unpatched files stay untouched
        entries.append({"src": s, "dst": d, "sha256_before": before,
                        "sha256_after": sha(d), "changed": touched})

    manifest = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "src": src, "dst": dst,
                "files": len(entries), "patched": sum(1 for e in entries if e["changed"]),
                "patches": applied, "entries": entries}
    out = args.manifest or os.path.join(dst, "..", "phase1-manifest.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print("copied %d files (%d patched) -> %s" % (len(entries), manifest["patched"], dst))
    print("manifest:", os.path.abspath(out))
    for e in entries:
        flag = "PATCHED" if e["changed"] else "copy   "
        print("  %s %s" % (flag, os.path.relpath(e["dst"], dst)))
    fixes = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apply_fixes.py")
    if os.path.exists(fixes) and not os.environ.get("SKIP_APPLY_FIXES"):
        import subprocess, sys as _sys
        print("--- applying production fixes ---")
        subprocess.run([_sys.executable, fixes, "--dst", dst,
                        "--report", os.path.join(os.path.dirname(os.path.abspath(out)),
                                                 "phase1-fixes.json")], check=True)
    print("patches applied:")
    for p in applied:
        print("  %-45s %s" % (os.path.basename(p["file"]), p["patch"]))


if __name__ == "__main__":
    main()





