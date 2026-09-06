"""A-side UI surface configuration.

The A-side controls one surface only: the ChatGPT web page. Executor product
names are protocol implementation details owned by the B-side.
"""

from __future__ import annotations

from pathlib import Path

CHATGPT_SURFACE = "chatgpt_web"
DEFAULT_ENDPOINT = CHATGPT_SURFACE  # Compatibility name for existing callers.

_TEMPLATES = {
    "trigger": "templates/chatgpt_web/trigger.png",
    "bottom": "templates/chatgpt_web/bottom.png",
    "copy": "templates/chatgpt_web/copy.png",
    "stop": "templates/chatgpt_web/stop.png",
}


def endpoints() -> list[str]:
    return [CHATGPT_SURFACE]


def resolve_targets(config: dict, endpoint: str = CHATGPT_SURFACE) -> dict:
    if endpoint != CHATGPT_SURFACE:
        return {}
    surfaces = config.get("surfaces", {})
    if isinstance(surfaces, dict):
        value = surfaces.get(CHATGPT_SURFACE)
        if isinstance(value, dict):
            return value
    # Read-only compatibility for the former misnamed OpenCode namespace.
    targets = config.get("targets", {})
    if isinstance(targets, dict) and isinstance(targets.get("opencode"), dict):
        return targets["opencode"]
    return targets if _flat_targets(targets) else {}


def resolve_target(config: dict, target_name: str, endpoint: str = CHATGPT_SURFACE) -> dict:
    value = resolve_targets(config, endpoint).get(target_name)
    return value if isinstance(value, dict) else {}


def resolve_source(config: dict, endpoint: str = CHATGPT_SURFACE) -> str:
    return "CHATGPT"


def template_map(config: dict, endpoint: str = CHATGPT_SURFACE) -> dict:
    configured = config.get("surface_templates", {})
    if isinstance(configured, dict) and isinstance(configured.get(CHATGPT_SURFACE), dict):
        return dict(configured[CHATGPT_SURFACE])
    legacy_paths = {
        key: f"templates/{key}.png" for key in ("trigger", "bottom", "copy", "stop")
    }
    return {
        key: path if Path(path).exists() else _TEMPLATES[key]
        for key, path in legacy_paths.items()
    }


def _flat_targets(targets: object) -> bool:
    return isinstance(targets, dict) and any(
        isinstance(targets.get(key), dict) for key in ("trigger", "input_box")
    )
