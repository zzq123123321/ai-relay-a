import os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "AI_Relay"
WORK = ROOT / "build_work"

def pyi(*args):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                    "--distpath", str(DIST), "--workpath", str(WORK),
                    "--specpath", str(WORK), *args], check=True)

def patch_sources():
    """Inject frozen-mode detection into source files so they find bundled exes."""
    import re

    # --- main_window.py ---
    mw = ROOT / "ui" / "main_window.py"
    src = mw.read_text("utf-8")

    # Remove any previous patch block
    src = re.sub(r'\n# --- FROZEN PATCH START.*?# --- FROZEN PATCH END\n', '', src, flags=re.DOTALL)

    patch = '''
# --- FROZEN PATCH START ---
import sys as _sys
from pathlib import Path as _Path
def _resolve_python():
    if getattr(_sys, "frozen", False):
        exe = _Path(_sys.executable).parent / "main.exe"
        return str(exe), [str(exe), "--once"]
    return r"''' + sys.executable + r'''", [
        r"''' + sys.executable + r'''",
        str(_Path(__file__).resolve().parent.parent / "main.py"),
        "--once",
    ]
PYTHON, _PYI_ARGS = _resolve_python()
# --- FROZEN PATCH END ---
'''
    src = patch + src

    # Replace the setProgram/setArguments block
    old_block = '''        self._process.setProgram(PYTHON)
        self._process.setArguments([str(main_py), "--once"])'''
    new_block = '''        self._process.setProgram(PYI_ARGS[0])
        self._process.setArguments(PYI_ARGS[1:])'''
    src = src.replace(old_block, new_block)

    mw.write_text(src, "utf-8")

    # --- calibration.py ---
    cal = ROOT / "ui" / "calibration.py"
    src = cal.read_text("utf-8")
    src = re.sub(r'\n# --- FROZEN PATCH START.*?# --- FROZEN PATCH END\n', '', src, flags=re.DOTALL)

    patch_cal = '''
# --- FROZEN PATCH START ---
import sys as _sys
from pathlib import Path as _Path
if getattr(_sys, "frozen", False):
    PYTHON = str(_Path(_sys.executable).parent / "calibrate.exe")
else:
    PYTHON = r"''' + sys.executable + r'''"
# --- FROZEN PATCH END ---
'''
    src = patch_cal + src

    # Replace the subprocess.run call
    old_run = "subprocess.run([PYTHON, str(CALIBRATE_PY)], check=True)"
    new_run = ("subprocess.run([PYTHON], check=True) if getattr(_sys, 'frozen', False) "
               "else subprocess.run([PYTHON, str(CALIBRATE_PY)], check=True)")
    src = src.replace(old_run, new_run)

    cal.write_text(src, "utf-8")

def restore_sources():
    for name in ["ui/main_window.py", "ui/calibration.py"]:
        subprocess.run(["git", "checkout", "--", str(ROOT / name)],
                       cwd=ROOT, capture_output=True)

def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    if WORK.exists():
        shutil.rmtree(WORK)

    patch_sources()
    try:
        # Build main.exe (no GUI, monitoring loop)
        pyi("--onefile", "--name", "main",
            "--add-data", f"{ROOT / 'config.json'}{os.pathsep}.",
            "--add-data", f"{ROOT / 'templates'}{os.pathsep}templates",
            str(ROOT / "main.py"))

        # Build calibrate.exe (tkinter calibration tool)
        pyi("--onefile", "--name", "calibrate",
            "--add-data", f"{ROOT / 'config.json'}{os.pathsep}.",
            "--add-data", f"{ROOT / 'templates'}{os.pathsep}templates",
            str(ROOT / "calibrate.py"))

        # Build AI_Relay.exe (PySide6 GUI)
        pyi("--onefile", "--name", "AI_Relay",
            "--add-data", f"{ROOT / 'config.json'}{os.pathsep}.",
            "--add-data", f"{ROOT / 'templates'}{os.pathsep}templates",
            str(ROOT / "app.py"))

        # Assemble final directory
        final = DIST
        for exe_name in ["main.exe", "calibrate.exe", "AI_Relay.exe"]:
            src = DIST / exe_name
            if src.exists():
                print(f"  {exe_name}: {src.stat().st_size / 1024:.0f} KB")
            else:
                print(f"  WARNING: {exe_name} not found at {src}")

        # Copy data files alongside
        shutil.copy2(ROOT / "config.json", final / "config.json")
        templ_dir = final / "templates"
        if templ_dir.exists():
            shutil.rmtree(templ_dir)
        shutil.copytree(ROOT / "templates", templ_dir)
        Path(final / "debug").mkdir(exist_ok=True)
        Path(final / "logs").mkdir(exist_ok=True)

        print(f"\n=== Build complete: {final} ===")
        for f in sorted(final.iterdir()):
            if f.is_file():
                print(f"  {f.name}  ({f.stat().st_size / 1024:.0f} KB)")
    finally:
        restore_sources()

if __name__ == "__main__":
    main()
