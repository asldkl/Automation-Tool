"""
应用程序配置信息
"""

APP_NAME = "LCA"
APP_VERSION = "1.2.6.2"

# 在线更新服务已移除；保留常量给旧调用方安全读取。
UPDATE_SERVER = ""
MANIFEST_URL = ""
INSTALLER_URL_TEMPLATE = ""

# 安全配置
VERIFY_HASH = True  # 是否验证文件哈希
VERIFY_SIZE = True  # 是否验证文件大小
