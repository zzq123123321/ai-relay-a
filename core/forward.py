"""A-side manual ChatGPT task capture and clipboard publishing."""

from __future__ import annotations

import pyperclip

from core import protocol
from core.diagnostic import log as diag


def capture() -> str:
    try:
        value = pyperclip.paste()
    except pyperclip.PyperclipException as exc:
        raise RuntimeError(f"读取剪贴板失败: {exc}") from exc
    return value if isinstance(value, str) else ""


def build_task(content: str, task_id: str = "") -> str:
    return protocol.wrap_task(content, task_id=task_id)


def write_to_clipboard(wrapped: str) -> int:
    try:
        pyperclip.copy(wrapped)
    except pyperclip.PyperclipException as exc:
        raise RuntimeError(f"写入剪贴板失败: {exc}") from exc
    diag("A: 写入执行任务", f"length={len(wrapped)}")
    return len(wrapped)


def forward(content: str, task_id: str = "") -> str:
    wrapped = build_task(content, task_id=task_id)
    write_to_clipboard(wrapped)
    return wrapped
