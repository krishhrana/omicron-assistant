import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.settings import get_settings


def _derive_fernet_key(master_key: str, service: str) -> str:
    master_bytes = base64.urlsafe_b64decode(master_key)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"omicron:{service}".encode("utf-8"),
    )
    derived = hkdf.derive(master_bytes)
    return base64.urlsafe_b64encode(derived).decode("utf-8")


def _require_master_key() -> str:
    key = get_settings().google_tokens_encryption_key
    if not key:
        raise RuntimeError("Missing gmail_tokens_encryption_key; token encryption is required.")
    return key


def _get_master_fernet() -> Fernet:
    key = _require_master_key()
    return Fernet(key)


def _get_fernet(service: str) -> Fernet:
    key = _require_master_key()
    derived_key = _derive_fernet_key(key, service)
    return Fernet(derived_key)


def encrypt_token(token: str | None, *, service: str) -> str | None:
    if token is None:
        return None
    fernet = _get_fernet(service)
    if token.startswith("gAAAAAB"):
        return token
    return fernet.encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str | None, *, service: str) -> str | None:
    if token is None:
        return None
    fernet = _get_fernet(service)
    if not token.startswith("gAAAAAB"):
        raise ValueError(f"Unencrypted {service} token stored")
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        legacy = _get_master_fernet()
        try:
            return legacy.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            pass
        raise ValueError(f"Failed to decrypt {service} token") from exc
