"""
加密工具模块
提供有效期加密存储、时间戳加密存储等功能
"""
import hashlib
import struct
import os
import datetime

# ==================== 加密密钥（分散存储） ====================
# 这些值在运行时动态组合，增加静态分析难度
_K1 = 0x42
_K2 = 0x37
_K3 = 0x19
_K4 = 0x88

# ==================== 加密后的有效期 ====================
# 2026年7月1日 加密后的字节
# 计算方式: plain = [0x07, 0xEA, 0x07, 0x01] (年份高8位, 年份低8位, 月, 日)
#           key = [0x42, 0x37, 0x19, 0x88]
#           encrypted = plain XOR key
_ENCRYPTED_EXPIRY = bytes([0x45, 0xDD, 0x1E, 0x89])

def _get_key():
    """动态组合加密密钥"""
    return bytes([_K1, _K2, _K3, _K4])

def decrypt_expiry():
    """
    解密有效期
    返回: datetime.date 对象
    """
    key = _get_key()
    decrypted = bytes(a ^ b for a, b in zip(_ENCRYPTED_EXPIRY, key))
    year = (decrypted[0] << 8) | decrypted[1]
    month = decrypted[2]
    day = decrypted[3]
    return datetime.date(year, month, day)

def encrypt_expiry_date(year, month, day):
    """
    加密有效期日期（用于生成加密字节）
    返回: bytes (4字节)
    """
    plain = bytes([year >> 8, year & 0xFF, month, day])
    key = _get_key()
    return bytes(a ^ b for a, b in zip(plain, key))

# ==================== 时间戳加密存储 ====================
TIMESTAMP_FILE = os.path.join(os.path.expanduser("~"), ".delta_auto_timestamp.dat")

def _hash_data(data):
    """计算数据的哈希值（用于校验）"""
    return hashlib.md5(data).digest()[:4]

def save_timestamp(dt):
    """
    加密保存时间戳到文件
    参数: dt - datetime.datetime 或 datetime.date 对象
    """
    if isinstance(dt, datetime.date):
        dt = datetime.datetime.combine(dt, datetime.time())

    # 转换为时间戳（8字节）
    timestamp = int(dt.timestamp())
    data = struct.pack('>q', timestamp)

    # XOR混淆时间戳数据
    key = _get_key()
    data = bytes(a ^ key[i % len(key)] for i, a in enumerate(data))

    # 计算校验和
    checksum = _hash_data(data)

    # 写入文件
    try:
        with open(TIMESTAMP_FILE, 'wb') as f:
            f.write(data + checksum)
        return True
    except Exception:
        return False

def load_timestamp():
    """
    从文件加载并解密时间戳
    返回: datetime.datetime 或 None（文件不存在或损坏时）
    """
    if not os.path.exists(TIMESTAMP_FILE):
        return None

    try:
        with open(TIMESTAMP_FILE, 'rb') as f:
            data = f.read()

        # 验证文件长度
        if len(data) != 12:  # 8字节时间戳 + 4字节校验和
            return None

        # 验证校验和
        timestamp_data = data[:8]
        stored_checksum = data[8:]
        expected_checksum = _hash_data(timestamp_data)

        if stored_checksum != expected_checksum:
            return None

        # XOR解密时间戳数据
        key = _get_key()
        timestamp_data = bytes(a ^ key[i % len(key)] for i, a in enumerate(timestamp_data))

        # 解密时间戳
        timestamp = struct.unpack('>q', timestamp_data)[0]
        return datetime.datetime.fromtimestamp(timestamp)
    except Exception:
        return None

def clear_timestamp():
    """清除时间戳文件"""
    try:
        if os.path.exists(TIMESTAMP_FILE):
            os.remove(TIMESTAMP_FILE)
        return True
    except Exception:
        return False

# ==================== 测试函数 ====================
def _test_encryption():
    """测试加密解密功能"""
    # 测试有效期解密
    expiry = decrypt_expiry()
    print(f"解密后的有效期: {expiry}")

    # 测试加密
    encrypted = encrypt_expiry_date(2026, 7, 1)
    print(f"加密后的字节: {encrypted}")

    # 测试时间戳保存和加载
    now = datetime.datetime.now()
    save_timestamp(now)
    loaded = load_timestamp()
    print(f"保存的时间: {now}")
    print(f"加载的时间: {loaded}")
    print(f"时间匹配: {now.date() == loaded.date()}")

    # 清理
    clear_timestamp()
    print("测试完成")

if __name__ == '__main__':
    _test_encryption()
