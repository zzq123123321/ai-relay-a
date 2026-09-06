import ctypes
from ctypes import wintypes
import json
import os
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np
import pyautogui
from PIL import Image, ImageTk

from core import adapter


TARGET_KEYS = ["trigger", "bottom", "copy"]
TARGET_LABELS = ["回复完成图标", "到底按钮", "复制回复按钮"]
OPTIONAL_KEYS: list[str] = []
OPTIONAL_LABELS: list[str] = []
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
TK_COLOR = "#ff01fe"
BOX_FILL = "#ff01ff"
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTTRANSPARENT = -1
GWL_WNDPROC = -4

_BG = "#2b2b2b"
_FG = "#e0e0e0"
_BTN_BG = "#3c3c3c"
_BLUE = "#5b9aff"
_TXT2 = "#98989d"
_RED = "#ff453a"
_GREEN = "#30d158"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def capture_region(x, y, w, h):
    screen = pyautogui.screenshot()
    screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
    if h <= 0 or w <= 0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return screen_cv[y : y + h, x : x + w]


class Calibrator:
    def __init__(self, endpoint: str = adapter.DEFAULT_ENDPOINT, step: str | None = None):
        self.endpoint = endpoint if endpoint in adapter.endpoints() else adapter.DEFAULT_ENDPOINT
        self.config = load_config()
        surfaces = self.config.setdefault("surfaces", {})
        surfaces.setdefault(self.endpoint, {})
        self.locked_step = step if step in TARGET_KEYS else None
        self.target_idx = TARGET_KEYS.index(self.locked_step) if self.locked_step else 0
        self.optional_idx = None
        self.box = self._load_box()

        self.dragging = False
        self.resizing = False
        self.resize_corner = None
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.box_start = {}

        self.edit_mode = True
        self.passthrough_mode = False

        self.panel = tk.Tk()
        self.panel.title("AI Relay 标定")
        self.panel.geometry("440x680+50+50")
        self.panel.resizable(False, False)
        self.panel.attributes("-topmost", True)
        self.panel.configure(bg=_BG)
        self.panel.protocol("WM_DELETE_WINDOW", self._on_close)
        self.panel.update()

        sw = self.panel.winfo_screenwidth()
        sh = self.panel.winfo_screenheight()

        self.overlay = tk.Toplevel(self.panel)
        self.overlay.geometry(f"{sw}x{sh}+0+0")
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-transparentcolor", TK_COLOR)
        self.overlay.configure(bg=TK_COLOR)

        self.overlay.lower(self.panel)

        self.canvas = tk.Canvas(self.overlay, highlightthickness=0, bg=TK_COLOR)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_hover)

        self.overlay.update_idletasks()
        self._subclass_overlay()

        self._build_panel()
        self._draw_box()
        self._last_preview = 0.0
        self._apply_overlay()
        self.panel.after(200, self._update_preview)

        self.panel.mainloop()

    def _apply_overlay(self):
        if self.edit_mode:
            self.passthrough_mode = False
            self._draw_box()
            self.lbl_mode.config(text="✏️ 编辑模式", fg=_BLUE)
        elif self.passthrough_mode:
            self.canvas.delete("box")
            self.lbl_mode.config(text="👆 穿透模式", fg=_GREEN)
        else:
            self.canvas.delete("box")
            self.lbl_mode.config(text="🔒 锁定模式", fg=_TXT2)

    def _subclass_overlay(self):
        hwnd = self.overlay.winfo_id()
        user32 = ctypes.windll.user32

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
            ctypes.c_ulonglong, ctypes.c_longlong,
        )

        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._old_wndproc = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)

        user32.CallWindowProcW.restype = ctypes.c_longlong
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p,
        ]

        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_NCHITTEST:
                    lo32 = lparam & 0xFFFFFFFF
                    x = ctypes.c_int16(lo32 & 0xFFFF).value
                    y = ctypes.c_int16((lo32 >> 16) & 0xFFFF).value
                    b = self.box
                    if (
                        self.edit_mode
                        and b["x"] <= x <= b["x"] + b["w"]
                        and b["y"] <= y <= b["y"] + b["h"]
                    ):
                        return HTCLIENT
                    return HTTRANSPARENT
                return user32.CallWindowProcW(
                    self._old_wndproc, hwnd, msg, wparam, lparam,
                )
            except Exception as exc:
                print(f"[calibrate][ERROR] window callback failed: {exc}")
                try:
                    return user32.CallWindowProcW(
                        self._old_wndproc, hwnd, msg, wparam, lparam,
                    )
                except OSError as fallback_exc:
                    print(f"[calibrate][ERROR] fallback callback failed: {fallback_exc}")
                    return 0

        self._wndproc_callback = WNDPROC(wnd_proc)
        user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, self._wndproc_callback)
        print(f"[calibrate] subclass installed")

    def _current_key(self):
        if self.optional_idx is not None:
            return OPTIONAL_KEYS[self.optional_idx]
        return TARGET_KEYS[self.target_idx]

    def _current_label(self):
        if self.optional_idx is not None:
            return OPTIONAL_LABELS[self.optional_idx]
        return TARGET_LABELS[self.target_idx]

    def _load_box(self):
        key = self._current_key()
        t = adapter.resolve_target(self.config, key, self.endpoint)
        if t:
            return {
                "x": t.get("x", 1400),
                "y": t.get("y", 850),
                "w": t.get("w", 80),
                "h": t.get("h", 80),
            }
        return {"x": 1400, "y": 850, "w": 80, "h": 80}

    def _save_box(self):
        key = self._current_key()
        ns = self.config["surfaces"].setdefault(self.endpoint, {})
        cx = self.box["x"] + self.box["w"] // 2
        cy = self.box["y"] + self.box["h"] // 2
        ns[key] = {
            "x": self.box["x"],
            "y": self.box["y"],
            "w": self.box["w"],
            "h": self.box["h"],
            "click_x": cx,
            "click_y": cy,
        }
        save_config(self.config)

    def _build_panel(self):
        tk.Label(self.panel, text="AI Relay — 视觉标定", font=("Arial", 14, "bold"), bg=_BG, fg=_FG).pack(pady=(10, 2))

        self.lbl_target = tk.Label(self.panel, text=f"目标: {self._current_label()}", font=("Arial", 13, "bold"), fg=_BLUE, bg=_BG)
        self.lbl_target.pack(pady=2)

        self.lbl_mode = tk.Label(self.panel, text="✏️ 编辑模式", font=("Arial", 11, "bold"), fg=_BLUE, bg=_BG)
        self.lbl_mode.pack(pady=2)

        cf = tk.Frame(self.panel, bg=_BG)
        cf.pack(pady=5)
        self.lbl_x = tk.Label(cf, text=f"x: {self.box['x']}", width=10, anchor="w", bg=_BG, fg=_FG)
        self.lbl_x.grid(row=0, column=0, padx=5)
        self.lbl_y = tk.Label(cf, text=f"y: {self.box['y']}", width=10, anchor="w", bg=_BG, fg=_FG)
        self.lbl_y.grid(row=0, column=1, padx=5)
        self.lbl_w = tk.Label(cf, text=f"w: {self.box['w']}", width=10, anchor="w", bg=_BG, fg=_FG)
        self.lbl_w.grid(row=1, column=0, padx=5)
        self.lbl_h = tk.Label(cf, text=f"h: {self.box['h']}", width=10, anchor="w", bg=_BG, fg=_FG)
        self.lbl_h.grid(row=1, column=1, padx=5)

        self.preview_label = tk.Label(self.panel, text="区域预览", bg="#444", fg=_FG, width=50, height=12)
        self.preview_label.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        self.lbl_result = tk.Label(self.panel, text="等待操作...", font=("Arial", 11), bg=_BG, fg=_FG)
        self.lbl_explain = tk.Label(self.panel, text="拖动绿色框对准目标区域，点击保存模板", font=("Arial", 10), bg=_BG, fg=_TXT2)
        self.lbl_explain.pack(pady=2)
        self.lbl_result.pack(pady=2)

        bf = tk.Frame(self.panel, bg=_BG)
        bf.pack(pady=8)
        tk.Button(bf, text="检测识别", command=self._detect, width=10, height=2, bg=_BTN_BG, fg=_FG, activebackground="#555", activeforeground=_FG).grid(row=0, column=0, padx=3)
        tk.Button(bf, text="保存模板", command=self._save_template, width=10, height=2, bg=_BTN_BG, fg=_FG, activebackground="#555", activeforeground=_FG).grid(row=0, column=1, padx=3)
        tk.Button(bf, text="下一目标", command=self._next_target, width=10, height=2, bg=_BTN_BG, fg=_FG, activebackground="#555", activeforeground=_FG).grid(row=0, column=2, padx=3)

        bf2 = tk.Frame(self.panel, bg=_BG)
        bf2.pack(pady=5)
        self.btn_edit = tk.Button(bf2, text="搜索范围", command=self._toggle_edit, width=10, height=2, bg=_BTN_BG, fg=_FG, activebackground="#555", activeforeground=_FG)
        self.btn_edit.grid(row=0, column=0, padx=3)
        self.btn_passthrough = tk.Button(bf2, text="穿透模式", command=self._toggle_passthrough, width=10, height=2, bg=_BTN_BG, fg=_FG, activebackground="#555", activeforeground=_FG)
        self.btn_passthrough.grid(row=0, column=1, padx=3)
        tk.Button(bf2, text="退出", command=self._on_close, width=10, height=2, bg="#cc3333", fg=_FG, activebackground="#aa2222", activeforeground=_FG).grid(row=0, column=2, padx=3)

        bf3 = tk.Frame(self.panel, bg=_BG)
        bf3.pack(pady=5)

    def _draw_box(self):
        self.canvas.delete("box")
        b = self.box
        self.canvas.create_rectangle(
            b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"],
            outline="#00ff00", width=4, fill=BOX_FILL, tags="box",
        )
        cx, cy = b["x"] + b["w"] // 2, b["y"] + b["h"] // 2
        self.canvas.create_line(cx - 15, cy, cx + 15, cy, fill="#00ff00", width=2, tags="box")
        self.canvas.create_line(cx, cy - 15, cx, cy + 15, fill="#00ff00", width=2, tags="box")
        hs = 10
        for dx, dy in [(0, 0), (b["w"], 0), (0, b["h"]), (b["w"], b["h"])]:
            self.canvas.create_rectangle(
                b["x"] + dx - hs, b["y"] + dy - hs,
                b["x"] + dx + hs, b["y"] + dy + hs,
                fill="white", outline="#00ff00", width=2, tags="box",
            )

    def _on_box_zone(self, x, y):
        b = self.box
        hs = 10
        hits = [
            ("nw", b["x"], b["y"]),
            ("ne", b["x"] + b["w"], b["y"]),
            ("sw", b["x"], b["y"] + b["h"]),
            ("se", b["x"] + b["w"], b["y"] + b["h"]),
        ]
        for name, cx, cy in hits:
            if abs(x - cx) <= hs and abs(y - cy) <= hs:
                return name
        if b["x"] <= x <= b["x"] + b["w"] and b["y"] <= y <= b["y"] + b["h"]:
            return "move"
        return None

    def _on_mouse_down(self, event):
        if not self.edit_mode:
            return
        zone = self._on_box_zone(event.x, event.y)
        if zone is None:
            return
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.box_start = dict(self.box)
        if zone == "move":
            self.dragging = True
        else:
            self.resizing = True
            self.resize_corner = zone

    def _on_mouse_move(self, event):
        if not self.edit_mode:
            return
        if self.dragging:
            dx = event.x - self.drag_start_x
            dy = event.y - self.drag_start_y
            self.box["x"] = self.box_start["x"] + dx
            self.box["y"] = self.box_start["y"] + dy
            self._redraw()
        elif self.resizing:
            dx = event.x - self.drag_start_x
            dy = event.y - self.drag_start_y
            s, b, c = self.box_start, self.box, self.resize_corner
            if c == "se":
                b["w"] = max(20, s["w"] + dx); b["h"] = max(20, s["h"] + dy)
            elif c == "sw":
                nw = max(20, s["w"] - dx); b["x"] = s["x"] + (s["w"] - nw); b["w"] = nw; b["h"] = max(20, s["h"] + dy)
            elif c == "ne":
                b["w"] = max(20, s["w"] + dx); nh = max(20, s["h"] - dy); b["y"] = s["y"] + (s["h"] - nh); b["h"] = nh
            elif c == "nw":
                nw = max(20, s["w"] - dx); nh = max(20, s["h"] - dy); b["x"] = s["x"] + (s["w"] - nw); b["y"] = s["y"] + (s["h"] - nh); b["w"] = nw; b["h"] = nh
            self._redraw()

    def _on_mouse_hover(self, event):
        if not self.edit_mode:
            return
        zone = self._on_box_zone(event.x, event.y)
        cursors = {"move": "fleur", "nw": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw", "se": "size_nw_se"}
        self.canvas.config(cursor=cursors.get(zone) if zone else "")

    def _on_mouse_up(self, event):
        if not self.edit_mode:
            return
        self.dragging = False
        self.resizing = False
        self.canvas.config(cursor="")
        self._update_labels()
        self._update_preview()

    def _redraw(self):
        self._draw_box()
        self._update_labels()
        if self.dragging or self.resizing:
            return
        now = time.time()
        if now - self._last_preview > 0.3:
            self._last_preview = now
            self._update_preview()

    def _update_labels(self):
        b = self.box
        self.lbl_x.config(text=f"x: {b['x']}")
        self.lbl_y.config(text=f"y: {b['y']}")
        self.lbl_w.config(text=f"w: {b['w']}")
        self.lbl_h.config(text=f"h: {b['h']}")

    def _update_preview(self, event=None):
        b = self.box

        self.overlay.withdraw()
        self.panel.update()
        region = capture_region(b["x"], b["y"], b["w"], b["h"])
        self.overlay.deiconify()
        self.panel.update()

        if region.size == 0 or region.shape[0] < 2 or region.shape[1] < 2:
            return
        h, w = region.shape[:2]
        mw, mh = 380, 160
        scale = min(mw / w, mh / h, 1.0)
        if scale < 1.0:
            region = cv2.resize(region, (int(w * scale), int(h * scale)))
        rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(img)
        self.preview_label.config(image=imgtk)
        self.preview_label.image = imgtk

    def _template_path(self, key: str) -> str:
        tmpl = adapter.template_map(self.config, self.endpoint).get(key)
        if tmpl:
            path = Path(tmpl)
            return str(path if path.is_absolute() else APP_DIR / path)
        return str(APP_DIR / "templates" / f"{key}.png")

    def _detect(self):
        key = self._current_key()
        tpl_path = self._template_path(key)
        if not os.path.exists(tpl_path):
            self.lbl_result.config(text="❌ 模板不存在，先保存模板", fg=_RED)
            return
        b = self.box

        self.overlay.withdraw()
        self.panel.update()
        time.sleep(0.15)
        region = capture_region(b["x"], b["y"], b["w"], b["h"])
        self.overlay.deiconify()
        self.panel.update()

        if region.size == 0:
            self.lbl_result.config(text="❌ 区域无效", fg=_RED)
            return
        template = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
        if template is None:
            self.lbl_result.config(text="❌ 模板读取失败", fg=_RED)
            return
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        th = self.config.get("threshold", 0.8)
        if max_val >= th:
            self.lbl_result.config(text=f"🟩 匹配成功 识别率={max_val:.3f}", fg="green")
        else:
            self.lbl_result.config(text=f"🟥 未匹配 识别率={max_val:.3f}", fg="red")

    def _save_template(self):
        key = self._current_key()
        tpl_path = self._template_path(key)
        Path(tpl_path).parent.mkdir(parents=True, exist_ok=True)
        b = self.box

        self.overlay.withdraw()
        self.panel.update()
        time.sleep(0.15)
        region = capture_region(b["x"], b["y"], b["w"], b["h"])
        self.overlay.deiconify()
        self.panel.update()

        if region.size == 0 or region.shape[0] < 2 or region.shape[1] < 2:
            self.lbl_result.config(text="❌ 区域无效，无法保存", fg=_RED)
            return
        if not cv2.imwrite(tpl_path, region):
            self.lbl_result.config(text="❌ 保存失败", fg=_RED)
            return
        self._save_box()
        self.lbl_result.config(text=f"✅ 已保存: {key}", fg="green")
        print(f"[标定] 已保存 {tpl_path} + 配置目标")

    def _next_target(self):
        if self.locked_step:
            self._on_close()
            return
        if self.optional_idx is not None:
            self.optional_idx = None
            self.lbl_result.config(text="已退出可选标定", fg=_FG)
        elif self.target_idx < len(TARGET_KEYS) - 1:
            self.target_idx += 1
            self.lbl_result.config(text="等待操作...", fg=_FG)
        else:
            self.target_idx = 0
            self.lbl_result.config(text="必选标定完成", fg="green")
        save_config(self.config)
        self.box = self._load_box()
        self.lbl_target.config(text=f"目标: {self._current_label()}")
        self._update_labels()
        self._draw_box()
        self._update_preview()

    def _toggle_optional(self):
        if not OPTIONAL_KEYS:
            self.lbl_result.config(text="当前流程没有可选标定项", fg=_FG)
            return
        if self.optional_idx is None:
            self.optional_idx = 0
            self.lbl_result.config(text="可选: 标定停止按钮", fg=_ORANGE)
        else:
            self.optional_idx = None
            self.lbl_result.config(text="已退出可选标定", fg=_FG)
        self.box = self._load_box()
        self.lbl_target.config(text=f"目标: {self._current_label()}")
        self._update_labels()
        self._draw_box()
        self._update_preview()

    def _toggle_edit(self):
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            self.passthrough_mode = False
            self.btn_edit.config(bg="#aaddff", relief=tk.SUNKEN)
            self.btn_passthrough.config(bg="#e0e0e0", relief=tk.RAISED)
        else:
            self.btn_edit.config(bg="#e0e0e0", relief=tk.RAISED)
        self._apply_overlay()

    def _toggle_passthrough(self):
        self.passthrough_mode = not self.passthrough_mode
        if self.passthrough_mode:
            self.edit_mode = False
            self.btn_passthrough.config(bg="#aaffaa", relief=tk.SUNKEN)
            self.btn_edit.config(bg="#e0e0e0", relief=tk.RAISED)
        else:
            self.btn_passthrough.config(bg="#e0e0e0", relief=tk.RAISED)
        self._apply_overlay()

    def _on_close(self):
        save_config(self.config)
        self.overlay.destroy()
        self.panel.destroy()


if __name__ == "__main__":
    import sys as _sys
    endpoint = adapter.DEFAULT_ENDPOINT
    if "--endpoint" in _sys.argv:
        i = _sys.argv.index("--endpoint")
        if i + 1 < len(_sys.argv):
            endpoint = _sys.argv[i + 1]
    step = None
    if "--step" in _sys.argv:
        i = _sys.argv.index("--step")
        if i + 1 < len(_sys.argv):
            step = _sys.argv[i + 1]
    Calibrator(endpoint=endpoint, step=step)
