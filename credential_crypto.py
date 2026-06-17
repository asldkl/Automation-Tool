"""
凭据加密模块
使用 Fernet 对称加密保护敏感配置（SMTP 授权码、账号密码等）
密钥基于机器指纹派生，绑定到当前设备
"""
import os
import hashlib
import base64
import json

_KEY_FILE = os.path.join(os.path.expanduser("~"), ".delta_auto_crypto.key")


def _derive_key():
    """从机器指纹派生 Fernet 密钥（32 url-safe base64 字符）"""
    try:
        import machine_fingerprint
        machine_id = machine_fingerprint.get_machine_id()
    except Exception:
        machine_id = "fallback_key"

    # 使用 PBKDF2 派生密钥（标准库实现，无需外部依赖）
    salt = b"delta_auto_salt_v1"
    dk = hashlib.pbkdf2_hmac('sha256', machine_id.encode(), salt, iterations=100000, dklen=32)
    return base64.urlsafe_b64encode(dk)


def _get_fernet():
    """获取 Fernet 加密实例"""
    from cryptography.fernet import Fernet
    key = _derive_key()
    return Fernet(key)


def encrypt_value(plaintext):
    """加密字符串值，返回加密后的字符串（base64 编码）"""
    if not plaintext:
        return ""
    try:
        f = _get_fernet()
        encrypted = f.encrypt(plaintext.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        print(f"⚠️ 加密失败: {e}")
        return plaintext


def decrypt_value(ciphertext):
    """解密字符串值，返回原始字符串。如果是明文则原样返回"""
    if not ciphertext:
        return ""
    try:
        f = _get_fernet()
        decrypted = f.decrypt(ciphertext.encode('utf-8'))
        return decrypted.decode('utf-8')
    except Exception:
        # 解密失败说明是明文数据，原样返回（向后兼容）
        return ciphertext


def is_encrypted(value):
    """判断字符串是否已加密（Fernet token 以 'gAAAAA' 开头）"""
    if not value:
        return False
    return value.startswith('gAAAAA')


def encrypt_settings(settings):
    """加密设置中的敏感字段，返回新字典（smtp_code 不加密）"""
    encrypted = dict(settings)
    sensitive_keys = []  # smtp_code 不再加密
    for key in sensitive_keys:
        val = encrypted.get(key, "")
        if val and not is_encrypted(val):
            encrypted[key] = encrypt_value(val)
    # 如果已有的 smtp_code 被加密过，解密回明文
    smtp_val = encrypted.get("smtp_code", "")
    if smtp_val and is_encrypted(smtp_val):
        encrypted["smtp_code"] = decrypt_value(smtp_val)
    return encrypted


def decrypt_settings(settings):
    """解密设置中的敏感字段，返回新字典（smtp_code 不加密）"""
    decrypted = dict(settings)
    # smtp_code 不再加密，但如果旧版本已加密过，解密回明文
    smtp_val = decrypted.get("smtp_code", "")
    if smtp_val and is_encrypted(smtp_val):
        decrypted["smtp_code"] = decrypt_value(smtp_val)
    return decrypted