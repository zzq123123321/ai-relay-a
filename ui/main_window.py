import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import adapter, protocol
from core import config_manager as cfg
from core import forward as fwd
from core.clipboard_listener import ClipboardListener
from core.window_activator import send_to_input

_CURRENT_PYTHON = Path(sys.executable)
PYTHON = str(
    _CURRENT_PYTHON.with_name("python.exe")
    if _CURRENT_PYTHON.name.lower() == "pythonw.exe"
    else _CURRENT_PYTHON
)

APP_DIR = Path(__file__).resolve().parent.parent

STATUS_ICONS = {"ready": "🟢", "error": "🔴", "waiting": "⚪", "done": "✅", "pause": "⏸️"}

# Dark mode palette
_BG = "#1c1c1e"
_CARD = "#2c2c2e"
_BORDER = "#38383a"
_TXT = "#f5f5f7"
_TXT2 = "#98989d"
_GREEN = "#30d158"
_RED = "#ff453a"
_BLUE = "#0a84ff"
_ORANGE = "#ff9f0a"

EVENT_MAP = {
    "检测到回复完成图标": "回复检测",
    "回复完成图标已变化，确认开始执行": "执行确认",
    "回复完成图标未变化，重新执行发送": "执行重试",
    "找到到底按钮": "页面定位",
    "点击到底按钮": "页面定位",
    "找到复制回复按钮": "复制功能",
    "收到完成指令，自动联动停止": "流程完成",
}

CONF_EVENT_MAP = {
    "检测到回复完成图标": "trigger",
    "回复完成图标已变化，确认开始执行": "trigger",
    "找到到底按钮": "bottom",
    "找到复制回复按钮": "copy",
}

STATE_LABEL_MAP = {
    "等待检测": "等待检测",
    "正在检测回复": "正在检测回复",
    "正在定位页面": "正在定位页面",
    "正在复制回复": "正在复制回复",
}


def _make_row(left_text: str, right_widget: QWidget) -> QWidget:
    row = QWidget()
    row.setFixedHeight(36)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(16, 0, 16, 0)
    label = QLabel(left_text)
    label.setStyleSheet(f"font-size: 15px; color: {_TXT};")
    layout.addWidget(label)
    layout.addStretch()
    layout.addWidget(right_widget)
    return row


def _make_divider() -> QFrame:
    div = QFrame()
    div.setFixedHeight(1)
    div.setStyleSheet(f"background: {_BORDER};")
    return div


def _status_label(text: str, color: str = _TXT2) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(f"font-size: 15px; color: {color};")
    return lb


class _Card(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {_CARD};
                border-radius: 12px;
                border: 1px solid {_BORDER};
            }}
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add_row(self, left_text: str, right_widget: QWidget):
        if self._layout.count() > 0:
            self._layout.addWidget(_make_divider())
        self._layout.addWidget(_make_row(left_text, right_widget))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Relay 桌面端")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setFixedSize(440, 620)

        self._process: QProcess | None = None
        self._output_buffer = ""
        self._current_task_id = ""
        self._current_round = 0
        self._max_rounds = protocol.DEFAULT_MAX_ROUNDS
        self._conf_map: dict[str, float] = {}

        self._clipboard_listener = ClipboardListener(self)
        self._clipboard_listener.response_received.connect(self._on_response)
        self._clipboard_listener.diagnostic_received.connect(self._on_diagnostic)
        self._clipboard_listener.protocol_error.connect(
            lambda error: self._append_log("协议错误", error)
        )

        self._setup_ui()
        self._refresh_config_status()

    def _setup_ui(self):
        self.setStyleSheet(f"QMainWindow {{ background: {_BG}; }}")

        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"background: {_BG};")
        self.setCentralWidget(central)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }}"
                             f"QScrollBar:vertical {{ width: 0; }}")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._main_layout = QVBoxLayout(content)
        self._main_layout.setContentsMargins(16, 20, 16, 20)
        self._main_layout.setSpacing(12)

        self._add_header()
        self._add_config_section()
        self._add_current_state_section()
        self._add_detail_status_section()
        self._add_log_section()
        self._add_buttons()

        scroll.setWidget(content)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _add_header(self):
        header = QLabel("AI Relay")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {_TXT};")
        self._main_layout.addWidget(header)

    def _add_config_section(self):
        sec = QLabel("配置状态")
        sec.setStyleSheet(f"font-size: 13px; color: {_TXT2}; font-weight: 600; margin-left: 4px;")
        self._main_layout.addWidget(sec)

        self._card_config = _Card()

        self._lbl_trigger = _status_label("未配置", _RED)
        self._card_config.add_row("回复完成图标", self._lbl_trigger)

        self._lbl_bottom = _status_label("未配置", _RED)
        self._card_config.add_row("到底按钮", self._lbl_bottom)

        self._lbl_copy = _status_label("未配置", _RED)
        self._card_config.add_row("复制回复按钮", self._lbl_copy)

        self._lbl_input = _status_label("未配置", _RED)
        self._card_config.add_row("输入框", self._lbl_input)

        self._main_layout.addWidget(self._card_config)

    def _add_current_state_section(self):
        sec = QLabel("当前状态")
        sec.setStyleSheet(f"font-size: 13px; color: {_TXT2}; font-weight: 600; margin-left: 4px;")
        self._main_layout.addWidget(sec)

        card = QFrame()
        card.setObjectName("state_card")
        card.setStyleSheet(f"""
            QFrame#state_card {{
                background: {_CARD};
                border-radius: 12px;
                border: 1px solid {_BORDER};
                padding: 16px;
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)

        self._lbl_state = QLabel(f"{STATUS_ICONS['waiting']} 等待运行")
        self._lbl_state.setAlignment(Qt.AlignCenter)
        self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_TXT2};")
        lay.addWidget(self._lbl_state)

        self._main_layout.addWidget(card)

    def _add_detail_status_section(self):
        sec = QLabel("运行状态")
        sec.setStyleSheet(f"font-size: 13px; color: {_TXT2}; font-weight: 600; margin-left: 4px;")
        self._main_layout.addWidget(sec)

        self._card_status = _Card()

        self._lbl_reply = _status_label(f"{STATUS_ICONS['waiting']} 等待运行", _TXT2)
        self._card_status.add_row("回复检测", self._lbl_reply)

        self._lbl_page = _status_label(f"{STATUS_ICONS['waiting']} 等待运行", _TXT2)
        self._card_status.add_row("页面定位", self._lbl_page)

        self._lbl_copy_status = _status_label(f"{STATUS_ICONS['waiting']} 等待运行", _TXT2)
        self._card_status.add_row("复制功能", self._lbl_copy_status)

        self._lbl_clipboard = _status_label(f"{STATUS_ICONS['waiting']} 等待运行", _TXT2)
        self._card_status.add_row("剪贴板", self._lbl_clipboard)

        self._lbl_confidence = _status_label("--", _TXT2)
        self._card_status.add_row("识别率", self._lbl_confidence)

        self._main_layout.addWidget(self._card_status)

    def _add_log_section(self):
        sec = QLabel("最近操作")
        sec.setStyleSheet(f"font-size: 13px; color: {_TXT2}; font-weight: 600; margin-left: 4px;")
        self._main_layout.addWidget(sec)

        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFixedHeight(90)
        self._log_area.setStyleSheet(f"""
            QTextEdit {{
                background: {_CARD};
                border: 1px solid {_BORDER};
                border-radius: 12px;
                font-size: 12px;
                color: {_TXT};
                padding: 12px;
            }}
        """)
        self._main_layout.addWidget(self._log_area)

    def _add_buttons(self):
        btn_cal = QPushButton("开始标定")
        btn_cal.setStyleSheet(f"""
            QPushButton {{
                background: {_BLUE}; color: white; border: none;
                border-radius: 10px; padding: 10px; font-size: 14px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #0066d6; }}
        """)
        btn_cal.clicked.connect(self._on_calibrate)

        self._btn_run = QPushButton("运行")
        self._btn_run.setStyleSheet(f"""
            QPushButton {{
                background: {_GREEN}; color: white; border: none;
                border-radius: 10px; padding: 10px; font-size: 14px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #28a745; }}
        """)
        self._btn_run.clicked.connect(self._on_run)

        self._btn_stop = QPushButton("停止")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet(f"""
            QPushButton {{
                background: {_RED}; color: white; border: none;
                border-radius: 10px; padding: 10px; font-size: 14px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #d63031; }}
            QPushButton:disabled {{ background: #48484a; color: {_TXT2}; }}
        """)
        self._btn_stop.clicked.connect(self._on_stop)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        top_row.addWidget(btn_cal)
        top_row.addWidget(self._btn_run)
        top_row.addWidget(self._btn_stop)

        self._main_layout.addLayout(top_row)

        btn_test = QPushButton("测试识别率")
        btn_test.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD}; color: {_TXT}; border: 1px solid {_BORDER};
                border-radius: 10px; padding: 10px; font-size: 14px; font-weight: 500;
            }}
            QPushButton:hover {{ background: #38383a; }}
        """)
        btn_test.clicked.connect(self._on_test_recognition)
        self._main_layout.addWidget(btn_test)

        fwd_sec = QLabel("发送 ChatGPT 任务到执行端")
        fwd_sec.setStyleSheet(f"font-size: 13px; color: {_TXT2}; font-weight: 600; margin-left: 4px;")
        self._main_layout.addWidget(fwd_sec)

        fwd_row = QHBoxLayout()
        fwd_row.setSpacing(12)
        target_label = QLabel("目标：EXECUTOR")
        target_label.setStyleSheet(f"color: {_TXT}; font-size: 14px;")
        fwd_row.addWidget(target_label, 1)

        btn_send = QPushButton("包装并写入剪贴板")
        btn_send.setStyleSheet(f"""
            QPushButton {{
                background: {_BLUE}; color: white; border: none;
                border-radius: 10px; padding: 10px; font-size: 14px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #0066d6; }}
        """)
        btn_send.clicked.connect(self._on_forward)
        fwd_row.addWidget(btn_send)
        self._main_layout.addLayout(fwd_row)

    def _refresh_config_status(self):
        config = cfg.load()
        status = cfg.target_status(config)
        self._set_config_row(self._lbl_trigger, status["trigger"], "trigger")
        self._set_config_row(self._lbl_bottom, status["bottom"], "bottom")
        self._set_config_row(self._lbl_copy, status["copy"], "copy")
        self._set_config_row(self._lbl_input, status["input_box"], "input_box")

    def _set_config_row(self, label: QLabel, configured: bool, key: str = ""):
        if configured:
            conf = self._conf_map.get(key)
            if conf is not None:
                pct = conf * 100
                c = _GREEN if pct >= 85 else _ORANGE if pct >= 70 else _RED
                label.setText(f"已配置 ({pct:.1f}%)")
                label.setStyleSheet(f"font-size: 15px; color: {c}; font-weight: 600;")
            else:
                label.setText("已配置")
                label.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")
        else:
            label.setText("未配置")
            label.setStyleSheet(f"font-size: 15px; color: {_RED}; font-weight: 600;")

    def _on_calibrate(self):
        from ui.calibration import CalibrationDialog
        dlg = CalibrationDialog(self, endpoint=adapter.CHATGPT_SURFACE)
        dlg.exec()
        self._refresh_config_status()

    def _on_test_recognition(self):
        from PySide6.QtWidgets import QMessageBox
        try:
            import cv2
            import numpy as np
            import pyautogui as pg
        except ImportError as e:
            QMessageBox.warning(self, "错误", f"缺少依赖: {e}")
            return

        config = cfg.load()
        endpoint = adapter.CHATGPT_SURFACE
        targets = adapter.resolve_targets(config, endpoint)
        tpl_cfg = adapter.template_map(config, endpoint)

        try:
            screen = pg.screenshot()
            screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"截图失败: {e}")
            return

        results = {}
        for key in ("trigger", "bottom", "copy"):
            if key not in targets:
                continue
            tpl_rel = tpl_cfg.get(key)
            if not tpl_rel:
                continue
            tpl_path = Path(tpl_rel)
            if not tpl_path.exists():
                continue
            try:
                template = cv2.imread(str(tpl_path), cv2.IMREAD_COLOR)
                if template is None:
                    continue
                region = targets[key]
                x, y, w, h = region["x"], region["y"], region["w"], region["h"]
                if h <= 0 or w <= 0:
                    continue
                roi = screen_cv[y : y + h, x : x + w]
                if roi.shape[:2] != template.shape[:2]:
                    roi = cv2.resize(roi, (template.shape[1], template.shape[0]))
                result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                results[key] = float(max_val)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"匹配 {key} 失败: {e}")

        for key, conf in results.items():
            self._conf_map[key] = conf
            label = getattr(self, f"_lbl_{key}", None)
            if label:
                self._set_config_row(label, True, key)
        if results:
            max_conf = max(results.values())
            pct = max_conf * 100
            self._lbl_confidence.setText(f"{pct:.1f}%")
            color = _GREEN if pct >= 85 else _ORANGE if pct >= 70 else _RED
            self._lbl_confidence.setStyleSheet(f"font-size: 15px; color: {color}; font-weight: 600;")

        lines = [f"{k}: {v*100:.1f}%" for k, v in results.items()] or ["无已配置模板"]
        QMessageBox.information(self, f"识别测试结果 [{endpoint}]", "\n".join(lines))

    def _reset_detail_status(self):
        for lbl in (self._lbl_reply, self._lbl_page, self._lbl_copy_status, self._lbl_clipboard):
            lbl.setText(f"{STATUS_ICONS['waiting']} 等待运行")
            lbl.setStyleSheet(f"font-size: 15px; color: {_TXT2};")

    def _on_run(self):
        self._clipboard_listener.start()
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lbl_state.setText(f"{STATUS_ICONS['waiting']} 等待执行端响应")
        self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_TXT2};")
        self._lbl_clipboard.setText(f"{STATUS_ICONS['ready']} 监听中")
        self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_BLUE}; font-weight: 600;")
        self._conf_map.clear()
        self._lbl_confidence.setText("--")
        self._lbl_confidence.setStyleSheet(f"font-size: 15px; color: {_TXT2};")
        self._reset_detail_status()
        self._append_log("启动", "剪贴板监听已启动，等待执行端响应")

    def _on_stop(self):
        self._clipboard_listener.stop()
        if self._process and self._process.state() == QProcess.Running:
            self._process.kill()
            self._process = None
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._lbl_state.setText(f"{STATUS_ICONS['waiting']} 已停止")
        self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_TXT2};")
        self._lbl_clipboard.setText(f"{STATUS_ICONS['waiting']} 已停止")
        self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_TXT2};")
        self._lbl_confidence.setText("--")
        self._lbl_confidence.setStyleSheet(f"font-size: 15px; color: {_TXT2};")
        self._reset_detail_status()
        self._append_log("停止", "已停止")

    def _on_forward(self):
        if self._process and self._process.state() == QProcess.Running:
            self._append_log("忽略", "检测正在进行中，请先停止")
            return
        content = fwd.capture()
        if not content or not content.strip():
            self._lbl_state.setText(f"{STATUS_ICONS['error']} 剪贴板为空")
            self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_RED};")
            self._append_log("失败", "剪贴板为空，无法转发")
            return
        if protocol.is_relay_text(content):
            self._append_log("忽略", "剪贴板中已是 AI Relay 消息，未重复包装")
            return
        wrapped = protocol.wrap_task(content)
        fwd.write_to_clipboard(wrapped)
        self._lbl_clipboard.setText(f"{STATUS_ICONS['done']} 任务已写入")
        self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")
        self._lbl_state.setText(f"{STATUS_ICONS['done']} 等待执行端")
        self._append_log("发送", f"ChatGPT TASK 已写入共享剪贴板 (长度={len(content)})")

    def _on_response(self, message):
        if self._process and self._process.state() == QProcess.Running:
            self._append_log("忙碌", f"已拒绝 task_id={message.message_id}：正在处理上一条响应")
            fwd.write_to_clipboard(protocol.wrap_busy_error(message.message_id))
            return

        endpoint = adapter.CHATGPT_SURFACE
        self._current_task_id = message.message_id
        self._current_round = message.round_number
        self._max_rounds = max(message.max_rounds, protocol.DEFAULT_MAX_ROUNDS)
        self._append_log("响应", f"收到执行结果 task_id={message.message_id}")
        self._lbl_state.setText(f"{STATUS_ICONS['ready']} 收到执行结果")
        self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_ORANGE};")

        config = cfg.load()
        input_box = adapter.resolve_target(config, "input_box", endpoint)
        cx = input_box.get("click_x", 0)
        cy = input_box.get("click_y", 0)
        if cx == 0 or cy == 0:
            self._lbl_state.setText(f"{STATUS_ICONS['error']} 输入框未标定")
            self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_RED};")
            self._append_log("失败", f"[{endpoint}] 输入框未标定，请先标定输入框位置")
            return

        surface_meta = config.get("surface_meta", {}).get(endpoint, {})
        ok, msg = send_to_input(cx, cy, message.content, surface_meta)
        if ok:
            self._clipboard_listener.mark_processed(message.message_id)
            self._lbl_clipboard.setText(f"{STATUS_ICONS['done']} 已发送")
            self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")
            self._lbl_state.setText(f"{STATUS_ICONS['done']} 已发送到 {endpoint}")
            self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_GREEN};")
            self._append_log("发送", f"已粘贴到 ChatGPT 网页 (长度={len(message.content)})")
        else:
            self._lbl_state.setText(f"{STATUS_ICONS['error']} 发送失败")
            self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_RED};")
            self._append_log("失败", msg)
            return

        self._lbl_state.setText(f"{STATUS_ICONS['ready']} 等待回复")
        self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_BLUE};")
        self._append_log("等待", "等待 ChatGPT 生成下一条任务")

        self._start_detection(endpoint=endpoint)

    def _on_diagnostic(self, message):
        config = cfg.load()
        status = cfg.target_status(config)
        report = "\n".join(
            (
                "程序状态：运行中",
                f"监听状态：{'\u6b63\u5e38' if self._clipboard_listener.is_running() else '\u672a\u542f\u52a8'}",
                "配置状态：已加载 schema_version=" + str(config.get("schema_version", "legacy")),
                "标定对象：chatgpt_web",
                "标定项：" + ", ".join(f"{key}={'OK' if value else 'MISSING'}" for key, value in status.items()),
                "协议能力：AI_RELAY/1, AI_RELAY_BEGIN/END",
                "执行软件识别：A端不区分，统一使用 EXECUTOR",
            )
        )
        fwd.write_to_clipboard(protocol.wrap_diagnostic_response(report, message.message_id))
        self._append_log("诊断", f"已回传只读诊断 task_id={message.message_id}")

    def _start_detection(self, endpoint: str = adapter.DEFAULT_ENDPOINT):
        main_py = APP_DIR / "main.py"
        if not main_py.exists():
            self._append_log("错误", "未找到 main.py")
            return

        if self._process and self._process.state() == QProcess.Running:
            return

        self._output_buffer = ""
        self._process = QProcess()
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        if self._current_task_id:
            env.insert("AI_RELAY_TASK_ID", self._current_task_id)
        env.insert("AI_RELAY_ROUND", str(self._current_round))
        env.insert("AI_RELAY_MAX_ROUNDS", str(self._max_rounds))
        self._process.setProcessEnvironment(env)
        self._process.setProgram(PYTHON)
        args = [str(main_py), "--once"]
        if endpoint != adapter.DEFAULT_ENDPOINT:
            args += ["--endpoint", endpoint]
        self._process.setArguments(args)
        self._process.readyReadStandardOutput.connect(self._on_process_output)
        self._process.finished.connect(self._on_process_finished)
        self._process.start()
        self._append_log("检测", f"启动回复检测 endpoint={endpoint}")

    def _on_process_output(self):
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._output_buffer += data

        lines = self._output_buffer.split("\n")
        self._output_buffer = lines.pop() if lines else ""

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    msg = json.loads(line)
                    self._handle_status(msg)
                except json.JSONDecodeError:
                    self._append_log("进程", line)
            elif line.startswith("[") and line.endswith("]"):
                pass
            elif line and not line.startswith("ERROR"):
                pass

    def _handle_status(self, msg: dict):
        msg_type = msg.get("type", "")
        ts = datetime.now().strftime("%H:%M:%S")

        if msg_type == "state":
            state_text = msg.get("state", "")
            if state_text:
                if state_text == "已暂停":
                    color = _TXT2
                    icon = STATUS_ICONS["waiting"]
                    self._lbl_clipboard.setText(f"{STATUS_ICONS['waiting']} 已暂停")
                    self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_TXT2};")
                else:
                    icon = STATUS_ICONS["ready"]
                    color = _BLUE
                self._lbl_state.setText(f"{icon} {state_text}")
                self._lbl_state.setStyleSheet(
                    f"font-size: 17px; font-weight: 600; color: {color};"
                )
                self._append_log("状态", state_text)

        elif msg_type == "event":
            event_text = msg.get("event", "")
            if not event_text:
                return

            confidence = msg.get("confidence")
            if confidence is not None:
                pct = confidence * 100
                self._lbl_confidence.setText(f"{pct:.1f}%")
                color = _GREEN if pct >= 85 else _ORANGE if pct >= 70 else _RED
                self._lbl_confidence.setStyleSheet(
                    f"font-size: 15px; color: {color}; font-weight: 600;"
                )
                conf_key = CONF_EVENT_MAP.get(event_text)
                if conf_key:
                    self._conf_map[conf_key] = confidence
                    label = getattr(self, f"_lbl_{conf_key}", None)
                    if label:
                        self._set_config_row(label, True, conf_key)

            self._lbl_state.setText(f"{STATUS_ICONS['ready']} {event_text}")
            self._lbl_state.setStyleSheet(
                f"font-size: 17px; font-weight: 600; color: {_BLUE};"
            )

            category = EVENT_MAP.get(event_text)
            if category == "回复检测":
                self._lbl_reply.setText(f"{STATUS_ICONS['ready']} 正常")
                self._lbl_reply.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")
            elif category == "页面定位":
                self._lbl_page.setText(f"{STATUS_ICONS['ready']} 正常")
                self._lbl_page.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")
            elif category == "复制功能":
                self._lbl_copy_status.setText(f"{STATUS_ICONS['ready']} 正常")
                self._lbl_copy_status.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")

            if event_text == "复制回复成功":
                length = msg.get("length", 0)
                self._lbl_clipboard.setText(f"{STATUS_ICONS['done']} 已复制")
                self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_GREEN}; font-weight: 600;")
                self._lbl_state.setText(f"{STATUS_ICONS['done']} 复制回复成功")
                self._lbl_state.setStyleSheet(
                    f"font-size: 17px; font-weight: 600; color: {_GREEN};"
                )
                self._append_log("复制", f"复制回复成功, 长度={length}")
            else:
                self._append_log("事件", event_text)

    def _on_process_finished(self):
        self._process = None
        self._lbl_state.setText(f"{STATUS_ICONS['waiting']} 等待执行端响应")
        self._lbl_state.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {_TXT2};")
        self._lbl_clipboard.setText(f"{STATUS_ICONS['ready']} 监听中")
        self._lbl_clipboard.setStyleSheet(f"font-size: 15px; color: {_BLUE}; font-weight: 600;")
        self._conf_map.clear()
        self._lbl_confidence.setText("--")
        self._lbl_confidence.setStyleSheet(f"font-size: 15px; color: {_TXT2};")
        self._reset_detail_status()
        self._append_log("完成", "等待下一条执行端响应")

    def _append_log(self, event: str, detail: str):
        ts = datetime.now().strftime("%H:%M:%S")
        text = detail if event in ("事件", "状态", "复制", "请求", "发送", "失败", "检测", "等待", "启动", "停止", "完成") else f"{event}: {detail}"
        self._log_area.append(f"{ts} {text}")
        scroll = self._log_area.verticalScrollBar()
        scroll.setValue(scroll.maximum())
