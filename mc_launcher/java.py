"""Java 探测、版本识别与内存建议。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import app_dir, data_dir
from .storage import read_json, write_json

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class JavaError(Exception):
    pass


@dataclass
class JavaInfo:
    path: Path
    major: int
    version: str

    def __str__(self) -> str:
        return f"Java {self.major} ({self.version})"


def _flags() -> int:
    return CREATE_NO_WINDOW


def inspect_java(path: Path, use_cache: bool = True) -> JavaInfo | None:
    path = Path(path)
    try:
        if not path.is_file():
            return None
        stat = path.stat()
    except OSError:
        return None

    cache_path = data_dir() / "java_cache.json"
    cache = read_json(cache_path, {})
    if not isinstance(cache, dict):
        cache = {}
    key = os.path.normcase(str(path.resolve()))
    cached = cache.get(key)
    if (
        use_cache
        and isinstance(cached, dict)
        and cached.get("mtime") == stat.st_mtime
        and cached.get("size") == stat.st_size
        and cached.get("major")
    ):
        return JavaInfo(path, int(cached["major"]), str(cached.get("version") or ""))

    try:
        proc = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    match = re.search(r'version\s+"([^"]+)"', text)
    if not match:
        match = re.search(r"(?:openjdk|java)\s+([0-9][^\s\"]*)", text, re.IGNORECASE)
    if not match:
        return None
    version = match.group(1)
    try:
        if version.startswith("1."):
            major = int(version.split(".")[1])
        else:
            major = int(re.match(r"(\d+)", version).group(1))
    except (ValueError, AttributeError):
        return None

    cache[key] = {"mtime": stat.st_mtime, "size": stat.st_size, "major": major, "version": version}
    try:
        write_json(cache_path, cache)
    except OSError:
        pass
    return JavaInfo(path, major, version)


def _candidate_paths(config) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(value):
        if not value:
            return
        try:
            path = Path(value).expanduser()
        except (TypeError, ValueError):
            return
        key = os.path.normcase(str(path))
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    configured = config.get("java_path")
    add(configured)

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        add(Path(java_home) / "bin" / "java.exe")
        add(Path(java_home) / "bin" / "java")

    for name in ("java.exe", "java"):
        found = shutil.which(name)
        if found:
            add(found)

    if os.name != "nt":
        add("/usr/bin/java")
        return candidates

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Java",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Java",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Eclipse Adoptium",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "BellSoft",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Amazon Corretto",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Zulu",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Semeru",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Eclipse Adoptium",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft",
        Path.home() / ".jdks",
    ]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                if child.is_dir():
                    add(child / "bin" / "java.exe")
        except OSError:
            continue

    runtime_roots = [
        Path(os.environ.get("APPDATA", "")) / ".minecraft" / "runtime",
        Path(os.environ.get("APPDATA", "")) / ".hmcl" / "java",
        app_dir() / "java",
        app_dir() / "runtime",
    ]
    for root in runtime_roots:
        try:
            if not root.is_dir():
                continue
            for java in root.rglob("java.exe"):
                add(java)
        except OSError:
            continue

    for name in ("java.exe", "jre/bin/java.exe", "runtime/bin/java.exe"):
        add(app_dir() / name)
    return candidates


def discover_javas(config) -> list[JavaInfo]:
    result: dict[str, JavaInfo] = {}
    for candidate in _candidate_paths(config):
        info = inspect_java(candidate)
        if info is None:
            continue
        key = os.path.normcase(str(info.path.resolve()))
        result[key] = info
    return sorted(result.values(), key=lambda j: (-j.major, str(j.path)))


def choose_java(required: int, config) -> JavaInfo:
    configured = config.get("java_path")
    if configured:
        info = inspect_java(Path(configured))
        if info is None:
            raise JavaError(f"配置的 Java 无法运行：{configured}")
        if info.major < required:
            raise JavaError(
                f"该版本需要 Java {required} 或更高，但配置的是 Java {info.major}。"
            )
        return info

    javas = discover_javas(config)
    if not javas:
        raise JavaError(
            "未找到可用的 Java。请安装 Java 后重试，或用 --java <路径> 指定 java.exe。"
        )

    suitable = [java for java in javas if java.major >= required]
    if suitable:
        best = min(suitable, key=lambda j: (j.major, str(j.path)))
        if best.major > required:
            from . import ui

            ui.warn(
                f"该版本建议 Java {required}，将使用 Java {best.major}；"
                "若启动失败请安装对应 Java。"
            )
        return best

    best = javas[0]
    from . import ui

    ui.warn(
        f"该版本需要 Java {required}，本机最高只有 Java {best.major}，仍尝试启动。"
    )
    return best


def total_ram_mb() -> int:
    if os.name != "nt":
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size // (1024 * 1024))
        except (ValueError, OSError, AttributeError):
            return 0
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys // (1024 * 1024))
    except Exception:
        pass
    return 0


def auto_memory_mb() -> int:
    total = total_ram_mb()
    if total <= 0:
        return 2048
    memory = min(int(total * 0.5), 8192)
    memory = max(memory, 1024)
    return memory // 512 * 512
