#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crypto.py — Enterprise Security & Secret Encryption (AES-256-CBC + HMAC-SHA256 Authenticated Encryption)
Standard enterprise cryptographic operations using the standard `cryptography` library.
Master key MUST be provided via ARGOS_MASTER_KEY environment variable (or Docker secret).
Refuses to startup if master key is missing or invalid.
"""

import os
import sys
import base64
import hashlib
import hmac
import secrets
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.backends import default_backend

from app_paths import APP_HOME, IS_FROZEN

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = APP_HOME
ENV_PATH = os.path.join(BASE_DIR, ".env")

_CACHED_MASTER_KEY = None


def _bootstrap_packaged_master_key() -> str:
    """Packaged (.exe) builds only: create a random master key on first run.

    Source/Docker deployments keep the strict behaviour (the key must be supplied
    by the operator). A packaged build has no installer step, so the key is
    generated once and stored in ``.env`` next to the executable. That file MUST
    be backed up: without it, secrets already encrypted in config.json / the
    database can no longer be decrypted.
    """
    key = secrets.token_hex(32)
    target_path = ENV_PATH
    try:
        try:
            existing = ""
            if os.path.isfile(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            prefix = "" if (not existing or existing.endswith("\n")) else "\n"
            with open(target_path, "a", encoding="utf-8") as f:
                f.write(prefix + "ARGOS_MASTER_KEY=" + key + "\n")
        except OSError:
            user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~"), "ArgosWorks")
            os.makedirs(user_data_dir, exist_ok=True)
            target_path = os.path.join(user_data_dir, ".env")
            existing = ""
            if os.path.isfile(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            prefix = "" if (not existing or existing.endswith("\n")) else "\n"
            with open(target_path, "a", encoding="utf-8") as f:
                f.write(prefix + "ARGOS_MASTER_KEY=" + key + "\n")

        try:
            os.chmod(target_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        raise RuntimeError(
            "Cannot create master key file in %s (%s). "
            "Make sure the program folder is writable." % (target_path, exc)
        )
    print("[Security] First run: generated a new ARGOS_MASTER_KEY in %s - back up this file." % target_path,
          file=sys.stderr, flush=True)
    return key


def get_master_key() -> bytes:
    """Return 32-byte master key derived from ARGOS_MASTER_KEY (or legacy JARVIS_MASTER_KEY).
    Refuses startup if master key is missing or not provided.
    """
    global _CACHED_MASTER_KEY
    if _CACHED_MASTER_KEY is not None:
        return _CACHED_MASTER_KEY

    raw_key = os.environ.get("ARGOS_MASTER_KEY", "").strip() or os.environ.get("JARVIS_MASTER_KEY", "").strip()

    # If not in environ, check Docker secret file or .env file
    secret_file = "/run/secrets/argos_master_key"
    if not raw_key and os.path.isfile(secret_file):
        try:
            with open(secret_file, "r", encoding="utf-8") as f:
                raw_key = f.read().strip()
        except Exception:
            pass

    if not raw_key and os.path.isfile(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if (line.startswith("ARGOS_MASTER_KEY=") or line.startswith("JARVIS_MASTER_KEY=")) and not line.startswith("#"):
                        raw_key = line.split("=", 1)[1].strip()
                        if raw_key:
                            break
        except Exception:
            pass

    if not raw_key and IS_FROZEN:
        raw_key = _bootstrap_packaged_master_key()

    # Strictly reject missing master key: Never silently auto-generate to .env container ephemeral storage
    if not raw_key:
        raise RuntimeError(
            "FATAL SECURITY ERROR: ARGOS_MASTER_KEY is not set in environment or secret store. "
            "Master key must be securely provided via environment variable ARGOS_MASTER_KEY or Docker secret."
        )

    # Derive 32 bytes using SHA-256
    _CACHED_MASTER_KEY = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return _CACHED_MASTER_KEY


def _derive_keys(master_key: bytes):
    enc_key = hashlib.sha256(master_key + b":enc_key_v1").digest()
    mac_key = hashlib.sha256(master_key + b":mac_key_v1").digest()
    return enc_key, mac_key


PREFIX = "enc:v1:"


def is_encrypted(val: str) -> bool:
    """Check if value is in encrypted format."""
    return bool(val and isinstance(val, str) and val.startswith(PREFIX))


def _aes256_cbc_encrypt(plaintext_bytes: bytes, key: bytes, iv: bytes) -> bytes:
    padder = crypto_padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext_bytes) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(padded_data) + encryptor.finalize()


def _aes256_cbc_decrypt(ciphertext_bytes: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext_bytes) + decryptor.finalize()
    unpadder = crypto_padding.PKCS7(128).unpadder()
    return unpadder.update(padded_data) + unpadder.finalize()


def encrypt_secret(val: str) -> str:
    """Encrypt a string secret using standard AES-256-CBC + HMAC-SHA256 authenticated encryption.
    Returns string prefixed with 'enc:v1:'. If empty, returns empty string.
    Raises RuntimeError on failure rather than returning plaintext.
    """
    if not val or not isinstance(val, str):
        return val or ""
    val_str = val
    if not val_str:
        return ""
    if is_encrypted(val_str):
        return val_str

    try:
        master_key = get_master_key()
        enc_key, mac_key = _derive_keys(master_key)
        iv = secrets.token_bytes(16)
        plaintext_bytes = val_str.encode("utf-8")
        ciphertext = _aes256_cbc_encrypt(plaintext_bytes, enc_key, iv)
        # Encrypt-then-MAC: HMAC covers IV + ciphertext
        mac = hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest()
        payload = iv + mac + ciphertext
        return PREFIX + base64.b64encode(payload).decode("ascii")
    except Exception as e:
        raise RuntimeError(f"Secret encryption failed: {e}") from e


def decrypt_secret(val: str) -> str:
    """Decrypt a secret prefixed with 'enc:v1:'.
    If not encrypted (plain text), returns the string as is for 100% backward compatibility.
    If tampered or corrupted, returns empty string or raises on critical errors.
    """
    if not val or not isinstance(val, str):
        return val or ""
    val_str = val
    if not is_encrypted(val_str):
        return val_str

    try:
        raw_b64 = val_str[len(PREFIX):]
        payload = base64.b64decode(raw_b64)
        if len(payload) < 16 + 32 + 16:  # IV(16) + MAC(32) + at least 1 AES block(16)
            return ""

        iv = payload[:16]
        expected_mac = payload[16:48]
        ciphertext = payload[48:]

        master_key = get_master_key()
        enc_key, mac_key = _derive_keys(master_key)

        # Authenticate first (Encrypt-then-MAC verification)
        actual_mac = hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(actual_mac, expected_mac):
            print("[Crypto] HMAC verification failed — ciphertext tampered or invalid master key", file=sys.stderr)
            return ""

        plaintext_bytes = _aes256_cbc_decrypt(ciphertext, enc_key, iv)
        return plaintext_bytes.decode("utf-8")
    except Exception as e:
        print(f"[Crypto] Decryption failed: {e}", file=sys.stderr)
        return ""
