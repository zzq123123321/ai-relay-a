"""Clipboard polling for A-side responses destined for ChatGPT."""

from hashlib import sha256

from PySide6.QtCore import QObject, QTimer, Signal
import pyperclip

from core import protocol
from core.diagnostic import log as diag
from core.task_registry import TaskRegistry


class ClipboardListener(QObject):
    response_received = Signal(object)
    diagnostic_received = Signal(object)
    protocol_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._last_digest = ""
        self._registry = TaskRegistry()

    def start(self, interval_ms: int = 500):
        self._last_digest = self._digest(self._read())
        self._timer.start(interval_ms)

    def stop(self):
        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _read(self) -> str:
        try:
            value = pyperclip.paste()
        except pyperclip.PyperclipException as exc:
            raise RuntimeError(f"读取剪贴板失败: {exc}") from exc
        return value if isinstance(value, str) else ""

    def _check(self):
        try:
            text = self._read()
        except RuntimeError as exc:
            self.protocol_error.emit(str(exc))
            return
        digest = self._digest(text)
        if digest == self._last_digest:
            return
        self._last_digest = digest
        if not protocol.is_relay_text(text):
            return
        try:
            message = protocol.parse(text)
        except protocol.ProtocolError as exc:
            self.protocol_error.emit(str(exc))
            return

        if (
            message.target == "AI_RELAY"
            and message.message_type is protocol.MessageType.DIAGNOSTIC
            and message.source == protocol.SOURCE_CHATGPT
        ):
            self.diagnostic_received.emit(message)
            return

        # A-side owns only responses for ChatGPT. Legacy executor names are
        # accepted during migration, but new messages use SOURCE: EXECUTOR.
        if message.target != protocol.TARGET_CHATGPT:
            return
        if message.message_type is not protocol.MessageType.RESPONSE:
            return
        if message.source == "AI_RELAY":
            return
        if message.source not in {protocol.SOURCE_EXECUTOR, "REASONIX", "OPENCODE"}:
            self.protocol_error.emit(f"unsupported response SOURCE: {message.source}")
            return
        if self._registry.contains(message.message_id):
            return
        diag(
            "A: 收到执行结果",
            f"source={message.source} task_id={message.message_id} content_length={len(message.content)}",
        )
        self.response_received.emit(message)

    def mark_processed(self, message_id: str) -> None:
        self._registry.add(message_id)

    @staticmethod
    def _digest(text: str) -> str:
        return sha256(text.encode("utf-8")).hexdigest()
