"""Encrypted local secret storage for API keys and tokens.

Backends
--------
Windows: DPAPI (``CryptProtectData``) bound to the current user account.
Other systems: Fernet (AES-128-CBC + HMAC-SHA256) with a 0600 key file.

The on-disk envelope never contains plaintext.  Keys are cached in memory only
while the application is running and are never logged, exported in backups or
included in diagnostics.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path

from ..core.errors import AppError

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,80}$")
_IS_WINDOWS = sys.platform.startswith("win")


class SecretBackendError(AppError):
    code = "security.backend"
    title_key = "error.secret"


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        os.chmod(path, mode)
    except OSError:  # pragma: no cover - windows
        pass


# --------------------------------------------------------------------------- DPAPI
if _IS_WINDOWS:  # pragma: no cover - executed on Windows only
    import ctypes
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _dpapi_protect(data: bytes) -> bytes:
        in_blob, _keep = _blob(data)
        out_blob = _DataBlob()
        if not _crypt32.CryptProtectData(
            ctypes.byref(in_blob), "MyAI Studio secret", None, None, None, 0x1, ctypes.byref(out_blob)
        ):
            raise SecretBackendError(
                "DPAPI encryption failed", message_key="error.secret", details=str(ctypes.get_last_error())
            )
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            _kernel32.LocalFree(out_blob.pbData)

    def _dpapi_unprotect(data: bytes) -> bytes:
        in_blob, _keep = _blob(data)
        out_blob = _DataBlob()
        if not _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
        ):
            raise SecretBackendError(
                "DPAPI decryption failed", message_key="error.secret", details=str(ctypes.get_last_error())
            )
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            _kernel32.LocalFree(out_blob.pbData)


class SecretStore:
    """Thread-safe encrypted key/value store for credentials."""

    def __init__(self, secrets_file: Path, key_file: Path) -> None:
        self.path = Path(secrets_file)
        self.key_path = Path(key_file)
        self.backend = "dpapi" if _IS_WINDOWS else "fernet"
        self._lock = threading.RLock()
        self._cache: dict[str, str] | None = None
        self._fernet = None

    # ------------------------------------------------------------- fernet key
    def _get_fernet(self):
        if self._fernet is not None:
            return self._fernet
        from cryptography.fernet import Fernet

        if not self.key_path.exists():
            key = Fernet.generate_key()
            _atomic_write(self.key_path, key)
            logger.info("secret_key_created path=%s", self.key_path)
        else:
            key = self.key_path.read_bytes()
        try:
            self._fernet = Fernet(key)
        except Exception as exc:
            raise SecretBackendError(
                "Secret key file is corrupt", message_key="error.secret", cause=exc
            ) from exc
        return self._fernet

    # ------------------------------------------------------------- load/save
    def _encrypt(self, payload: bytes) -> str:
        if self.backend == "dpapi":
            return base64.b64encode(_dpapi_protect(payload)).decode("ascii")
        return self._get_fernet().encrypt(payload).decode("ascii")

    def _decrypt(self, token: str) -> bytes:
        if self.backend == "dpapi":
            # DPAPI ciphertext is stored base64-encoded; Fernet tokens already are.
            return _dpapi_unprotect(base64.b64decode(token.encode("ascii")))
        return self._get_fernet().decrypt(token.encode("ascii"))

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            token = envelope["data"]
            file_backend = envelope.get("backend", "fernet")
            if file_backend != self.backend:
                raise SecretBackendError(
                    "Secret file was created on a different platform",
                    message_key="error.secret",
                    details=f"{file_backend} != {self.backend}",
                )
            payload = json.loads(self._decrypt(token).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Invalid secret payload")
            self._cache = {str(k): str(v) for k, v in payload.items()}
        except SecretBackendError:
            raise
        except Exception as exc:
            raise SecretBackendError(
                "Secret file could not be read (it may belong to another user)",
                message_key="error.secret",
                details=type(exc).__name__,
                cause=exc,
            ) from exc
        return self._cache

    def _save(self, values: dict[str, str]) -> None:
        if not values:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            self._cache = {}
            return
        payload = json.dumps(values, ensure_ascii=False).encode("utf-8")
        envelope = {
            "v": 1,
            "backend": self.backend,
            "data": self._encrypt(payload),
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        _atomic_write(self.path, json.dumps(envelope).encode("utf-8"))

    # ------------------------------------------------------------------- api
    # The single place that knows which key name the AI provider uses. Keeping
    # it here means no module has to hard-code the storage name.
    OPENROUTER_KEY = "openrouter.api_key"

    def get_api_key(self) -> str | None:
        return self.get(self.OPENROUTER_KEY)

    def set_api_key(self, value: str) -> None:
        value = (value or "").strip()
        if not value:
            self.delete(self.OPENROUTER_KEY)
            return
        self.set(self.OPENROUTER_KEY, value)

    def has_api_key(self) -> bool:
        return self.has(self.OPENROUTER_KEY)

    def get(self, name: str) -> str | None:
        self._validate_name(name)
        with self._lock:
            return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        self._validate_name(name)
        if not isinstance(value, str) or not value:
            raise ValueError("Secret value must be a non-empty string")
        with self._lock:
            values = dict(self._load())
            values[name] = value
            self._save(values)
            self._cache = values
        logger.info("secret_saved name=%s", name)

    def delete(self, name: str) -> bool:
        self._validate_name(name)
        with self._lock:
            values = dict(self._load())
            existed = values.pop(name, None) is not None
            if existed:
                self._save(values)
                self._cache = values
        if existed:
            logger.info("secret_deleted name=%s", name)
        return existed

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._load().keys())

    def delete_all(self) -> None:
        with self._lock:
            self._save({})

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(f"Invalid secret name: {name!r}")

    def status(self) -> dict[str, object]:  # pragma: no cover - trivial
        return {
            "backend": "Windows DPAPI (current user)" if self.backend == "dpapi" else "Fernet (local key file)",
            "path": str(self.path),
            "exists": self.path.exists(),
            "count": len(self._load()),
        }
