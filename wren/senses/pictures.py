import base64
import binascii
import os
import re
import secrets
import threading
import time
from typing import Final, List, Dict, Tuple, Optional, Any, TypedDict, Literal, Union

# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

class ImageUrlDetail(TypedDict, total=False):
    url: str
    detail: Literal["low", "high", "auto"]

class ImagePart(TypedDict):
    type: Literal["image_url"]
    image_url: ImageUrlDetail

class ContentPart(TypedDict, total=False):
    type: Literal["text", "image_url"]
    text: str
    image_url: ImageUrlDetail

class PictureHoldInfo(TypedDict):
    key: str
    slot: int
    count: int
    words: str

# =============================================================================
# CONSTANTS (The Iron Law)
# =============================================================================

MAX_PICTURES: Final[int] = 4
MAX_PICTURE_BYTES: Final[int] = 6 * 1024 * 1024          # 6 MB
DEFAULT_MAX_REQUEST_BYTES: Final[int] = 36 * 1024 * 1024  # 36 MB
HOLD_SECONDS: Final[int] = 3600  # 1 Hour

ALLOWED_TYPES: Final[Tuple[str, ...]] = ("image/png", "image/jpeg", "image/gif", "image/webp")
_DATA_URL_PATTERN: Final[re.Pattern] = re.compile(
    r"^data:(image/[a-z0-9.+-]+);base64,(.*)$", re.DOTALL | re.IGNORECASE
)

# =============================================================================
# EXCEPTIONS
# =============================================================================

class PictureError(ValueError):
    """Refusal of sensory input due to architectural constraints."""
    def __init__(self, code: str, message: str, status: int = 400, pictures: int = 0, size: int = 0):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status
        self.pictures = pictures
        self.size = size

# =============================================================================
# SOVEREIGN PICTURE ENGINE
# =============================================================================

class SovereignPictureEngine:
    """
    The authoritative engine for the validation, temporary holding, 
    and attachment of visual sensory data.
    """
    _instance: Optional['SovereignPictureEngine'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SovereignPictureEngine, cls).__new__(cls)
                cls._instance._init_engine()
            return cls._instance

    def _init_engine(self):
        self._held: Dict[str, Tuple[float, List[ImagePart]]] = {}
        self._messages = {
            "too-many-pictures": f"That message has more than {MAX_PICTURES} pictures. Send at most {MAX_PICTURES} at a time.",
            "unsupported-picture-type": "Pictures must be PNG, JPEG, GIF or WebP, sent as data. One of these was not.",
            "malformed-picture": "One of the pictures could not be read (it is not valid picture data).",
            "picture-too-large": "One of the pictures is over 6 MB. Send a smaller one.",
            "request-too-large": f"That message is too large to send (over {DEFAULT_MAX_REQUEST_BYTES // (1024 * 1024)} MB in all).",
            "malformed-tool-turn": "That message could not be understood.",
            "pictures-no-longer-available": "The pictures for this turn are no longer available. Please send the message again.",
        }

    def _get_msg(self, code: str) -> str:
        return self._messages.get(code, "That message was refused.")

    def get_max_request_bytes(self) -> int:
        try:
            val = int(str(os.environ.get("WREN_TOOL_TURN_MAX_BODY_BYTES", DEFAULT_MAX_REQUEST_BYTES)).strip())
            return val if val >= 1024 * 1024 else DEFAULT_MAX_REQUEST_BYTES
        except ValueError:
            return DEFAULT_MAX_REQUEST_BYTES

    def _verify_signature(self, kind: str, raw: bytes) -> bool:
        """Binary verification of file headers to prevent spoofing."""
        signatures = {
            "image/png": b"\x89PNG\r\n\x1a\n",
            "image/jpeg": b"\xff\xd8\xff",
            "image/gif": (b"GIF87a", b"GIF89a"),
            "image/webp": b"RIFF" # Simplified check for RIFF
        }
        sig = signatures.get(kind)
        if not sig: return False
        if isinstance(sig, tuple):
            return raw.startswith(sig)
        return raw.startswith(sig)

    def _validate_picture(self, url: str, seen_count: int) -> int:
        """Pure validation of a single image data URL."""
        match = _DATA_URL_PATTERN.match(url) if isinstance(url, str) else None
        if not match:
            raise PictureError("unsupported-picture-type", self._get_msg("unsupported-picture-type"), pictures=seen_count)
        
        kind, payload = match.group(1).lower(), match.group(2)
        if kind not in ALLOWED_TYPES:
            raise PictureError("unsupported-picture-type", self._get_msg("unsupported-picture-type"), pictures=seen_count)

        # Pre-decode size check (base64 is ~4/3 the size of raw)
        if len(payload) > (MAX_PICTURE_BYTES * 4) // 3 + 8:
            raise PictureError("picture-too-large", self._get_msg("picture-too-large"), pictures=seen_count, size=len(payload))

        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise PictureError("malformed-picture", self._get_msg("malformed-picture"), pictures=seen_count)

        if len(raw) >= MAX_PICTURE_BYTES:
            raise PictureError("picture-too-large", self._get_msg("picture-too-large"), pictures=seen_count, size=len(raw))

        if not self._verify_signature(kind, raw):
            raise PictureError("unsupported-picture-type", self._get_msg("unsupported-picture-type"), pictures=seen_count, size=len(raw))
        
        return len(raw)

    def split_user_content(self, content: Union[str, List[Any]]) -> Tuple[str, List[ImagePart], int]:
        """Separates text from images, validating all visual inputs."""
        if isinstance(content, str):
            return content, [], 0
        
        if not isinstance(content, list):
            raise PictureError("malformed-tool-turn", self._get_msg("malformed-tool-turn"))

        words: List[str] = []
        pictures: List[ImagePart] = []
        total_bytes = 0

        for part in content:
            if not isinstance(part, dict):
                raise PictureError("malformed-tool-turn", self._get_msg("malformed-tool-turn"), pictures=len(pictures))
            
            kind = part.get("type")
            if kind == "text" and isinstance(part.get("text"), str):
                words.append(part["text"])
            elif kind == "image_url":
                ref = part.get("image_url")
                url = ref.get("url") if isinstance(ref, dict) else ref
                
                if len(pictures) >= MAX_PICTURES:
                    raise PictureError("too-many-pictures", self._get_msg("too-many-pictures"), pictures=len(pictures) + 1)
                
                total_bytes += self._validate_picture(url, len(pictures) + 1)
                
                # Construct clean, immutable ImagePart
                clean_url: ImageUrlDetail = {"url": url}
                if isinstance(ref, dict):
                    detail = ref.get("detail")
                    if detail in ("low", "high", "auto"):
                        clean_url["detail"] = detail
                
                pictures.append({"type": "image_url", "image_url": clean_url})
            else:
                raise PictureError("malformed-tool-turn", self._get_msg("malformed-tool-turn"), pictures=len(pictures))

        return " ".join(w for w in words if w), pictures, total_bytes

    def _sweep(self, now: float):
        """Internal cleanup of expired image holds."""
        expired = [k for k, (until, _) in self._held.items() if until <= now]
        for k in expired:
            self._held.pop(k, None)

    def hold(self, pictures: List[ImagePart]) -> str:
        """Stores pictures in memory and returns an opaque key."""
        key = f"pic_{secrets.token_hex(8)}"
        now = time.time()
        with self._lock:
            self._sweep(now)
            self._held[key] = (now + HOLD_SECONDS, list(pictures))
        return key

    def retrieve(self, key: str) -> Optional[List[ImagePart]]:
        """Retrieves pictures if the hold is still valid."""
        now = time.time()
        with self._lock:
            self._sweep(now)
            entry = self._held.get(key)
        return list(entry[1]) if entry else None

    def drop(self, key: str):
        """Manually purges a hold."""
        with self._lock:
            self._held.pop(key, None)

    def attach(self, messages: List[Dict[str, Any]], info: Optional[PictureHoldInfo]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Re-injects held pictures into the message stream for the Provider.
        Returns (modified_messages, error_code).
        """
        if not info:
            return messages, None

        pictures = self.retrieve(info.get("key"))
        slot = info.get("slot")

        if pictures is None or not isinstance(slot, int) or not (0 <= slot < len(messages)):
            return messages, "pictures-no-longer-available"

        # Create a shallow copy of the message list to avoid mutating history
        out = list(messages)
        live_msg = out[slot]
        
        content = live_msg.get("content")
        words = content if isinstance(content, str) else ""
        
        # Build the composite content (text + pictures)
        composite_content: List[ContentPart] = []
        if info.get("words") and words:
            composite_content.append({"type": "text", "text": words})
        
        composite_content.extend(pictures)
        
        out[slot] = {**live_msg, "content": composite_content}
        return out, None

# Global instance for system-wide access
Engine = SovereignPictureEngine()


# --- PUBLIC BRIDGE (the names server.py / gateway.py call) ---

def max_request_bytes():
    return Engine.get_max_request_bytes()


def message_for(code):
    return Engine._get_msg(code)


def split_user_content(content):
    return Engine.split_user_content(content)


def hold(pictures):
    return Engine.hold(pictures)


def drop(key):
    return Engine.drop(key)


def attach(messages, info):
    return Engine.attach(messages, info)
