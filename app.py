import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    lock_path = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / "ai-relay-a.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(1000)
    if not lock.tryLock(100):
        if not lock.removeStaleLockFile() or not lock.tryLock(100):
            raise RuntimeError("AI Relay A端已在运行")
    app.setFont(QFont("PingFang SC", 10))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
