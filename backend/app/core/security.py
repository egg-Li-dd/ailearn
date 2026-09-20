"""PIN 哈希与 token 工具（标准库实现，无额外依赖）。"""
import hashlib
import secrets

from .config import PIN_ITERATIONS


def hash_pin(pin: str) -> str:
    """PBKDF2-HMAC-SHA256 + 随机盐，返回 salt$digest。"""
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt.encode("utf-8"), PIN_ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt.encode("utf-8"), PIN_ITERATIONS
    ).hex()
    return secrets.compare_digest(calc, digest)


def new_token() -> tuple[str, str]:
    """生成 (raw_token, sha256_hash)。服务端只存哈希。"""
    raw = secrets.token_hex(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()