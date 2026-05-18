# 三角洲行动自动化工具

基于图像识别的《三角洲行动》游戏日常自动化工具，支持 QQ 登录 + WeGame 快捷登录、多账号管理、定时执行、电源管理等功能。

## 功能特性

- **游戏内自动化** — 自动完成科技中心、工具台、护甲站、医疗站的生产/制作/领取
- **QQ 自动登录 + WeGame 快捷登录** — 多账号自动切换，完整自动化链路
- **定时执行** — 单次/每日循环，支持多个时间点，可设置运行前提醒
- **模板上传** — 在设置中可上传自定义模板图片，替换内置模板
- **系统托盘** — 静默运行，后台执行任务
- **电源管理** — 唤醒电脑、自动关机、定时开机
- **邮件通知** — 执行完成后自动发送运行结果到邮箱
- **开机自启动** — 登录 Windows 时自动运行，可选立即执行任务
- **联网时间校验** — 启动时验证有效期
- **单实例保护** — 重复启动自动激活已有窗口

## 系统要求

- Windows 10 / 11
- Python 3.8+

## 安装与运行

```bash
pip install opencv-python numpy pyautogui psutil pywin32 pystray pillow
python main.py
```

打包为 exe：
```bash
pip install pyinstaller
pyinstaller 三角洲自动工具.spec
```

## 使用说明

1. 添加 QQ 账号截图，配置 QQ/WeGame 路径
2. 勾选需要自动执行的操作
3. 点击「开始运行」手动执行，或在设置中启用定时执行
4. 在「图像识别设置」中点击「上传模板图片」可替换内置模板，点击「恢复默认」可还原

### 运行流程

清理进程 → 逐个账号：启动 QQ 登录 → 关闭 QQ → 启动 WeGame 快捷登录 → 进入游戏执行操作 → 关闭游戏和 WeGame → 完成

## 配置说明

用户配置：`~/.delta_auto_settings.json`，账号列表：`~/.delta_auto_accounts.json`，自定义模板：`~/.delta_auto_templates/`

| 配置项 | 说明 |
|--------|------|
| `wegame_path` / `qq_path` | WeGame / QQ 启动路径 |
| `confidence` | 图像匹配置信度（默认 0.7） |
| `run_mode` | 运行模式：单次 / 每日循环 |
| `schedule_times` | 定时执行时间列表 |
| `selected_operations` | 选中的自动操作 |
| `silent_mode` | 静默运行（托盘） |
| `wake_enabled` | 运行前唤醒电脑 |
| `auto_shutdown_enabled` | 自动关机 |
| `run_on_startup` | 开机立即运行 |
| `email_enabled` / `smtp_code` | 邮件通知配置 |
| `qq_mouse_move_distance` | QQ 账号列表鼠标下移距离 |
| `scroll_amount` | 滚动幅度（50-150） |
| `game_launch_wait` | 游戏启动等待时间（秒） |

## 技术栈

Tkinter / OpenCV / PyAutoGUI / psutil / pywin32 / pystray+Pillow / PyInstaller

## 注意事项

- 运行时请勿遮挡屏幕
- 建议 1920x1080 100% 缩放，识别失败可降低置信度
- 电源管理需管理员权限
- 有效期至 2026 年 7 月 1 日

## 免责声明

本工具仅供个人学习研究使用，请勿用于违反游戏用户协议的行为。
