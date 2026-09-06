import json
import hashlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import pyperclip
import win32con
import win32gui
import pywintypes

from core import adapter, agent as agent_mod
from core import protocol
from core.diagnostic import log as diag

APP_DIR = Path(__file__).resolve().parent


def load_config(path: str | Path = APP_DIR / "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str):
    print(f"[{timestamp()}]", flush=True)
    print(msg, flush=True)
    print(flush=True)


def emit_status(msg_type: str, **kwargs):
    data = {"type": msg_type}
    data.update(kwargs)
    print(json.dumps(data, ensure_ascii=False), flush=True)


def save_screenshot(img: np.ndarray, label: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    Path("debug").mkdir(parents=True, exist_ok=True)
    p = Path("debug") / f"{ts}_{label}.png"
    cv2.imwrite(str(p), img)
    print(f"SAVED_DEBUG: {p.name}", flush=True)


def capture_screen() -> np.ndarray:
    img = pyautogui.screenshot()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def capture_region(full: np.ndarray, region: dict) -> np.ndarray:
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    if h <= 0 or w <= 0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return full[y : y + h, x : x + w]


def load_template(path: str) -> np.ndarray | None:
    full = Path(path)
    if not full.is_absolute():
        full = APP_DIR / full
    if not full.exists():
        return None
    return cv2.imread(str(full), cv2.IMREAD_COLOR)


def match_template(screen: np.ndarray, template: np.ndarray, threshold: float) -> tuple[bool, float]:
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return max_val >= threshold, float(max_val)


def find_template(
    full: np.ndarray,
    template: np.ndarray,
    region: dict,
    threshold: float,
) -> tuple[bool, float, int, int, np.ndarray]:
    height, width = full.shape[:2]
    x = max(0, int(region["x"]))
    y = max(0, int(region["y"]))
    right = min(width, x + int(region["w"]))
    bottom = min(height, y + int(region["h"]))
    search = full[y:bottom, x:right]
    th, tw = template.shape[:2]
    if search.shape[0] < th or search.shape[1] < tw:
        return False, 0.0, 0, 0, search
    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return (
        max_val >= threshold,
        float(max_val),
        x + max_loc[0] + tw // 2,
        y + max_loc[1] + th // 2,
        search,
    )


def click_center(target: dict):
    pyautogui.click(target["click_x"], target["click_y"])


def scroll_up_once(target: dict, step_delay: float):
    """在 ChatGPT 网页标定区域向上滚动一个鼠标滚轮刻度。"""
    x = target["click_x"]
    y = target["click_y"]
    hwnd = win32gui.WindowFromPoint((x, y))
    root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
    class_name = win32gui.GetClassName(root)
    if class_name != "Chrome_WidgetWin_1":
        raise RuntimeError(
            f"滚动坐标不属于 Chrome 窗口: ({x}, {y}) class={class_name or 'unknown'}"
        )
    try:
        win32gui.SetForegroundWindow(root)
    except (OSError, pywintypes.error) as exc:
        raise RuntimeError(f"滚动前无法激活 Chrome 窗口: {exc}") from exc
    pyautogui.moveTo(x, y)
    time.sleep(step_delay)
    pyautogui.scroll(1)
    time.sleep(step_delay)
    diag("A: 页面已向上滚动", f"clicks=1 x={x} y={y}")


def main(once: bool = False, endpoint: str = adapter.DEFAULT_ENDPOINT):
    config = load_config()
    debug = config.get("debug", False)
    threshold = config.get("threshold", 0.85)
    trigger_threshold = max(0.9, float(config.get("trigger_threshold", 0.9)))
    interval = config.get("scan_interval", 1)
    clipboard_verify_delay = config.get("clipboard_verify_delay", 0.5)
    clipboard_retry_count = config.get("clipboard_retry_count", 2)
    bottom_detection_timeout = max(10.0, float(config.get("bottom_detection_timeout", 10)))
    interaction_step_delay = max(0.1, float(config.get("interaction_step_delay", 0.5)))
    execution_start_timeout = max(5.0, float(config.get("execution_start_timeout", 10)))

    ag = agent_mod.get(config, endpoint)
    targets = adapter.resolve_targets(config, ag.name)
    if not targets:
        print(f"ERROR: UI surface {ag.name} 缺少标定配置，请先运行 calibrate.py")
        sys.exit(1)

    required = ["input_box", "trigger", "bottom", "copy"]
    for key in required:
        if key not in targets:
            print(f"ERROR: ChatGPT 网页标定缺少 {key}")
            sys.exit(1)

    templates: dict[str, np.ndarray] = {}
    for name, path in ag.templates.items():
        tmpl = load_template(path)
        if tmpl is None:
            print(f"WARNING: 模板文件不存在: {path}，跳过 {name} 检测")
        else:
            templates[name] = tmpl

    trigger_tmpl = templates.get("trigger")
    bottom_tmpl = templates.get("bottom")
    copy_tmpl = templates.get("copy")
    trigger_ok = "trigger" in templates
    bottom_ok = "bottom" in templates
    copy_ok = "copy" in templates

    if not trigger_ok:
        print("ERROR: 缺少 trigger 模板")
        sys.exit(1)
    if not bottom_ok:
        print("ERROR: 缺少 bottom 模板")
        sys.exit(1)

    Path("debug").mkdir(parents=True, exist_ok=True)
    debug_dir = "debug/screenshots"
    if debug:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)

    st = ag.state
    COPY_SEARCH_UP = max(st.search_up, 150)
    COPY_SEARCH_SIDE = max(st.search_side, 300)
    COPY_SEARCH_DOWN = st.search_down

    trigger_cal = targets["trigger"]
    trigger_search = {
        "x": trigger_cal["x"] - 50,
        "y": trigger_cal["y"] - 40,
        "w": trigger_cal["w"] + 100,
        "h": trigger_cal["h"] + 80,
    }

    state = "WAIT_EXECUTION_START"
    execution_check_deadline = 0.0
    cooldown_until = 0.0
    last_emit = 0.0
    trigger_time = 0.0
    _copy_click_x = 0
    _copy_click_y = 0
    log(f"{ag.source} 屏幕监控已启动 (事件触发模式) agent={ag.name}")
    execution_check_deadline = time.monotonic() + execution_start_timeout
    emit_status("state", state="持续检测 ChatGPT 执行状态")

    while True:
        full = capture_screen()

        has_trigger, trigger_conf, _, _, _ = find_template(
            full, trigger_tmpl, trigger_search, trigger_threshold,
        )

        if debug:
            save_screenshot(full, state.lower())

        if state == "WAIT_EXECUTION_START":
            if not has_trigger:
                state = "IDLE"
                log("EXECUTION_STARTED")
                emit_status("event", event="回复完成图标已变化，确认开始执行")
                diag("A: 已确认ChatGPT开始执行", "回复完成图标已消失或变化")
            elif time.monotonic() >= execution_check_deadline:
                emit_status("event", event="回复完成图标未变化，重新执行发送")
                diag("A: ChatGPT未开始执行", "回复完成图标持续未变化，重新按Enter")
                input_box = targets["input_box"]
                pyautogui.moveTo(input_box["click_x"], input_box["click_y"])
                time.sleep(interaction_step_delay)
                pyautogui.click()
                time.sleep(interaction_step_delay)
                pyautogui.press("enter")
                time.sleep(interaction_step_delay)
                execution_check_deadline = time.monotonic() + execution_start_timeout

        elif state == "IDLE":
            if time.time() - last_emit >= 3:
                emit_status("event", event="等待检测", confidence=trigger_conf)
                last_emit = time.time()
            if has_trigger and time.time() > cooldown_until:
                state = "WAIT_REPLY_COMPLETE"
                trigger_time = time.time()
                log("TRIGGER_FOUND")
                emit_status("event", event="检测到回复完成图标", confidence=trigger_conf, trigger_time=trigger_time)
                diag("C: 找到回复完成图标", f"confidence={trigger_conf:.3f}")

        elif state == "WAIT_REPLY_COMPLETE":
            time.sleep(st.wait_before_scroll)
            if st.scroll_enabled:
                cal = targets["bottom"]
                bottom_search = {
                    "x": cal["x"] - 150,
                    "y": cal["y"] - 100,
                    "w": cal["w"] + 300,
                    "h": cal["h"] + 200,
                }
                bottom_deadline = time.monotonic() + bottom_detection_timeout
                has_bottom = False
                bottom_conf = 0.0
                bottom_x = 0
                bottom_y = 0
                bottom_img = np.zeros((1, 1, 3), dtype=np.uint8)
                while time.monotonic() < bottom_deadline:
                    full = capture_screen()
                    has_bottom, bottom_conf, bottom_x, bottom_y, bottom_img = find_template(
                        full, bottom_tmpl, bottom_search, threshold,
                    )
                    if has_bottom:
                        break
                    time.sleep(min(interval, 0.5))
                if has_bottom:
                    log("BOTTOM_FOUND")
                    emit_status(
                        "event",
                        event="找到到底按钮",
                        confidence=bottom_conf,
                        match_x=bottom_x,
                        match_y=bottom_y,
                    )
                    save_screenshot(bottom_img, "bottom_found")
                    time.sleep(interaction_step_delay)
                    pyautogui.moveTo(bottom_x, bottom_y)
                    time.sleep(interaction_step_delay)
                    pyautogui.click()
                    time.sleep(interaction_step_delay)
                    emit_status("event", event="点击到底按钮", click_x=bottom_x, click_y=bottom_y)
                    time.sleep(st.wait_after_scroll)
                else:
                    log("BOTTOM_NOT_FOUND")
                    emit_status(
                        "event",
                        event="持续10秒未找到到底按钮，向上滚动一格后重试",
                        confidence=bottom_conf,
                    )
                    scroll_up_once(targets["bottom"], interaction_step_delay)
                    time.sleep(st.wait_after_scroll)
                    continue
            state = "CHECK_COPY"
            log("CHECK_COPY")

        elif state == "CHECK_COPY":
            cal = targets["copy"]
            srch = {
                "x": cal["x"] - COPY_SEARCH_SIDE,
                "y": cal["y"] - COPY_SEARCH_UP,
                "w": cal["w"] + COPY_SEARCH_SIDE * 2,
                "h": COPY_SEARCH_UP + COPY_SEARCH_DOWN,
            }
            has_copy = False
            copy_conf = 0.0
            copy_img = capture_region(full, srch)
            if copy_ok:
                has_copy, copy_conf, _copy_click_x, _copy_click_y, copy_img = find_template(
                    full, copy_tmpl, srch, threshold,
                )

            if has_copy:
                elapsed = time.time() - trigger_time if trigger_time > 0 else -1
                emit_status("event", event="找到复制回复按钮", confidence=copy_conf, match_x=_copy_click_x, match_y=_copy_click_y, trigger_to_copy_sec=round(elapsed, 2))
                diag("CHECK_COPY: 找到按钮", f"conf={copy_conf:.3f} x={_copy_click_x} y={_copy_click_y} trigger_to_copy={elapsed:.1f}s")
                save_screenshot(copy_img, "check_copy_found")
                state = "CLICK_COPY"
            else:
                save_screenshot(full, "check_copy_not_found")
                log("COPY_NOT_FOUND")
                emit_status("event", event="复制按钮未找到，向上滚动一格后继续检测")
                scroll_up_once(targets["copy"], interaction_step_delay)

        elif state == "CLICK_COPY":
            cal = targets["copy"]
            srch = {
                "x": cal["x"] - COPY_SEARCH_SIDE,
                "y": cal["y"] - COPY_SEARCH_UP,
                "w": cal["w"] + COPY_SEARCH_SIDE * 2,
                "h": COPY_SEARCH_UP + COPY_SEARCH_DOWN,
            }
            has_copy = False
            copy_conf = 0.0
            copy_img = capture_region(full, srch)
            if copy_ok:
                has_copy, copy_conf, _copy_click_x, _copy_click_y, copy_img = find_template(
                    full, copy_tmpl, srch, threshold,
                )

            if not has_copy:
                state = "CHECK_COPY"
                save_screenshot(full, "click_copy_retry")
            else:
                click_x = _copy_click_x
                click_y = _copy_click_y
                log("COPY_FOUND")
                diag("C: 找到复制按钮", f"conf={copy_conf:.3f} x={click_x} y={click_y}")
                emit_status("event", event="点击复制按钮", confidence=copy_conf, click_x=click_x, click_y=click_y)
                save_screenshot(copy_img, "before_copy_click")
                clipboard_before = pyperclip.paste()
                time.sleep(interaction_step_delay)
                pyautogui.moveTo(click_x, click_y)
                time.sleep(interaction_step_delay)
                pyautogui.click()
                time.sleep(interaction_step_delay)
                save_screenshot(
                    capture_region(capture_screen(), srch), "after_copy_click",
                )
                copy_deadline = time.monotonic() + 5.0
                copied_text = clipboard_before
                while time.monotonic() < copy_deadline:
                    time.sleep(interaction_step_delay)
                    copied_text = pyperclip.paste()
                    if copied_text and copied_text != clipboard_before:
                        break
                if not copied_text or copied_text == clipboard_before:
                    emit_status("event", event="点击后剪贴板未变化，重新识别并点击")
                    diag("CLICK_COPY: 重试", "复制后剪贴板未变化，重新识别复制按钮")
                    state = "CHECK_COPY"
                    continue
                emit_status("event", event="复制ChatGPT输出后剪贴板", content_len=len(copied_text))
                copied_digest = hashlib.sha256(copied_text.encode("utf-8")).hexdigest()[:12]
                diag("CLICK_COPY: 剪贴板", f"content_len={len(copied_text)} sha256={copied_digest}")

                parent_task_id = os.environ.get("AI_RELAY_TASK_ID", "")
                current_round = int(os.environ.get("AI_RELAY_ROUND", "0"))
                max_rounds = max(
                    int(os.environ.get("AI_RELAY_MAX_ROUNDS", str(protocol.DEFAULT_MAX_ROUNDS))),
                    current_round + 1,
                )
                if protocol.is_complete(copied_text):
                    emit_status("event", event="收到完成指令，自动联动停止")
                    diag("D: 自动循环已完成", protocol.COMPLETE_MARKER)
                    state = "DONE"
                    continue
                wrapped = protocol.wrap_task(
                    copied_text,
                    round_number=current_round + 1,
                    max_rounds=max_rounds,
                )
                emit_status("event", event="ChatGPT任务已封装", length=len(wrapped))
                diag(
                    "D: ChatGPT任务已封装",
                    f"parent_task_id={parent_task_id or '-'} original_length={len(copied_text)} wrapped_length={len(wrapped)}",
                )
                pyperclip.copy(wrapped)
                emit_status("event", event="已写入剪贴板", length=len(wrapped))
                diag("D: 已写入剪贴板", f"total_length={len(wrapped)}")
                print(f"[{timestamp()}]")
                print(f"RELAY_COPY_SUCCESS\nlength={len(wrapped)}")
                print()
                for attempt in range(clipboard_retry_count + 1):
                    time.sleep(clipboard_verify_delay)
                    _clip_now = pyperclip.paste()
                    _clip_ok = protocol.BEGIN_MARKER in _clip_now and _clip_now == wrapped
                    diag(
                        "D: 剪贴板校验",
                        f"attempt={attempt} len={len(_clip_now)} ok={_clip_ok}",
                    )
                    if _clip_ok:
                        break
                    if attempt < clipboard_retry_count:
                        diag("D: 剪贴板被覆盖，重写", f"attempt={attempt}")
                        pyperclip.copy(wrapped)
                emit_status("event", event="复制回复成功", length=len(wrapped))
                state = "DONE"
                log("DONE")

        elif state == "DONE":
            time.sleep(st.wait_after_done)
            if once:
                break
            if has_trigger:
                cooldown_until = time.time() + 5
                state = "IDLE"
                log("IDLE")

        elif state == "ERROR":
            if once:
                raise RuntimeError("ChatGPT 回复复制失败")
            cooldown_until = time.time() + 5
            state = "IDLE"

        time.sleep(interval)


if __name__ == "__main__":
    once = "--once" in sys.argv
    endpoint = adapter.DEFAULT_ENDPOINT
    if "--endpoint" in sys.argv:
        idx = sys.argv.index("--endpoint")
        if idx + 1 < len(sys.argv):
            endpoint = sys.argv[idx + 1]
    main(once=once, endpoint=endpoint)
