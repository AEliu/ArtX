from __future__ import annotations

import base64
import hashlib
import hmac

from Crypto.Cipher import AES

from .constants import AES_IV, AES_KEY, ENCRYPTION_MARKER, SIGNING_KEY
from .models import PageInfo


def compute_tile_url(page_info: PageInfo, x: int, y: int, z: int) -> str:
    path = page_info.path()
    sign_payload = f"{path}=x{x}-y{y}-z{z}-t".encode("utf-8") + page_info.token.encode("utf-8")
    digest = hmac.new(SIGNING_KEY, sign_payload, hashlib.sha1).digest()
    signature = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=").replace("-", "_")
    return f"{page_info.base_url}=x{x}-y{y}-z{z}-t{signature}"


def decrypt_tile_if_needed(data: bytes) -> bytes:
    if not data.startswith(ENCRYPTION_MARKER):
        return data

    if len(data) < 12:
        return data

    header_size = int.from_bytes(data[-4:], "little")
    encrypted_size_offset = 4 + header_size
    encrypted_size = int.from_bytes(data[encrypted_size_offset : encrypted_size_offset + 4], "little")
    encrypted_start = encrypted_size_offset + 4
    encrypted_end = encrypted_start + encrypted_size
    footer_end = len(data) - 4

    if encrypted_end > footer_end or encrypted_size <= 0:
        return data

    header = data[4 : 4 + header_size]
    encrypted = data[encrypted_start:encrypted_end]
    footer = data[encrypted_end:footer_end]

    if len(encrypted) % AES.block_size != 0:
        return data

    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
    decrypted = cipher.decrypt(encrypted)
    return header + decrypted + footer
