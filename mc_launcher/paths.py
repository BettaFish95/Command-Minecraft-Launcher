"""游戏目录自动定位。"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .storage import read_json


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    path = app_dir() / "data"
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path(os.environ.get("APPDATA", Path.home())) / "CM Launcher"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _norm(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(str(path.absolute()))


@dataclass
class GameDir:
    path: Path
    source: str

    @property
    def versions_dir(self) -> Path:
        return self.path / "versions"

    def __str__(self) -> str:
        return str(self.path)


def _add(candidate, source: str, found: list, seen: set, require_versions: bool = False) -> None:
    if not candidate:
        return
    try:
        path = Path(candidate).expanduser()
        path = path.resolve()
    except (TypeError, ValueError, OSError, RuntimeError):
        return
    try:
        if not path.is_dir():
            return
        if require_versions and not (path / "versions").is_dir():
            return
    except OSError:
        return
    key = _norm(path)
    if key in seen:
        return
    seen.add(key)
    found.append(GameDir(path, source))


def _profile_dirs(base: Path):
    data = read_json(base / "launcher_profiles.json")
    if not isinstance(data, dict):
        return
    for profile in (data.get("profiles") or {}).values():
        if isinstance(profile, dict) and profile.get("gameDirectory"):
            yield profile["gameDirectory"]


def _deep_search(found: list, seen: set, budget: float = 8.0) -> None:
    """用户目录与非系统盘的限时、限深兜底搜索。"""
    skip = {
        "windows", "program files", "program files (x86)", "programdata",
        "$recycle.bin", "system volume information", "node_modules", ".git",
        ".cache", "temp", "tmp", "packages", "winsxs", "driverstore",
        "appdata",  # 由用户目录根覆盖，避免重复与权限噪音
        "users",
    }
    roots = [Path.home()]
    if os.name == "nt":
        home_drive = Path.home().anchor.lower()
        for letter in "CDEFGHIJ":
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists() and drive.anchor.lower() != home_drive:
                    roots.append(drive)
            except OSError:
                continue

    deadline = time.monotonic() + budget
    for root in roots:
        if time.monotonic() > deadline:
            return
        try:
            for dirpath, dirnames, _files in os.walk(root):
                if time.monotonic() > deadline:
                    return
                current = Path(dirpath)
                try:
                    depth = len(current.relative_to(root).parts)
                except ValueError:
                    depth = 9
                if depth >= 3:
                    dirnames[:] = []
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in skip and (d == ".minecraft" or not d.startswith("."))
                ]
                if current.name == ".minecraft" and (current / "versions").is_dir():
                    _add(current, "自动搜索", found, seen)
                    dirnames[:] = []
        except OSError:
            continue


def _has_any_version(found: list) -> bool:
    for game in found:
        try:
            if game.versions_dir.is_dir() and any(game.versions_dir.iterdir()):
                return True
        except OSError:
            continue
    return False


def find_game_dirs(configured=None, extra=None, deep: bool = False, force_deep: bool = False) -> list[GameDir]:
    found: list[GameDir] = []
    seen: set[str] = set()
    home = Path.home()
    roaming = Path(os.environ.get("APPDATA", home))

    for item in extra or []:
        _add(item, "命令行指定", found, seen)
    for item in configured or []:
        _add(item, "配置", found, seen)

    _add(roaming / ".minecraft", "Minecraft 官方客户端", found, seen)
    if os.name != "nt":
        _add(home / ".minecraft", "用户目录", found, seen)

    base = app_dir()
    for name, source in (
        (".minecraft", "CM Launcher目录"),
        ("minecraft", "CM Launcher目录"),
        ("Minecraft", "CM Launcher目录"),
        (".hmcl/.minecraft", "HMCL"),
        ("HMCL/.minecraft", "HMCL"),
        ("PCL/.minecraft", "PCL"),
        ("游戏/.minecraft", "CM Launcher目录"),
    ):
        _add(base / name, source, found, seen)
    try:
        _add(Path.cwd() / ".minecraft", "当前目录", found, seen)
    except OSError:
        pass

    for group in (
        base / "instances",
        base / ".minecraft" / "instances",
        roaming / ".minecraft" / "instances",
    ):
        try:
            if not group.is_dir():
                continue
            children = sorted(group.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                _add(child / ".minecraft", "实例", found, seen, require_versions=True)
                _add(child, "实例", found, seen, require_versions=True)

    for game in list(found):
        try:
            for profile_dir in _profile_dirs(game.path):
                _add(profile_dir, "CM Launcher配置", found, seen)
        except OSError:
            pass

    has_versions = _has_any_version(found)
    if deep and (force_deep or not has_versions):
        _deep_search(found, seen)
    return found


def default_game_dir(config) -> Path:
    configured = config.get("game_dir")
    if configured and (Path(configured) / "versions").is_dir():
        return Path(configured)
    dirs = find_game_dirs(configured=config.game_dirs(), deep=False)
    if dirs:
        return dirs[0].path
    return Path(os.environ.get("APPDATA", Path.home())) / ".minecraft"


def _pick_folder_modern(title: str):
    """使用 Windows Vista+ 的 IFileOpenDialog 文件夹选择器。"""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def guid(text: str) -> GUID:
        return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)

    clsid = guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
    iid = guid("D57C7288-D4AD-4768-BE02-9D969532D960")
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    initialized = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if initialized < 0:
        return "error", None
    dialog = ctypes.c_void_p()
    try:
        if ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid),
                                  ctypes.byref(dialog)) < 0:
            return "error", None
        vtable = ctypes.cast(dialog, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

        def method(index, restype, *argtypes):
            return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])

        set_options = method(9, ctypes.c_long, ctypes.c_ulong)
        set_title = method(17, ctypes.c_long, wintypes.LPCWSTR)
        show = method(3, ctypes.c_long, wintypes.HWND)
        get_result = method(20, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))

        set_options(dialog, 0x00000020 | 0x00000040 | 0x00000800)  # PICKFOLDERS/FORCEFS/PATHMUSTEXIST
        if title:
            set_title(dialog, title)
        result = show(dialog, 0)
        if result == -2147023673:  # ERROR_CANCELLED
            return "cancel", None
        if result < 0:
            return "error", None

        item = ctypes.c_void_p()
        if get_result(dialog, ctypes.byref(item)) < 0 or not item:
            return "error", None
        item_vtable = None
        try:
            item_vtable = ctypes.cast(item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            get_name = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(wintypes.LPWSTR)
            )(item_vtable[5])
            name = wintypes.LPWSTR()
            if get_name(item, 0x80058000, ctypes.byref(name)) < 0 or not name:
                return "error", None
            try:
                return "ok", Path(name.value)
            finally:
                ole32.CoTaskMemFree(ctypes.cast(name, ctypes.c_void_p))
        finally:
            if item_vtable is not None:
                release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(item_vtable[2])
                release(item)
    finally:
        if dialog:
            try:
                release_dialog = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
                release_dialog(dialog)
            except Exception:
                pass
        if initialized in (0, 1):
            ole32.CoUninitialize()


def _pick_folder_legacy(title: str) -> Path | None:
    import ctypes
    from ctypes import wintypes

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", ctypes.c_uint),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    display = ctypes.create_unicode_buffer(1024)
    info = BROWSEINFOW()
    info.hwndOwner = None
    info.pidlRoot = None
    info.pszDisplayName = ctypes.cast(display, wintypes.LPWSTR)
    info.lpszTitle = title
    info.ulFlags = 0x0001 | 0x0010 | 0x0040
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not pidl:
        return None
    path_buffer = ctypes.create_unicode_buffer(1024)
    try:
        if not shell32.SHGetPathFromIDListW(pidl, path_buffer):
            return None
        return Path(path_buffer.value)
    finally:
        ole32.CoTaskMemFree(pidl)


def pick_folder(title: str = "选择游戏实例文件夹") -> Path | None:
    """优先使用现代 Windows 文件夹选择窗口；取消返回 None。"""
    if os.name != "nt":
        return None
    try:
        status, path = _pick_folder_modern(title)
    except Exception:
        status, path = "error", None
    if status == "ok":
        return path
    if status == "cancel":
        return None
    return _pick_folder_legacy(title)
