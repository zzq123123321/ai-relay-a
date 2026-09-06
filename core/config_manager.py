import json
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"


def load() -> dict:
    path = CONFIG_PATH
    if not path.exists():
        return _default()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _default() -> dict:
    return {
        "schema_version": 3,
        "debug": False,
        "threshold": 0.85,
        "trigger_threshold": 0.75,
        "scan_interval": 1,
        "clipboard_verify_delay": 0.5,
        "clipboard_retry_count": 2,
        "scroll_wait": 0.8,
        "templates": {
            "trigger": "templates/trigger.png",
            "bottom": "templates/bottom.png",
            "ready": "templates/copy.png",
        },
        "surfaces": {"chatgpt_web": {}},
        "surface_templates": {},
    }


def _endpoint_targets(cfg: dict, endpoint: str) -> dict:
    """返回 ChatGPT 网页 surface 的标定配置。"""
    from core import adapter
    return adapter.resolve_targets(cfg, endpoint)


def target_status(cfg: dict) -> dict:
    targets = _endpoint_targets(cfg, "chatgpt_web")
    return {
        "trigger": "trigger" in targets and targets["trigger"].get("w", 0) > 0,
        "bottom": "bottom" in targets and targets["bottom"].get("w", 0) > 0,
        "copy": "copy" in targets and targets["copy"].get("w", 0) > 0,
        "input_box": "input_box" in targets and targets["input_box"].get("click_x", 0) > 0,
    }
