"""数据库里保存的密钥（如 API Key）用 SECRET_KEY 派生的密钥加密，备份泄露时不直接暴露明文。

注意：改了 SECRET_KEY 之后，已保存的 API Key 无法解密，需要在「系统设置」里重新填写。
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


def _fernet() -> Fernet:
    key = hashlib.sha256(("secretbox:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
