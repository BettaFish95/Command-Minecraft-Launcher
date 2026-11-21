"""启动核心：规则过滤、库/资源解析、参数拼装与进程启动。"""
from __future__ import annotations

import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import APP_NAME, __version__, ui
from .java import JavaInfo, choose_java
from .paths import data_dir, logs_dir
from .storage import read_json
from .versions import VersionInfo, parse_mc_version, required_java_major

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


class LaunchError(Exception):
    pass


@dataclass
class LaunchPlan:
    command: list[str]
    cwd: Path
    log_path: Path
    version: VersionInfo
    java: JavaInfo
    account_name: str = ""
    warnings: list[str] = field(default_factory=list)
    natives_dir: Path | None = None


def _os_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "osx"
    return "linux"


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x86" if sys.maxsize <= 2 ** 32 else "x86_64"


def _rule_matches(rule: dict, features: dict) -> bool:
    condition = rule.get("os") or {}
    if "name" in condition and condition["name"] != _os_name():
        return False
    if "arch" in condition and condition["arch"] != _arch():
        return False
    if "version" in condition:
        try:
            if not re.search(str(condition["version"]), platform.release()):
                return False
        except re.error:
            pass
    for key, expected in (rule.get("features") or {}).items():
        if bool(features.get(key)) != bool(expected):
            return False
    return True


def rules_allow(rules, features: dict | None = None) -> bool:
    if not rules:
        return True
    features = features or {}
    allowed = False
    for rule in rules:
        if not isinstance(rule, dict) or not _rule_matches(rule, features):
            continue
        if rule.get("action") == "disallow":
            allowed = False
        else:
            allowed = True
    return allowed


def flatten_arguments(items, features: dict | None = None) -> list[str]:
    result = []
    for item in items or []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            if not rules_allow(item.get("rules"), features):
                continue
            value = item.get("value")
            if isinstance(value, str):
                result.append(value)
            elif isinstance(value, list):
                result.extend(str(v) for v in value if isinstance(v, str))
    return result


def _maven_relative(name: str) -> Path | None:
    raw, _, ext = name.partition("@")
    parts = raw.split(":")
    if len(parts) < 3:
        return None
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    filename = f"{artifact}-{version}"
    if classifier:
        filename += f"-{classifier}"
    filename += f".{ext or 'jar'}"
    return Path(*group.split(".")) / artifact / version / filename


def library_path(lib: dict, libraries_dir: Path) -> Path | None:
    downloads = lib.get("downloads") or {}
    artifact = downloads.get("artifact") if isinstance(downloads, dict) else None
    if isinstance(artifact, dict) and artifact.get("path"):
        return libraries_dir / str(artifact["path"])
    name = str(lib.get("name") or "")
    relative = _maven_relative(name)
    return libraries_dir / relative if relative else None


def _native_classifier(lib: dict) -> str | None:
    natives = lib.get("natives") or {}
    key = natives.get(_os_name())
    if not key:
        return None
    bits = "64" if sys.maxsize > 2 ** 32 else "32"
    return str(key).replace("${arch}", bits)


def _native_jar(lib: dict, classifier: str, libraries_dir: Path, libraries: list[dict]) -> Path | None:
    downloads = lib.get("downloads") or {}
    classifiers = downloads.get("classifiers") if isinstance(downloads, dict) else None
    if isinstance(classifiers, dict):
        entry = classifiers.get(classifier)
        if isinstance(entry, dict) and entry.get("path"):
            candidate = libraries_dir / str(entry["path"])
            if candidate.is_file():
                return candidate
    key = _lib_key(lib)
    if key:
        group, artifact, _classifier, _ext = key
        for other in libraries:
            other_key = _lib_key(other)
            if not other_key:
                continue
            if other_key[0] == group and other_key[1] == artifact and other_key[2] == classifier:
                candidate = library_path(other, libraries_dir)
                if candidate and candidate.is_file():
                    return candidate
    raw, _, ext = str(lib.get("name") or "").partition("@")
    parts = raw.split(":")
    if len(parts) >= 3:
        group, artifact, version = parts[0], parts[1], parts[2]
        relative = _maven_relative(f"{group}:{artifact}:{version}:{classifier}@{ext or 'jar'}")
        if relative:
            candidate = libraries_dir / relative
            if candidate.is_file():
                return candidate
    return None


def _lib_key(lib: dict):
    name = str(lib.get("name") or "")
    if not name:
        return None
    raw, _, ext = name.partition("@")
    parts = raw.split(":")
    if len(parts) < 3:
        return None
    return (parts[0], parts[1], parts[3] if len(parts) > 3 else "", ext or "jar")


def _excluded(name: str, patterns) -> bool:
    if name.startswith("META-INF/"):
        return True
    for pattern in patterns or []:
        pattern = str(pattern)
        if pattern.endswith("/"):
            if name.startswith(pattern):
                return True
        elif name == pattern:
            return True
    return False


def _extract_natives(jar: Path, destination: Path, patterns) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    count = 0
    with zipfile.ZipFile(jar) as archive:
        for item in archive.infolist():
            if item.is_dir() or _excluded(item.filename, patterns):
                continue
            parts = [p for p in PurePosixPath(item.filename).parts if p not in ("", ".", "..")]
            if not parts:
                continue
            target = destination.joinpath(*parts)
            try:
                target.resolve().relative_to(base)
            except (ValueError, OSError):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)
            count += 1
    return count


def _prepare_virtual_assets(game_dir: Path, index_id: str, index: dict) -> None:
    objects = index.get("objects") or {}
    if not objects:
        return
    virtual_root = game_dir / "assets" / "virtual" / index_id
    resources_root = game_dir / "resources"
    copy_resources = bool(index.get("map_to_resources"))
    objects_root = game_dir / "assets" / "objects"
    for name, meta in objects.items():
        if not isinstance(meta, dict) or not meta.get("hash"):
            continue
        digest = str(meta["hash"])
        source = objects_root / digest[:2] / digest
        if not source.is_file():
            continue
        parts = [p for p in PurePosixPath(str(name)).parts if p not in ("", ".", "..")]
        if not parts:
            continue
        targets = [virtual_root.joinpath(*parts)]
        if copy_resources:
            targets.append(resources_root.joinpath(*parts))
        for target in targets:
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(source, target)
            except OSError:
                pass


def _substitute(args: list[str], mapping: dict) -> tuple[list[str], set[str]]:
    unknown: set[str] = set()

    def replace(match):
        key = match.group(1)
        if key in mapping:
            return str(mapping[key])
        unknown.add(key)
        return ""

    return [_PLACEHOLDER.sub(replace, arg) for arg in args], unknown


def _memory(config, override: int = 0) -> tuple[int, int]:
    maximum = int(override or 0)
    if maximum <= 0:
        maximum = int(config.get("max_memory_mb") or 0)
    if maximum <= 0:
        from .java import auto_memory_mb

        maximum = auto_memory_mb()
    minimum = max(256, min(int(config.get("min_memory_mb") or 512), maximum))
    return minimum, maximum


def _add_once(args: list[str], flag: str, value: str) -> None:
    if not any(arg == flag or arg.startswith(flag + "=") for arg in args):
        args.append(f"{flag}={value}")


def build_plan(info: VersionInfo, account, config, game_directory: Path | None = None,
               memory_mb: int = 0) -> LaunchPlan:
    if not info.ok or not info.data:
        raise LaunchError(f"实例「{info.name}」不可用：{info.error or '版本数据缺失'}")
    data = info.data
    if not info.client_jar or not info.client_jar.is_file():
        expected = info.game_dir / "versions" / info.name / f"{info.name}.jar"
        raise LaunchError(
            f"实例「{info.name}」缺少客户端 JAR。\n"
            f"  期望位置：{expected}\n"
            "  请先用Minecraft 官方客户端完整运行一次该版本，或等待后续下载功能补全。"
        )

    warnings: list[str] = []
    game_dir = info.game_dir
    runtime_dir = Path(game_directory).expanduser() if game_directory else game_dir
    runtime_dir.mkdir(parents=True, exist_ok=True)
    libraries_dir = game_dir / "libraries"
    assets_dir = game_dir / "assets"
    libraries = [lib for lib in data.get("libraries") or [] if isinstance(lib, dict)]

    classpath: list[str] = []
    missing: list[str] = []
    native_jobs: list[tuple[dict, str]] = []
    for lib in libraries:
        if not rules_allow(lib.get("rules")):
            continue
        path = library_path(lib, libraries_dir)
        if path is None:
            continue
        if path.is_file():
            if path.suffix.lower() == ".jar":
                classpath.append(str(path))
        elif not lib.get("natives"):
            missing.append(str(lib.get("name") or path))
        classifier = _native_classifier(lib)
        if classifier:
            native_jobs.append((lib, classifier))

    if missing:
        preview = "\n".join("    " + item for item in missing[:8])
        more = f"\n    等共 {len(missing)} 个" if len(missing) > 8 else ""
        raise LaunchError(
            "缺少运行库文件：\n" + preview + more + "\n"
            "  请先用Minecraft 官方客户端补全该版本，或等待后续下载功能。"
        )

    seen = set()
    unique_classpath = []
    for entry in classpath + [str(info.client_jar)]:
        key = os.path.normcase(entry)
        if key not in seen:
            seen.add(key)
            unique_classpath.append(entry)
    classpath_string = os.pathsep.join(unique_classpath)

    natives_dir = game_dir / "versions" / info.name / "natives"
    extracted = 0
    try:
        natives_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        natives_dir = data_dir() / "natives" / info.name
        natives_dir.mkdir(parents=True, exist_ok=True)
    for lib, classifier in native_jobs:
        jar = _native_jar(lib, classifier, libraries_dir, libraries)
        if jar is None:
            warnings.append(f"缺少原生库：{lib.get('name')} ({classifier})")
            continue
        try:
            patterns = (lib.get("extract") or {}).get("exclude") or []
            extracted += _extract_natives(jar, natives_dir, patterns)
        except (OSError, zipfile.BadZipFile) as exc:
            warnings.append(f"原生库解压失败：{jar.name} ({exc})")

    index_id = info.asset_index_id()
    index_path = info.asset_index_path()
    if index_id and index_path:
        if not index_path.is_file():
            warnings.append(f"缺少资源索引 {index_id}.json，游戏可能缺少声音/字体。")
        else:
            index = read_json(index_path)
            if isinstance(index, dict) and index.get("virtual"):
                try:
                    _prepare_virtual_assets(game_dir, index_id, index)
                except OSError as exc:
                    warnings.append(f"旧版资源整理失败：{exc}")
    elif not index_id:
        warnings.append("版本未声明资源索引。")

    arguments = data.get("arguments") or {}
    width = int(config.get("width") or 0)
    height = int(config.get("height") or 0)
    features = {
        "is_demo_user": False,
        "has_custom_resolution": False,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }

    if arguments:
        jvm_args = flatten_arguments(arguments.get("jvm"), features)
        game_args = flatten_arguments(arguments.get("game"), features)
    else:
        jvm_args = []
        game_args = str(data.get("minecraftArguments") or "").split()
    if not game_args:
        raise LaunchError("版本 JSON 未提供游戏启动参数。")

    minimum, maximum = _memory(config, memory_mb)
    prefix = [f"-Xms{minimum}M", f"-Xmx{maximum}M"]
    for extra in config.get("jvm_args") or []:
        if isinstance(extra, str) and extra.strip():
            prefix.append(extra.strip())
    jvm_args = prefix + jvm_args

    if not any(arg in ("-cp", "-classpath") for arg in jvm_args):
        jvm_args.extend(["-cp", classpath_string])
    if not any(arg.startswith("-Djava.library.path=") for arg in jvm_args):
        jvm_args.append(f"-Djava.library.path={natives_dir}")
    if not any(arg.startswith("-Dorg.lwjgl.librarypath=") for arg in jvm_args):
        jvm_args.append(f"-Dorg.lwjgl.librarypath={natives_dir}")
    _add_once(jvm_args, "-Dminecraft.launcher.brand", APP_NAME.replace(" ", ""))
    _add_once(jvm_args, "-Dminecraft.launcher.version", __version__)
    if not any(arg.startswith("-Dlog4j2.formatMsgNoLookups=") for arg in jvm_args):
        jvm_args.append("-Dlog4j2.formatMsgNoLookups=true")

    logging_config = data.get("logging") or {}
    client_logging = logging_config.get("client") if isinstance(logging_config, dict) else None
    if isinstance(client_logging, dict):
        log_argument = client_logging.get("argument")
        log_file = (client_logging.get("file") or {}).get("id")
        if log_argument and log_file:
            config_path = assets_dir / "log_configs" / str(log_file)
            if config_path.is_file():
                jvm_args.append(str(log_argument).replace("${path}", str(config_path)))
            else:
                warnings.append(f"缺少日志配置 {log_file}（不影响启动，但日志格式可能不同）。")

    main_class = str(data.get("mainClass") or "")
    if not main_class:
        raise LaunchError("版本 JSON 缺少 mainClass。")
    if info.loader in ("Forge", "NeoForge"):
        for flag in (
            "-Dfml.ignoreInvalidMinecraftCertificates=true",
            "-Dfml.ignorePatchDiscrepancies=true",
        ):
            if not any(arg.startswith(flag.split("=")[0] + "=") for arg in jvm_args):
                jvm_args.append(flag)
        if not any(arg.startswith("-DlibraryDirectory=") for arg in jvm_args):
            jvm_args.append(f"-DlibraryDirectory={libraries_dir}")
    for extra in config.get("game_args") or []:
        if isinstance(extra, str) and extra.strip():
            game_args.append(extra.strip())
    if width > 0 and height > 0:
        if "--width" not in game_args:
            game_args.extend(["--width", str(width), "--height", str(height)])
    if not any(arg in ("--username", "--userName") for arg in game_args):
        game_args.extend(["--username", account.name])
    if "--uuid" not in game_args:
        game_args.extend(["--uuid", account.uuid_hex])
    if not any(arg in ("--accessToken", "--session") for arg in game_args):
        game_args.extend(["--accessToken", "0" * 32])
    if "--gameDir" not in game_args:
        game_args.extend(["--gameDir", str(runtime_dir)])

    token = secrets.token_hex(16)
    mapping = {
        "auth_player_name": account.name,
        "profile_name": account.name,
        "version_name": info.name,
        "game_directory": str(runtime_dir),
        "assets_root": str(assets_dir),
        "game_assets": str(assets_dir / "virtual" / (index_id or "legacy")),
        "assets_index_name": index_id or "legacy",
        "auth_uuid": account.uuid_hex,
        "auth_access_token": token,
        "auth_session": token,
        "clientid": "",
        "auth_xuid": "",
        "user_type": "legacy",
        "version_type": str(data.get("type") or "release"),
        "natives_directory": str(natives_dir),
        "launcher_name": APP_NAME.replace(" ", ""),
        "launcher_version": __version__,
        "classpath": classpath_string,
        "classpath_separator": os.pathsep,
        "library_directory": str(libraries_dir),
        "resolution_width": str(width or 854),
        "resolution_height": str(height or 480),
        "user_properties": "{}",
    }
    jvm_args, unknown_jvm = _substitute(jvm_args, mapping)
    game_args, unknown_game = _substitute(game_args, mapping)
    unknown = unknown_jvm | unknown_game
    if unknown:
        warnings.append("未识别的参数占位符：" + ", ".join(sorted(unknown)[:5]))

    java = choose_java(required_java_major(info), config)
    command = [str(java.path), *jvm_args, main_class, *game_args]
    log_path = logs_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{info.name}.log"
    return LaunchPlan(
        command=command,
        cwd=runtime_dir,
        log_path=log_path,
        version=info,
        java=java,
        account_name=account.name,
        warnings=warnings,
        natives_dir=natives_dir,
    )


def format_command(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    import shlex

    return shlex.join(command)


def tail_log(path: Path, lines: int = 40) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.readlines()
    except OSError:
        return ""
    return "".join(content[-lines:]).rstrip()


def _force_chinese(cwd: Path, base_version: str) -> None:
    code = "zh_CN" if parse_mc_version(base_version) < (1, 13) else "zh_cn"
    options = cwd / "options.txt"
    lines = []
    if options.is_file():
        try:
            with open(options, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except OSError:
            return
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith("lang:"):
            lines[index] = f"lang:{code}\n"
            replaced = True
    if not replaced:
        lines.append(f"lang:{code}\n")
    try:
        options.write_text("".join(lines), encoding="utf-8")
    except OSError:
        return


def execute(plan: LaunchPlan, wait: bool = False, close_console: bool = True) -> int:
    _force_chinese(plan.cwd, plan.version.base_version)
    plan.log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = CREATE_NO_WINDOW if (os.name == "nt" and close_console) else 0
    try:
        with open(plan.log_path, "w", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                plan.command,
                cwd=str(plan.cwd),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
    except OSError as exc:
        raise LaunchError(f"无法启动 Java 进程：{exc}") from exc

    if wait:
        code = process.wait()
        if code == 0:
            ui.ok("游戏已正常退出。")
        else:
            ui.error(f"游戏进程退出，代码 {code}。")
            tail = tail_log(plan.log_path)
            if tail:
                ui.section("日志末尾")
                print(tail)
        return code

    time.sleep(4)
    code = process.poll()
    if code is not None:
        tail = tail_log(plan.log_path)
        ui.error(f"游戏启动后立即退出（代码 {code}）。")
        if tail:
            ui.section("日志末尾")
            print(tail)
        ui.detail(f"完整日志：{plan.log_path}")
        return 1 if code == 0 else code

    ui.ok(f"游戏已启动（PID {process.pid}）。")
    ui.detail(f"日志：{plan.log_path}")
    return 0
