"""
tool_crypto.py — ed25519 signing/verification for the signed tool protocol.

Matches the Electron client (wren-tool-client.js) byte-for-byte:
  canonical(value)  -> recursively sort object keys (arrays preserved, order kept)
  bytes(value)      -> JSON.stringify(canonical(value)) i.e. compact JSON, sorted keys

The server holds one persistent ed25519 keypair (created lazily on first use).
The client pins its public key and verifies every tool_call's `server_signature`
against it. This is the "workspace-read-v2" key-exchange half that Sovereign
Mode previously bypassed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

PROTOCOL: str = "workspace-read-v2"

_KEY_DIR: str = os.environ.get("WREN_STORE_DIR", "data")
_KEY_PATH: str = os.path.join(_KEY_DIR, "wren_server_ed25519.pem")

_lock = threading.Lock()
_private_key = None
_public_raw = None
_server_key_id = None
_server_public_key = None


def canonical(value):
    """Recursively sort dict keys; leave lists and scalars untouched."""
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: canonical(value[k]) for k in sorted(value.keys())}
    return value


def canonical_bytes(value) -> bytes:
    """The exact bytes the client signs/verifies: compact JSON, sorted keys."""
    return json.dumps(
        canonical(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _load_or_create_key() -> Ed25519PrivateKey:
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "rb") as fh:
            return Ed25519PrivateKey.from_pem(fh.read())
    key = Ed25519PrivateKey.generate()
    os.makedirs(os.path.dirname(_KEY_PATH), exist_ok=True)
    with open(_KEY_PATH, "wb") as fh:
        fh.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    try:
        os.chmod(_KEY_PATH, 0o600)
    except OSError:
        pass
    return key


def _keypair() -> Ed25519PrivateKey:
    global _private_key, _public_raw
    if _private_key is None:
        with _lock:
            if _private_key is None:
                _private_key = _load_or_create_key()
                _public_raw = _private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
    return _private_key


def server_key_info() -> dict:
    """The response body for GET /api/wren/tool-signing-key."""
    global _server_key_id, _server_public_key
    _keypair()
    if _server_key_id is None:
        _server_key_id = "server_" + hashlib.sha256(_public_raw).hexdigest()[:24]
        _server_public_key = _b64url(_public_raw)
    return {"protocol": PROTOCOL, "key_id": _server_key_id,
            "public_key": _server_public_key}


def sign(value) -> str:
    """Sign a value with the server key; returns base64url signature."""
    return _b64url(_keypair().sign(canonical_bytes(value)))


def verify(public_key_b64: str, signature_b64: str, value) -> bool:
    """Verify a base64url signature over `value` against a raw public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key_b64))
        pub.verify(_b64url_decode(signature_b64), canonical_bytes(value))
        return True
    except Exception:
        return False
