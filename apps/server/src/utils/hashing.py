"""提供文件, 资源和其他业务数据使用的哈希计算能力"""

import hashlib
import secrets

_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """为密码生成盐值哈希, 返回 salt$hash 格式"""

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码是否与盐值哈希匹配"""

    if "$" not in password_hash:
        return False

    salt, digest = password_hash.split("$", 1)
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    ).hex()
    return secrets.compare_digest(candidate, digest)