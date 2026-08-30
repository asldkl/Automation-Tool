# -*- coding: utf-8 -*-
"""
屏幕透明遮罩日志组件 (PyQt6)

功能特性：
  1. 无边框、置顶、背景透明；默认鼠标穿透（不影响下层游戏），交互模式可拖动
  2. QPlainTextEdit 日志容器：Consolas 等宽字体、背景透明或半透明
  3. 分级彩色日志：DEBUG 灰 / INFO 浅蓝 / WARN 黄 / ERROR 红，自动附加时间戳
  4. 外部接口 add_log(level, message) + 快捷方法 debug/info/warn/error
  5. 日志自动滚动到底部，最大行数可配置，超出自动清除最早日志
  6. 严格线程安全：使用 Qt 信号槽，子线程仅 emit，UI 更新在主线程槽函数
  7. 交互模式下：按住左键拖动窗口，双击切换回穿透模式

依赖安装：
    pip install PyQt6

运行 Demo：
    python screen_log_overlay.py

嵌入项目：
    from screen_log_overlay import ScreenLogOverlay, LogLevel
    overlay = ScreenLogOverlay(max_lines=500)
    overlay.show()
    overlay.add_log(LogLevel.INFO, "自动化任务启动")
    overlay.error("识别匹配失败")

注意事项：
    - 游戏需为窗口化 / 无边框模式；独占全屏会遮挡顶层遮罩
    - 鼠标穿透模式下窗口不接收输入；切换交互模式通过 set_input_transparent()
"""

from __future__ import annotations

import threading
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QPoint
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QVBoxLayout, QWidget


# ==================== 日志级别枚举 ====================
class LogLevel:
    """日志等级：数值 + 显示颜色 + 前缀标签"""
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

    # 等级 -> 颜色
    COLORS = {
        DEBUG: "#909090",   # 灰色
        INFO:  "#7ED3F5",   # 浅蓝
        WARN:  "#FFD54A",   # 黄色
        ERROR: "#FF5252",   # 红色
    }
    # 等级 -> 前缀标签
    LABELS = {
        DEBUG: "DBG",
        INFO:  "INF",
        WARN:  "WRN",
        ERROR: "ERR",
    }


# ==================== 主组件类 ====================
class ScreenLogOverlay(QWidget):
    """
    屏幕透明遮罩日志组件。

    线程安全设计（重要）：
      - log_signal 为类级别 Qt 信号
      - add_log() 从任意线程调用，内部仅执行 signal.emit(...)
      - 槽函数 _on_log 由 Qt 事件循环在主线程调度执行，更新 UI 控件
      - 因此子线程绝不直接操作 QPlainTextEdit，杜绝跨线程崩溃
    """

    # Qt 信号：日志提交通道（int=等级, str=消息）
    log_signal = pyqtSignal(int, str)
    # 顶行状态文本通道（线程安全）
    status_signal = pyqtSignal(str)
    # 实时鼠标坐标文本通道（线程安全，供校准滑块区域用）
    mouse_signal = pyqtSignal(str)

    def __init__(self, max_lines: int = 500,
                 pos: QPoint | None = None,
                 width: int = 420, height: int = 200,
                 translucent_bg: bool = False,
                 parent: QWidget | None = None):
        """
        Args:
            max_lines: 最大日志行数，超出自动清除最早日志（默认 500）
            pos: 窗口初始坐标；None 时自动放到屏幕左下角
            width / height: 窗口初始尺寸
            translucent_bg: True = 半透明黑色底板；False(默认) = 背景完全透明，
                            仅显示彩色日志文字，不遮挡下方游戏画面
            parent: 父窗口，默认 None（作为独立顶层窗口）
        """
        super().__init__(parent)
        self._max_lines = max(50, int(max_lines))
        self._transparent_input = True     # 当前是否鼠标穿透
        self._dragging = False             # 是否正在拖动窗口
        self._drag_offset = QPoint()       # 拖动时鼠标与窗口左上角偏移
        self._allow_close = False          # 是否允许关闭（仅程序主动关闭时 True）
                                           # 防止运行中游戏关闭后 alt+F4 误关遮罩

        # ---------- 窗口属性：无边框 + 置顶 + 不占任务栏 ----------
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint       # 无边框
            | Qt.WindowType.WindowStaysOnTopHint    # 始终置顶
            | Qt.WindowType.Tool                    # 不显示在任务栏
        )
        # 背景透明（配合日志控件，透明或半透明由 translucent_bg 决定）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ---------- 日志容器 ----------
        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)                          # 只读
        self.text_edit.setMaximumBlockCount(self._max_lines)      # 自动限行
        # 隐藏滚动条（日志自动滚动仍有效，只是不显示滚动条）
        self.text_edit.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if translucent_bg:
            # 半透明黑色底板
            bg = "rgba(0, 0, 0, 180)"
        else:
            # 完全透明：无底板，日志文字直接叠加在下方画面上
            bg = "transparent"
        self.text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {bg};
                color: #ffffff;
                border: none;
                padding: 2px;
                font-family: Consolas;                 /* 等宽字体 */
                font-size: 10px;
                font-weight: bold;                     /* 加粗 */
            }}
        """)

        # 布局：顶部固定状态行 + 日志区
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.status_label = QLabel("未运行", self)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #ffd54a;
                font-family: Consolas;
                font-size: 10px;
                font-weight: bold;
                padding: 0px 2px;
                background: transparent;
            }
        """)
        layout.addWidget(self.status_label)
        # 实时鼠标坐标行（方便直接在遮罩上看屏幕坐标）
        self.mouse_label = QLabel("🖱️ (0, 0)", self)
        self.mouse_label.setStyleSheet("""
            QLabel {
                color: #7ED3F5;
                font-family: Consolas;
                font-size: 10px;
                font-weight: bold;
                padding: 0px 2px;
                background: transparent;
            }
        """)
        layout.addWidget(self.mouse_label)
        layout.addWidget(self.text_edit)
        self.setLayout(layout)

        # 窗口尺寸与位置
        self.resize(width, height)
        self._corner_index = 0   # 0=左下 1=右下 2=右上 3=左上（逆时针）
        if pos is not None:
            self.move(pos)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(*self._corner_pos(screen, 0))

        # ---------- 信号槽连接（线程安全核心） ----------
        self.log_signal.connect(self._on_log)
        self.status_signal.connect(self._on_status)
        self.mouse_signal.connect(self._on_mouse)

        # 事件过滤器：交互模式下拦截日志控件鼠标事件实现拖动
        self.text_edit.installEventFilter(self)

        # 应用初始鼠标穿透设置
        self.set_input_transparent(True)

    # ==================================================
    # 对外公开接口（任意线程可调用）
    # ==================================================
    def add_log(self, level: int, message: str) -> None:
        """
        输出一条彩色日志（线程安全）。

        Args:
            level: LogLevel.DEBUG / INFO / WARN / ERROR
            message: 日志内容
        """
        if not isinstance(message, str):
            message = str(message)
        # 仅发送信号，不直接操作控件；跨线程安全
        self.log_signal.emit(level, message)

    def debug(self, message): self.add_log(LogLevel.DEBUG, message)
    def info(self, message):  self.add_log(LogLevel.INFO,  message)
    def warn(self, message):  self.add_log(LogLevel.WARN,  message)
    def error(self, message): self.add_log(LogLevel.ERROR, message)

    def set_input_transparent(self, transparent: bool) -> None:
        """
        切换鼠标穿透 / 可拖动交互模式。
        True = 鼠标穿透（默认），点击穿透到下层，不影响游戏；不可拖动
        False = 交互模式，可按住左键拖动窗口
        窗口标志变更后必须重新 show() 才生效。
        """
        self._transparent_input = bool(transparent)
        flag = Qt.WindowType.WindowTransparentForInput
        if transparent:
            self.setWindowFlag(flag, True)
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        else:
            self.setWindowFlag(flag, False)
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.show()

    def toggle_input_transparent(self) -> None:
        """F8：切换穿透 / 交互模式"""
        self.set_input_transparent(not self._transparent_input)

    def toggle_visibility(self) -> None:
        """F9：显示 / 隐藏遮罩窗口"""
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def clear_logs(self) -> None:
        """清空日志（注意：须在主线程调用，或通过信号转发）"""
        self.text_edit.clear()

    def set_status_text(self, text: str) -> None:
        """更新顶行状态文本（线程安全，内部走 Qt 信号）"""
        self.status_signal.emit(str(text))

    def set_mouse_text(self, text: str) -> None:
        """更新实时鼠标坐标文本（线程安全，内部走 Qt 信号）"""
        self.mouse_signal.emit(str(text))

    def cycle_corner(self, corner_index: int | None = None) -> int:
        """按 左下→右下→右上→左上→左下 逆时针旋转遮罩角落；
        corner_index 指定则直接跳转到该角落。返回当前角落索引(0-3)"""
        if corner_index is not None:
            self._corner_index = int(corner_index) % 4
        else:
            self._corner_index = (self._corner_index + 1) % 4
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(*self._corner_pos(screen, self._corner_index))
        return self._corner_index

    @property
    def corner_index(self) -> int:
        return self._corner_index

    def _corner_pos(self, screen, idx: int) -> tuple:
        """计算指定角落的窗口左上角坐标"""
        margin = 12
        if idx == 0:      # 左下
            return screen.left() + margin, screen.bottom() - self.height() - margin
        if idx == 1:      # 右下
            return screen.right() - self.width() - margin, screen.bottom() - self.height() - margin
        if idx == 2:      # 右上
            return screen.right() - self.width() - margin, screen.top() + margin
        return screen.left() + margin, screen.top() + margin   # 左上

    # ==================================================
    # 主线程槽函数（禁止子线程直接调用，由信号触发）
    # ==================================================
    def _on_log(self, level: int, message: str) -> None:
        """槽函数：在主线程向日志面板追加一条彩色日志"""
        color = LogLevel.COLORS.get(level, "#ffffff")
        label = LogLevel.LABELS.get(level, "LOG")
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 定位到文本末尾
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 设置当前插入颜色
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)

        # 插入带时间戳的日志行
        cursor.insertText(f"[{timestamp}][{label}] {message}\n")
        self.text_edit.setTextCursor(cursor)

        # 自动滚动到底部
        self._scroll_to_bottom()

    def _on_status(self, text: str) -> None:
        """槽函数：主线程更新顶行状态文本"""
        self.status_label.setText(str(text))

    def _on_mouse(self, text: str) -> None:
        """槽函数：主线程更新实时鼠标坐标文本"""
        self.mouse_label.setText(str(text))

    def _scroll_to_bottom(self) -> None:
        """滚动到日志末尾（配合 setMaximumBlockCount 自动清理旧行）"""
        sb = self.text_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ==================================================
    # 窗口拖动（仅在交互模式生效；穿透模式下收不到鼠标事件）
    # ==================================================
    def eventFilter(self, obj, event) -> bool:
        """拦截日志控件的鼠标事件，在交互模式下实现窗口拖动"""
        if obj is self.text_edit and not self._transparent_input:
            etype = event.type()
            if (etype == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
                self._dragging = True
                return True   # 拦截，避免选中文本
            elif etype == QEvent.Type.MouseMove and self._dragging:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            elif etype == QEvent.Type.MouseButtonRelease:
                self._dragging = False
                return True
        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event) -> None:
        """双击遮罩：切换鼠标穿透 / 可拖动交互模式（交互模式按住左键可拖动）"""
        self.toggle_input_transparent()
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event) -> None:
        """免疫系统关闭事件（alt+F4 / WM_CLOSE）
        运行中游戏关闭后，置顶的遮罩可能成为前台窗口被下一次 alt+F4 误关；
        遮罩是常驻工具窗口，仅允许程序主动关闭（disable_log_overlay 置 _allow_close=True）"""
        if self._allow_close:
            event.accept()
        else:
            event.ignore()


# ==================================================
# 可运行 Demo：双线程模拟业务调用，验证多线程安全
# ==================================================
if __name__ == "__main__":
    import sys
    import time
    import random

    app = QApplication(sys.argv)

    # 创建遮罩日志组件
    overlay = ScreenLogOverlay(max_lines=500)
    overlay.show()

    # 主线程演示各级别日志（含时间戳）
    overlay.info("遮罩日志组件已启动 (PyQt6)")
    overlay.debug("DEBUG 灰色日志")
    overlay.info("INFO 浅蓝日志")
    overlay.warn("WARN 黄色日志")
    overlay.error("ERROR 红色日志")
    overlay.info("按 F8 切换穿透/拖动，F9 显示/隐藏")

    # 子线程模拟业务调用（验证线程安全）
    stop_event = threading.Event()

    def worker(name: str) -> None:
        """后台工作线程：周期性输出随机级别日志"""
        levels = [LogLevel.DEBUG, LogLevel.INFO,
                  LogLevel.WARN, LogLevel.ERROR]
        messages = [
            f"worker-{name} 处理任务...",
            f"worker-{name} 读取配置成功",
            f"worker-{name} 检测到异常",
            f"worker-{name} 操作失败，重试中",
        ]
        while not stop_event.is_set():
            overlay.add_log(random.choice(levels),
                            random.choice(messages))
            time.sleep(0.3)

    threading.Thread(target=worker, args=("A",), daemon=True).start()
    threading.Thread(target=worker, args=("B",), daemon=True).start()

    # 演示：5 秒后清空日志一次
    def demo_clear() -> None:
        overlay.clear_logs()
        overlay.info("日志已清空（演示）")

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(5000, demo_clear)

    app.aboutToQuit.connect(stop_event.set)
    sys.exit(app.exec())
