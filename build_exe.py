"""
build_exe.py — Build script for FirstReplyBot.exe

Run this script to create a standalone executable.
The exe will be output to the Desktop.

Usage:
    python build_exe.py
"""

import os
import shutil
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(os.environ["TEMP"], "FirstReplyBot_build")
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop")

# Python files to include
PY_FILES = [
    "launcher.py", "main.py", "userbot.py", "control_bot.py",
    "scheduler.py", "state.py", "config.py", "persistent_state.py",
    "startup_checks.py", "create_session.py",
]

DATA_FILES = [".env.example"]


def main():
    print("=" * 60)
    print("  FirstReplyBot — EXE Builder")
    print("=" * 60)

    # Clean build dir
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR, exist_ok=True)

    # Copy all python files
    print("\n[1/3] Copying project files...")
    for f in PY_FILES + DATA_FILES:
        src = os.path.join(PROJECT_DIR, f)
        if os.path.exists(src):
            shutil.copy2(src, BUILD_DIR)
            print(f"  + {f}")
        else:
            print(f"  - {f} (not found, skipping)")

    # Create sessions directory
    os.makedirs(os.path.join(BUILD_DIR, "sessions"), exist_ok=True)

    # Build with PyInstaller
    print("\n[2/3] Building executable (this may take a minute)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "FirstReplyBot",
        "--distpath", OUTPUT_DIR,
        "--clean",
        "launcher.py",
    ]

    result = subprocess.run(cmd, cwd=BUILD_DIR)

    if result.returncode != 0:
        print("\n[X] Build FAILED!")
        return 1

    exe_path = os.path.join(OUTPUT_DIR, "FirstReplyBot.exe")

    # Clean up
    print("\n[3/3] Cleaning up...")
    shutil.rmtree(BUILD_DIR, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"  [OK] Build successful!")
    print(f"  Output: {exe_path}")
    print(f"\n  [!] IMPORTANT: Place these files next to the exe:")
    print(f"      - .env (your configuration)")
    print(f"      - sessions/ folder (your session files)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
