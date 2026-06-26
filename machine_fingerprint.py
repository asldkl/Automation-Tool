"""
机器指纹模块
通过提取电脑硬盘和主板的唯一序列号生成哈希值作为"机器指纹"
用于防复制/防滥用，确保软件只能在指定电脑上运行
"""
import hashlib
import subprocess
import platform
import uuid


def _get_wmic_value(cmd):
    """执行 WMIC 命令并提取返回值（兼容无 wmic 的系统）"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        lines = result.stdout.strip().split('\n')
        # WMIC 输出第一行是标题，第二行开始是值
        for line in lines[1:]:
            value = line.strip()
            if value and value not in ('(null)', 'To Be Filled By O.E.M.', 'Default string', ''):
                return value
    except Exception:
        pass
    return None


def _get_wmi_value_powershell(class_name, property_name):
    """通过 PowerShell WMI 获取硬件属性（兼容 Windows 11 无 wmic 的情况）"""
    try:
        ps_cmd = f"Get-WmiObject {class_name} | Select-Object -ExpandProperty {property_name}"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        value = result.stdout.strip()
        if value and value not in ('(null)', 'To Be Filled By O.E.M.', 'Default string', ''):
            return value
    except Exception:
        pass
    return None


def _get_disk_serial():
    """获取硬盘序列号"""
    serial = _get_wmic_value(["wmic", "diskdrive", "get", "serialnumber"])
    if not serial:
        serial = _get_wmi_value_powershell("Win32_DiskDrive", "SerialNumber")
    return serial


def _get_baseboard_serial():
    """获取主板序列号"""
    serial = _get_wmic_value(["wmic", "baseboard", "get", "serialnumber"])
    if not serial:
        serial = _get_wmi_value_powershell("Win32_BaseBoard", "SerialNumber")
    return serial


def _get_fallback_id():
    """降级方案：使用主机名 + MAC 地址生成指纹"""
    node = platform.node()
    mac = uuid.getnode()
    raw = f"{node}:{mac}"
    return raw


def get_machine_id():
    """
    获取机器指纹（唯一标识一台电脑）
    组合硬盘序列号 + 主板序列号，计算 SHA256 哈希
    返回 32 位十六进制字符串
    """
    disk_serial = _get_disk_serial()
    board_serial = _get_baseboard_serial()

    if disk_serial or board_serial:
        # 至少获取到一个硬件序列号
        raw = f"{disk_serial or 'UNKNOWN'}:{board_serial or 'UNKNOWN'}"
    else:
        # 两个都没获取到，使用降级方案
        raw = _get_fallback_id()

    fingerprint = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]
    return fingerprint


def get_machine_info():
    """获取机器指纹及来源信息（调试用）"""
    disk_serial = _get_disk_serial()
    board_serial = _get_baseboard_serial()
    machine_id = get_machine_id()

    return {
        "machine_id": machine_id,
        "disk_serial": disk_serial or "(无法获取)",
        "board_serial": board_serial or "(无法获取)",
        "source": "hardware" if (disk_serial or board_serial) else "fallback"
    }


if __name__ == "__main__":
    info = get_machine_info()
    print(f"机器指纹: {info['machine_id']}")
    print(f"硬盘序列号: {info['disk_serial']}")
    print(f"主板序列号: {info['board_serial']}")
    print(f"来源: {info['source']}")
