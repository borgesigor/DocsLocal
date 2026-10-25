"""Store small application secrets encrypted for the current Windows user."""

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

from app.core.config import STATE
from app.services.storage import atomic_write

SECRET_FILE = STATE / 'github-secrets.bin'


class DataBlob(ctypes.Structure):
    _fields_ = [
        ('size', wintypes.DWORD),
        ('data', ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('O cofre de credenciais requer Windows DPAPI.')

    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = DataBlob()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPWSTR,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    operation.restype = wintypes.BOOL

    if not operation(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(output_blob.data)


class SecretStore:
    """Persist OAuth values in a DPAPI-protected file scoped to this user."""

    def __init__(self, path: Path = SECRET_FILE):
        self.path = path

    def read_all(self) -> dict[str, str]:
        try:
            encrypted = self.path.read_bytes()
            serialized = _crypt(encrypted, decrypt=True)
            values = json.loads(serialized.decode('utf-8'))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return {}

        return values if isinstance(values, dict) else {}

    def get(self, key: str) -> str | None:
        value = self.read_all().get(key)
        return value if isinstance(value, str) and value else None

    def write(self, **values: str | None) -> None:
        stored = self.read_all()
        for key, value in values.items():
            if value:
                stored[key] = value
            else:
                stored.pop(key, None)

        if not stored:
            self.clear()
            return

        plaintext = json.dumps(stored, separators=(',', ':')).encode('utf-8')
        atomic_write(self.path, _crypt(plaintext, decrypt=False))

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


secret_store = SecretStore()
