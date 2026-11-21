"""控制台输出：UTF-8/ANSI 初始化、颜色、中英文混排表格。"""
from __future__ import annotations

import atexit
import os
import re
import sys
import unicodedata

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_COLOR = False
_PREVIOUS_CP = None

_COLORS = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "cyan": "\x1b[36m",
    "magenta": "\x1b[35m",
    "gray": "\x1b[90m",
}


def _restore_codepage() -> None:
    if _PREVIOUS_CP:
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(_PREVIOUS_CP)
        except Exception:
            pass


def init_console() -> None:
    """把 Windows 控制台切到 UTF-8 并开启 ANSI，避免中文乱码。"""
    global _COLOR, _PREVIOUS_CP
    if os.name == "nt":
        try:
            import ctypes

            k32 = ctypes.windll.kernel32
            _PREVIOUS_CP = k32.GetConsoleOutputCP()
            k32.SetConsoleOutputCP(65001)
            k32.SetConsoleCP(65001)
            handle = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            if _PREVIOUS_CP:
                atexit.register(_restore_codepage)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _COLOR = (
        sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
        and os.environ.get("TERM") != "dumb"
    )


def paint(text: str, *styles: str) -> str:
    if not _COLOR or not styles:
        return text
    prefix = "".join(_COLORS.get(s, "") for s in styles)
    return f"{prefix}{text}{_COLORS['reset']}"


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def vis_width(text: str) -> int:
    width = 0
    for ch in strip_ansi(text):
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or vis_width(text) <= limit:
        return text
    out = ""
    for ch in text:
        if vis_width(out + ch) > limit - 1:
            break
        out += ch
    return out + "…"


def pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - vis_width(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def rule(width: int = 72, char: str = "─") -> str:
    return paint(char * width, "gray")


def banner() -> None:
    from . import APP_NAME, __version__
    from .i18n import t

    print()
    print(paint(f"  {APP_NAME}", "bold", "cyan") + paint(f"  v{__version__}", "gray"))
    print(paint(t("  Minecraft Java 版 · 命令行工具", "  Minecraft Java Edition · Command-line Launcher"), "gray"))
    print(rule())


def section(title: str) -> None:
    print()
    print(paint(f"■ {title}", "bold", "cyan"))


def info(message: str) -> None:
    print(paint("[i] ", "cyan") + message)


def ok(message: str) -> None:
    print(paint("[+] ", "green") + message)


def warn(message: str) -> None:
    print(paint("[!] ", "yellow") + message)


def error(message: str) -> None:
    print(paint("[x] ", "red") + message)


def detail(message: str) -> None:
    print(paint("    " + message, "gray"))


def table(headers, rows, aligns=None, max_widths=None) -> None:
    """打印自动对齐的表格；rows 中的 None 视为空字符串。"""
    headers = [str(h) for h in headers]
    rows = [["" if c is None else str(c) for c in row] for row in rows]
    columns = len(headers)
    aligns = aligns or ["left"] * columns
    max_widths = max_widths or [None] * columns

    display = []
    for row in rows:
        display.append([
            truncate(cell, max_widths[i]) if max_widths[i] else cell
            for i, cell in enumerate(row)
        ])

    widths = [vis_width(h) for h in headers]
    for row in display:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], vis_width(cell))

    print("  " + "  ".join(paint(pad(h, widths[i]), "bold") for i, h in enumerate(headers)))
    print("  " + paint("  ".join("─" * widths[i] for i in range(columns)), "gray"))
    for row in display:
        print("  " + "  ".join(pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)))


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(paint(f"{prompt}{suffix}: ", "bold"))
    except EOFError:
        return default
    return value.strip() or default
