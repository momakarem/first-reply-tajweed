"""
launcher.py — Console launcher for First Reply Tajweed Bot.

Features:
  - Nice console banner with colored output
  - Starts the bot (control bot + userbot system)
  - Type 'stop' or 'quit' or press Ctrl+C to gracefully shut down
  - Shows real-time status
"""

import asyncio
import logging
import os
import sys
import threading
import time

# ── Ensure working directory is where the exe/script lives ────────────────────
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Windows console setup ─────────────────────────────────────────────────────
if sys.platform == "win32":
    # Enable ANSI colors on Windows 10+
    os.system("")
    # Use WindowsSelectorEventLoopPolicy for compatibility
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ── ANSI Colors ───────────────────────────────────────────────────────────────
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[92m"
    CYAN    = "\033[96m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"
    BG_DARK = "\033[40m"


def print_banner():
    """Print a styled startup banner."""
    banner = f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   {C.GREEN}█▀▀ █ █▀█ █▀ ▀█▀   █▀█ █▀▀ █▀█ █   █▄█{C.CYAN}                     ║
║   {C.GREEN}█▀  █ █▀▄ ▄█  █    █▀▄ ██▄ █▀▀ █▄▄  █ {C.CYAN}                     ║
║                                                              ║
║   {C.WHITE}First Reply Tajweed Bot{C.CYAN}                                     ║
║   {C.DIM}Telegram Auto-Reply System{C.RESET}{C.CYAN}{C.BOLD}                                ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   {C.YELLOW}⚡ Zero-delay reply mode{C.CYAN}                                    ║
║   {C.YELLOW}🔒 Device spoofing (Galaxy S24 Ultra){C.CYAN}                       ║
║   {C.YELLOW}🤖 Control bot: /arm /stop /status{C.CYAN}                          ║
║   {C.YELLOW}📡 Persistent service mode{C.CYAN}                                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}
"""
    print(banner)


def print_controls():
    """Print available controls."""
    print(f"""
{C.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.RESET}
  {C.GREEN}Bot is running!{C.RESET}
  
  {C.WHITE}Controls:{C.RESET}
    {C.YELLOW}stop{C.RESET}  / {C.YELLOW}quit{C.RESET}  → Graceful shutdown
    {C.YELLOW}Ctrl+C{C.RESET}        → Graceful shutdown
{C.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.RESET}
""")


def main():
    print_banner()

    # ── Check .env file exists ────────────────────────────────────────────
    if not os.path.exists(".env"):
        print(f"\n{C.RED}{C.BOLD}  ❌ ERROR: .env file not found!{C.RESET}")
        print(f"  {C.YELLOW}Create a .env file with your credentials.{C.RESET}")
        print(f"  {C.DIM}See .env.example for reference.{C.RESET}\n")
        input("  Press Enter to exit...")
        return

    print(f"  {C.DIM}Loading configuration...{C.RESET}")

    # ── Import after chdir so .env is found ───────────────────────────────
    try:
        from main import _async_main
    except SystemExit as e:
        print(f"\n{C.RED}{C.BOLD}  ❌ Configuration Error: {e}{C.RESET}")
        print(f"  {C.YELLOW}Check your .env file.{C.RESET}\n")
        input("  Press Enter to exit...")
        return
    except Exception as e:
        print(f"\n{C.RED}{C.BOLD}  ❌ Import Error: {e}{C.RESET}")
        input("  Press Enter to exit...")
        return

    print(f"  {C.GREEN}✅ Configuration loaded{C.RESET}")

    # ── Shutdown event ────────────────────────────────────────────────────
    shutdown_requested = threading.Event()

    async def _run_with_shutdown():
        """Run the bot with console input monitoring."""
        # Start input listener in a thread
        def _input_listener():
            while not shutdown_requested.is_set():
                try:
                    cmd = input().strip().lower()
                    if cmd in ("stop", "quit", "exit", "q"):
                        print(f"\n{C.YELLOW}  ⏳ Shutting down gracefully...{C.RESET}")
                        shutdown_requested.set()
                        return
                except EOFError:
                    return
                except Exception:
                    return

        input_thread = threading.Thread(target=_input_listener, daemon=True)
        input_thread.start()

        # Run the actual bot
        try:
            await _async_main()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"\n{C.RED}  ❌ Bot error: {e}{C.RESET}")

    # ── Run ───────────────────────────────────────────────────────────────
    print_controls()

    try:
        asyncio.run(_run_with_shutdown())
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}  ⏳ Shutting down...{C.RESET}")

    print(f"\n{C.GREEN}{C.BOLD}  ✅ Bot stopped successfully.{C.RESET}")
    print(f"  {C.DIM}Goodbye!{C.RESET}\n")

    # Give a moment to read the message
    time.sleep(1)


if __name__ == "__main__":
    main()
