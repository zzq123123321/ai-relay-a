"""Persistent IDs for responses already consumed by the A-side."""

from __future__ import annotations

import json
from pathlib import Path


class TaskRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parent.parent / "data" / "responses.json"
        self._ids = self._load()

    def contains(self, message_id: str) -> bool:
        return message_id in self._ids

    def add(self, message_id: str) -> None:
        self._ids.add(message_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(sorted(self._ids), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"failed to load response registry: {self.path}") from exc
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise RuntimeError("response registry has an invalid structure")
        return set(data)
