from PySide6.QtCore import QObject, Signal


class StateManager(QObject):
    state_changed = Signal(str)
    log_appended = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._state = "IDLE"

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, s: str):
        if s != self._state:
            self._state = s
            self.state_changed.emit(s)

    def add_log(self, event: str, detail: str = ""):
        self.log_appended.emit(event, detail)
