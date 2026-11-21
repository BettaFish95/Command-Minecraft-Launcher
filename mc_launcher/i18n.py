"""极简中英双语支持。"""
from __future__ import annotations

import os

LANG = "zh"


def _detect() -> str:
    if os.name == "nt":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if (lang_id & 0x3FF) == 0x04 else "en"
        except Exception:
            pass
    return "zh"


def set_lang(value: str | None) -> None:
    global LANG
    text = (value or "").strip().lower()
    if text in ("zh", "zh_cn", "chinese", "中文"):
        LANG = "zh"
    elif text in ("en", "en_us", "english"):
        LANG = "en"
    else:
        LANG = _detect()


def is_en() -> bool:
    return LANG == "en"


def t(zh: str, en: str) -> str:
    return en if LANG == "en" else zh
