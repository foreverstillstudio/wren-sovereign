"""The web pre-pass gate: who may use it, and which messages are worth asking the decider about.

Before this, every chat turn for every companion sent the latest message (first 2,000 characters)
to OpenAI so a small model could decide whether the turn needed the web. Most turns do not.

Two things are decided here, both without any network call:

  WHO     WEB_PREPASS               on by default; 0 / false / no / off turns the whole pre-pass off.
          WEB_PREPASS_COMPANIONS    which companions may use it, comma separated. Not set means all
                                    four (wren, ember, maeve, rowan). Set but empty means none.
                                    Names the kernel does not know are ignored.
  WHICH   WEB_PREFILTER             on by default; 0 / false / no / off asks the decider about every
                                    message, as the kernel did before. When on, the decider is asked
                                    only if the message names a page or site, or uses a word that
                                    plainly points at the live web (search, news, weather, today,
                                    latest, ...). A message with none of those makes no OpenAI call
                                    and no search. Saying "look it up" or "search for" always works.

The environment is read on every call; the kernel's own environment is fixed when it starts, so
a change to these settings takes effect at the next restart.
"""
import os
import re

COMPANIONS = ("wren", "ember", "maeve", "rowan")
_OFF = ("0", "false", "no", "off")


def _on(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in _OFF


def enabled():
    """The whole web pre-pass, for everyone."""
    return _on("WEB_PREPASS")


def prefilter_on():
    return _on("WEB_PREFILTER")


def allowed_companions():
    raw = os.environ.get("WEB_PREPASS_COMPANIONS")
    if raw is None:
        return frozenset(COMPANIONS)
    names = {n.strip().lower() for n in raw.split(",")}
    return frozenset(n for n in names if n in COMPANIONS)


def allowed_for(companion):
    """May this companion's turn use the web pre-pass at all? An unknown or empty name may not."""
    return enabled() and str(companion or "").strip().lower() in allowed_companions()


# A page or site she named: a scheme, www., or a bare domain with a common ending.
_SITE = r"(?:https?://|www\.|\b[a-z0-9][a-z0-9-]*\.(?:com|org|net|io|co|dev|app|edu|gov|us|uk|ca|info|biz|shop|store|site|online|xyz|ai)\b)"
# Words that plainly point at the live web or at something that changes.
_WORDS = (
    r"\b(?:search(?:ing|es)?|google[sd]?|bing|duckduckgo|look(?:ing)?\s+(?:it\s+|that\s+|this\s+|them\s+)?up|lookup|"
    r"on\s+the\s+(?:web|internet)|online|internet|web\s?(?:site|page)s?|links?|news|headlines?|"
    r"weather|forecast|temperature|stocks?|scores?|who\s+won|breaking|trending|"
    r"today|tonight|tomorrow|this\s+(?:week|weekend|morning|afternoon|evening)|right\s+now|"
    r"latest|current(?:ly)?|recent(?:ly)?|just\s+(?:came\s+out|released|announced)|"
    r"reviews?|open\s+(?:now|today|right\s+now)|hours\s+(?:of|for)|"
    r"check\s+(?:the|their|this|that|out)\s+(?:site|page|link|website))\b"
)
_LOOKS_WEB = re.compile(_SITE + "|" + _WORDS, re.IGNORECASE)


def looks_like_web(text):
    """Is this message worth asking the decider about? Cheap, local, deterministic."""
    return bool(_LOOKS_WEB.search(str(text or "")))
