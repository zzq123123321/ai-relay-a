from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "diagnostic.log"


def log(label: str, detail: str = ""):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[DIAG][{ts}] {label}"
    if detail:
        line += f" | {detail}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        print(f"[DIAG][ERROR] 无法写入日志: {exc}")
