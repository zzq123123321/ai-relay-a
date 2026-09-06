"""A-side ChatGPT web surface model."""

from dataclasses import dataclass

from core import adapter

DEFAULT_AGENT = adapter.CHATGPT_SURFACE


@dataclass
class AgentState:
    scroll_enabled: bool = True
    wait_before_scroll: float = 2.0
    wait_after_scroll: float = 2.0
    search_up: int = 50
    search_side: int = 50
    search_down: int = 500
    wait_after_copy: float = 0.5
    wait_after_done: float = 3.0


@dataclass
class Agent:
    name: str
    source: str
    label: str
    templates: dict
    state: AgentState


def agents() -> list[str]:
    return [adapter.CHATGPT_SURFACE]


def get(config: dict, name: str = DEFAULT_AGENT) -> Agent:
    if name != adapter.CHATGPT_SURFACE:
        raise ValueError(f"unsupported A-side surface: {name}")
    raw_state = config.get("surface_state", {}).get(name, {})
    state = AgentState(**raw_state) if isinstance(raw_state, dict) else AgentState()
    return Agent(
        name=name,
        source="CHATGPT",
        label="ChatGPT 网页",
        templates=adapter.template_map(config, name),
        state=state,
    )
