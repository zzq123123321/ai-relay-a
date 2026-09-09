import time
import ctypes

import pyautogui
import pyperclip
import win32con
import win32gui
import pywintypes

from core.diagnostic import log as diag


def send_to_input(
    click_x: int,
    click_y: int,
    content: str,
    expected_meta: dict | None = None,
) -> tuple[bool, str]:
    if click_x <= 0 or click_y <= 0:
        return False, "ChatGPT 输入框坐标无效"
    if not content.strip():
        return False, "待发送内容为空"
    hwnd = win32gui.WindowFromPoint((click_x, click_y))
    root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
    class_name = win32gui.GetClassName(root)
    if class_name != "Chrome_WidgetWin_1":
        return False, f"标定坐标不属于 Chrome 窗口: {class_name or 'unknown'}"
    if expected_meta:
        expected_class = expected_meta.get("window_class")
        if expected_class and expected_class != class_name:
            return False, f"窗口类型与标定时不一致: {class_name}"
        expected_dpi = expected_meta.get("dpi")
        current_dpi = int(ctypes.windll.user32.GetDpiForWindow(root))
        if expected_dpi and int(expected_dpi) != current_dpi:
            return False, f"DPI与标定时不一致: {expected_dpi} -> {current_dpi}"
    try:
        if win32gui.IsIconic(root):
            win32gui.ShowWindow(root, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(root)
    except (OSError, pywintypes.error) as exc:
        # Windows may reject SetForegroundWindow for a background process.
        # The validated click below is still allowed to activate the input.
        diag("A: 浏览器前台激活被系统拒绝", f"error={exc}")
    diag("A: 准备发送ChatGPT", f"click=({click_x},{click_y}) content_length={len(content)}")
    pyautogui.click(click_x, click_y)
    time.sleep(0.3)

    try:
        pyperclip.copy(content)
    except pyperclip.PyperclipException as exc:
        return False, f"写入剪贴板失败: {exc}"
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.5)
    pyautogui.press("enter")
    time.sleep(2)
    pyautogui.press("enter")
    diag("A: 已发送ChatGPT", f"length={len(content)}")

    return True, f"已发送到ChatGPT (长度={len(content)})"
