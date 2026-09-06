import subprocess
import sys
import ctypes
import time as time_module
from pathlib import Path

import pyautogui
import win32con
import win32gui

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import adapter
from core import config_manager as cfg

_BG = "#1c1c1e"
_CARD = "#2c2c2e"
_BORDER = "#38383a"
_TXT = "#f5f5f7"
_TXT2 = "#98989d"
_BLUE = "#0a84ff"
_GREEN = "#30d158"

_CURRENT_PYTHON = Path(sys.executable)
PYTHON = str(
    _CURRENT_PYTHON.with_name("pythonw.exe")
    if _CURRENT_PYTHON.with_name("pythonw.exe").exists()
    else _CURRENT_PYTHON
)

APP_DIR = Path(__file__).resolve().parent.parent
CALIBRATE_PY = APP_DIR / "calibrate.py"

STEPS = [
    {"id": "input_box", "title": "第一步：ChatGPT 输入框", "desc": "记录 ChatGPT 网页输入框的点击位置"},
    {"id": "trigger", "title": "第二步：回复完成图标", "desc": "标定 ChatGPT 回复完成后稳定出现的图标"},
    {"id": "bottom", "title": "第三步：到底按钮", "desc": "标定 ChatGPT 页面底部的「到底」按钮"},
    {"id": "copy", "title": "第四步：复制回复按钮", "desc": "标定 ChatGPT 最后一条回复的复制按钮"},
]


class CalibrationDialog(QDialog):
    def __init__(self, parent=None, endpoint: str = adapter.DEFAULT_ENDPOINT):
        super().__init__(parent)
        self.setWindowTitle("标定流程")
        self.setFixedSize(520, 660)

        self._endpoint = endpoint if endpoint in adapter.endpoints() else adapter.DEFAULT_ENDPOINT
        self._process: subprocess.Popen | None = None
        self._current_step = 0
        self._continue_flow = False

        self._setup_ui()
        self._refresh_steps()
        self._update_button_text()

    def _setup_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: {_BG};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("标定流程")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {_TXT};")
        layout.addWidget(title)

        ep_label = QLabel("标定对象：ChatGPT 网页")
        ep_label.setAlignment(Qt.AlignCenter)
        ep_label.setStyleSheet(f"font-size: 13px; color: {_BLUE}; margin-bottom: 2px;")
        layout.addWidget(ep_label)

        desc = QLabel("按顺序标定，每步完成后自动进入下一步")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet(f"font-size: 13px; color: {_TXT2}; margin-bottom: 4px;")
        layout.addWidget(desc)

        self._step_widgets = []
        for i, step in enumerate(STEPS):
            card = self._build_step_card(i, step)
            self._step_widgets.append(card)
            layout.addWidget(card)

        layout.addStretch()

        self._btn_action = QPushButton("启动标定程序")
        self._btn_action.setStyleSheet(f"""
            QPushButton {{
                background: {_BLUE}; color: white; border: none;
                border-radius: 12px; padding: 14px; font-size: 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #0066d6; }}
            QPushButton:disabled {{ background: #48484a; color: {_TXT2}; }}
        """)
        self._btn_action.clicked.connect(self._on_action)
        layout.addWidget(self._btn_action)

        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD}; color: {_BLUE}; border: none;
                border-radius: 10px; padding: 12px; font-size: 15px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #38383a; }}
        """)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _build_step_card(self, index: int, step: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("step_card")
        card.setStyleSheet(f"""
            QFrame#step_card {{
                background: {_CARD};
                border-radius: 12px;
                border: 1px solid {_BORDER};
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QLabel(step["title"])
        header.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {_TXT};")
        layout.addWidget(header)

        desc = QLabel(step["desc"])
        desc.setStyleSheet(f"font-size: 12px; color: {_TXT2};")
        layout.addWidget(desc)

        status_row = QHBoxLayout()
        status = QLabel("⏳ 未开始")
        status.setObjectName(f"step_status_{index}")
        status.setStyleSheet(f"font-size: 13px; color: {_TXT2}; margin-top: 4px;")
        status_row.addWidget(status)
        status_row.addStretch()

        retry = QPushButton("单独重标")
        retry.setStyleSheet(f"""
            QPushButton {{
                background: {_BORDER}; color: {_BLUE}; border: none;
                border-radius: 7px; padding: 6px 10px; font-size: 12px;
            }}
            QPushButton:hover {{ background: #48484a; }}
        """)
        retry.clicked.connect(lambda _checked=False, i=index: self._calibrate_step(i, False))
        status_row.addWidget(retry)
        layout.addLayout(status_row)

        return card

    def _refresh_steps(self):
        config = cfg.load()
        targets = adapter.resolve_targets(config, self._endpoint)
        status = {
            "trigger": "trigger" in targets and targets["trigger"].get("w", 0) > 0,
            "bottom": "bottom" in targets and targets["bottom"].get("w", 0) > 0,
            "copy": "copy" in targets and targets["copy"].get("w", 0) > 0,
            "input_box": "input_box" in targets and targets["input_box"].get("click_x", 0) > 0,
        }
        for i, step in enumerate(STEPS):
            done = status.get(step["id"], False)
            status_label = self._step_widgets[i].findChild(QLabel, f"step_status_{i}")
            if status_label:
                if done:
                    status_label.setText("✅ 已完成")
                    status_label.setStyleSheet(f"font-size: 13px; color: {_GREEN}; margin-top: 4px;")
                else:
                    status_label.setText("⏳ 未配置")
                    status_label.setStyleSheet(f"font-size: 13px; color: {_TXT2}; margin-top: 4px;")
        self._update_button_text()

    def _on_action(self):
        self._start_next_missing()

    def _status(self) -> dict[str, bool]:
        config = cfg.load()
        targets = adapter.resolve_targets(config, self._endpoint)
        return {
            "trigger": "trigger" in targets and targets["trigger"].get("w", 0) > 0,
            "bottom": "bottom" in targets and targets["bottom"].get("w", 0) > 0,
            "copy": "copy" in targets and targets["copy"].get("w", 0) > 0,
            "input_box": "input_box" in targets and targets["input_box"].get("click_x", 0) > 0,
        }

    def _start_next_missing(self):
        status = self._status()
        for i, step in enumerate(STEPS):
            if not status.get(step["id"], False):
                self._calibrate_step(i, True)
                break
        else:
            self._refresh_steps()
            QMessageBox.information(self, "完成", "全部标定已完成。如需修正，请点击对应项目的“单独重标”。")

    def _calibrate_step(self, step_idx: int, continue_flow: bool):
        if self._process is not None:
            QMessageBox.warning(self, "正在标定", "请先完成当前标定步骤。")
            return
        step = STEPS[step_idx]
        self._continue_flow = continue_flow

        if step["id"] == "input_box":
            self._calibrate_input()
            return

        if not CALIBRATE_PY.exists():
            QMessageBox.warning(self, "错误", f"未找到 calibrate.py ({CALIBRATE_PY})")
            return

        self._btn_action.setEnabled(False)
        self._btn_action.setText(f"正在标定：{step['title']}...")

        try:
            self._process = subprocess.Popen(
                [PYTHON, str(CALIBRATE_PY), "--endpoint", self._endpoint, "--step", step["id"]],
            )
            return_code = self._process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, self._process.args)
            self._refresh_steps()
            completed = self._status().get(step["id"], False)
            if continue_flow and completed:
                QTimer.singleShot(0, self._start_next_missing)
        except subprocess.CalledProcessError as e:
            QMessageBox.warning(self, "错误", f"标定程序异常退出 (代码 {e.returncode})")
        except FileNotFoundError:
            QMessageBox.warning(self, "错误", f"未找到 Python: {PYTHON}")
        finally:
            self._process = None
            self._btn_action.setEnabled(True)
            self._update_button_text()

    def _update_button_text(self):
        config = cfg.load()
        targets = adapter.resolve_targets(config, self._endpoint)
        status = {
            "trigger": "trigger" in targets and targets["trigger"].get("w", 0) > 0,
            "bottom": "bottom" in targets and targets["bottom"].get("w", 0) > 0,
            "copy": "copy" in targets and targets["copy"].get("w", 0) > 0,
            "input_box": "input_box" in targets and targets["input_box"].get("click_x", 0) > 0,
        }
        for i, step in enumerate(STEPS):
            if not status.get(step["id"], False):
                if step["id"] == "input_box":
                    self._btn_action.setText("标定输入框")
                else:
                    self._btn_action.setText(f"启动标定程序")
                return
        self._btn_action.setText("全部已完成，请按项目单独重标")
        self._btn_action.setEnabled(False)

    def _calibrate_input(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("标定输入框")
        msg.setText("请将鼠标移动到 ChatGPT 输入框位置\n\n点击「确定」后将在 3 秒后自动记录鼠标位置")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        if msg.exec() != QMessageBox.Ok:
            return

        self._btn_action.setEnabled(False)
        self._btn_action.setText("3...")

        count = [3]

        def tick():
            count[0] -= 1
            if count[0] > 0:
                self._btn_action.setText(f"{count[0]}...")
            else:
                timer.stop()
                x, y = pyautogui.position()
                self._save_input_position(x, y)

        timer = QTimer(self)
        timer.timeout.connect(tick)
        timer.start(1000)

    def _save_input_position(self, x: int, y: int):
        config = cfg.load()
        ns = config.setdefault("surfaces", {}).setdefault(self._endpoint, {})
        ns["input_box"] = {
            "x": x - 150,
            "y": y - 10,
            "w": 300,
            "h": 40,
            "click_x": x,
            "click_y": y,
        }
        hwnd = win32gui.WindowFromPoint((x, y))
        root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        config.setdefault("surface_meta", {})[self._endpoint] = {
            "window_class": win32gui.GetClassName(root),
            "window_title": win32gui.GetWindowText(root),
            "window_rect": list(win32gui.GetWindowRect(root)),
            "dpi": int(ctypes.windll.user32.GetDpiForWindow(root)),
        }
        cfg.save(config)

        self._btn_action.setEnabled(True)
        self._btn_action.setText("启动标定程序")
        self._refresh_steps()
        QMessageBox.information(
            self, "完成",
            f"输入框位置已记录 (click=({x}, {y}))\n如位置不准可重新标定"
        )
        if self._continue_flow:
            QTimer.singleShot(0, self._start_next_missing)
