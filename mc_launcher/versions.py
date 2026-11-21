"""版本 JSON 解析：继承链合并、加载器识别、实例扫描。"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .storage import read_json


class VersionError(Exception):
    pass


@dataclass
class VersionInfo:
    name: str
    game_dir: Path
    json_path: Path | None
    data: dict | None
    chain: list[str] = field(default_factory=list)
    base_version: str = ""
    loader: str = "未知"
    loader_version: str = ""
    mods: list[str] = field(default_factory=list)
    client_jar: Path | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.data is not None

    @property
    def loader_text(self) -> str:
        if self.loader in ("", "未知"):
            return "未知"
        text = self.loader
        if self.loader_version:
            text += f" {self.loader_version}"
        if self.mods:
            text += " + " + " + ".join(self.mods)
        return text

    def asset_index_id(self) -> str:
        if not self.data:
            return ""
        index = self.data.get("assetIndex")
        if isinstance(index, dict) and index.get("id"):
            return str(index["id"])
        return str(self.data.get("assets") or "")

    def asset_index_path(self) -> Path | None:
        index_id = self.asset_index_id()
        if not index_id:
            return None
        return self.game_dir / "assets" / "indexes" / f"{index_id}.json"

    @property
    def status(self) -> str:
        if self.error:
            return "损坏"
        has_jar = bool(self.client_jar and self.client_jar.is_file())
        index = self.asset_index_path()
        has_assets = bool(index and index.is_file())
        if has_jar and has_assets:
            return "就绪"
        if not has_jar and not has_assets:
            return "缺客户端/资源"
        if not has_jar:
            return "缺客户端"
        return "缺资源"


def _lib_key(lib: dict):
    name = str(lib.get("name") or "")
    if not name:
        return None
    raw, _, ext = name.partition("@")
    parts = raw.split(":")
    if len(parts) < 3:
        return None
    classifier = parts[3] if len(parts) > 3 else ""
    return (parts[0], parts[1], classifier, ext or "jar")


def _dedupe_libraries(libs) -> list[dict]:
    result = []
    seen = set()
    for lib in libs:
        if not isinstance(lib, dict):
            continue
        key = _lib_key(lib)
        if key is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(lib)
    return result


def _merge(parent: dict, child: dict) -> dict:
    merged = dict(parent)
    for key, value in child.items():
        if key in ("libraries", "arguments", "minecraftArguments", "inheritsFrom"):
            continue
        merged[key] = value

    libraries = _dedupe_libraries(
        list(child.get("libraries") or []) + list(parent.get("libraries") or [])
    )
    if libraries:
        merged["libraries"] = libraries
    else:
        merged.pop("libraries", None)

    parent_args = parent.get("arguments") or {}
    child_args = child.get("arguments") or {}
    if parent.get("arguments") or child.get("arguments"):
        merged["arguments"] = {
            "game": list(parent_args.get("game") or []) + list(child_args.get("game") or []),
            "jvm": list(parent_args.get("jvm") or []) + list(child_args.get("jvm") or []),
        }
    elif child.get("minecraftArguments") or parent.get("minecraftArguments"):
        merged["minecraftArguments"] = (
            child.get("minecraftArguments") or parent.get("minecraftArguments")
        )
        merged.pop("arguments", None)

    merged.pop("inheritsFrom", None)
    return merged


def _load_json(path: Path) -> dict:
    data = read_json(path)
    if not isinstance(data, dict):
        raise VersionError(f"无法读取版本 JSON：{path}")
    return data


def resolve_version(game_dir: Path, name: str, _stack=None) -> VersionInfo:
    _stack = list(_stack or [])
    if name in _stack:
        raise VersionError("版本继承出现循环：" + " -> ".join(_stack + [name]))

    json_path = game_dir / "versions" / name / f"{name}.json"
    if not json_path.is_file():
        raise VersionError(f"缺少版本 JSON：{json_path}")
    data = _load_json(json_path)
    chain = [name]

    parent_name = data.get("inheritsFrom")
    if parent_name:
        parent = resolve_version(game_dir, str(parent_name), _stack + [name])
        data = _merge(parent.data or {}, data)
        chain += parent.chain

    client_jar = None
    for candidate in chain:
        jar = game_dir / "versions" / candidate / f"{candidate}.jar"
        if jar.is_file():
            client_jar = jar
            break
    if client_jar is None and data.get("jar"):
        jar_name = str(data["jar"])
        jar = game_dir / "versions" / jar_name / f"{jar_name}.jar"
        if jar.is_file():
            client_jar = jar

    base = chain[-1] if chain else name
    loader, loader_version, mods = detect_loader(data, base)

    return VersionInfo(
        name=name,
        game_dir=game_dir,
        json_path=json_path,
        data=data,
        chain=chain,
        base_version=base,
        loader=loader,
        loader_version=loader_version,
        mods=mods,
        client_jar=client_jar,
    )


def _arg_strings(data: dict) -> list[str]:
    result = []
    arguments = data.get("arguments") or {}
    for key in ("game", "jvm"):
        for item in arguments.get(key) or []:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                value = item.get("value")
                if isinstance(value, str):
                    result.append(value)
                elif isinstance(value, list):
                    result.extend(str(v) for v in value if isinstance(v, str))
    if data.get("minecraftArguments"):
        result.append(str(data["minecraftArguments"]))
    return result


def detect_loader(data: dict, base_version: str = "") -> tuple[str, str, list[str]]:
    libraries = [str(lib.get("name") or "") for lib in data.get("libraries") or [] if isinstance(lib, dict)]
    blob = " ".join(libraries).lower()
    main_class = str(data.get("mainClass") or "").lower()
    arg_blob = " ".join(_arg_strings(data)).lower()
    text = f"{blob} {main_class} {arg_blob}"

    mods = ["OptiFine"] if "optifine" in text else []
    loader = "原版"
    loader_version = ""

    def artifact_version(needles):
        for raw in libraries:
            low = raw.lower()
            if any(needle in low for needle in needles):
                parts = raw.split("@")[0].split(":")
                if len(parts) >= 3:
                    return parts[2]
        return ""

    if "net.neoforged" in blob or "neoforge" in main_class:
        loader = "NeoForge"
        loader_version = artifact_version(("neoforge", "net.neoforged"))
    elif "quilt" in blob or "quilt" in main_class:
        loader = "Quilt"
        loader_version = artifact_version(("quilt-loader", "quiltmc"))
    elif "fabric" in blob or "fabricmc" in main_class:
        loader = "Fabric"
        loader_version = artifact_version(("fabric-loader", "fabricmc"))
    elif (
        "net.minecraftforge" in blob
        or "fmltweaker" in text
        or "bootstraplauncher" in main_class
        or "forge" in main_class
    ):
        loader = "Forge"
        loader_version = artifact_version(("net.minecraftforge:forge", "fmlloader", "forge"))
    elif "optifine" in blob or "optifine" in main_class:
        loader = "OptiFine"

    if loader == "Forge" and loader_version and base_version:
        prefix = base_version + "-"
        if loader_version.startswith(prefix):
            loader_version = loader_version[len(prefix):]
    if loader == "OptiFine":
        mods = []
    return loader, loader_version, mods


def parse_mc_version(text: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not match:
        return (0,)
    return tuple(int(x) for x in match.groups() if x is not None)


def required_java_major(info: VersionInfo) -> int:
    java_version = (info.data or {}).get("javaVersion") or {}
    major = java_version.get("majorVersion")
    if isinstance(major, int) and major > 0:
        return major
    version = parse_mc_version(info.base_version)
    if version >= (1, 20, 5):
        return 21
    if version >= (1, 17):
        return 17
    return 8


def _natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def scan_versions(game_dir: Path) -> list[VersionInfo]:
    versions_dir = game_dir / "versions"
    if not versions_dir.is_dir():
        return []
    results: list[VersionInfo] = []
    try:
        entries = sorted(versions_dir.iterdir(), key=lambda p: _natural_key(p.name))
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir():
            continue
        json_path = entry / f"{entry.name}.json"
        if not json_path.is_file():
            if any(entry.glob("*.jar")):
                results.append(VersionInfo(
                    name=entry.name,
                    game_dir=game_dir,
                    json_path=None,
                    data=None,
                    error="缺少版本 JSON",
                ))
            continue
        try:
            results.append(resolve_version(game_dir, entry.name))
        except (VersionError, OSError, ValueError) as exc:
            results.append(VersionInfo(
                name=entry.name,
                game_dir=game_dir,
                json_path=json_path,
                data=None,
                error=str(exc),
            ))
    return results


def find_instance(infos: list[VersionInfo], query: str) -> tuple[VersionInfo | None, list[VersionInfo]]:
    query = (query or "").strip()
    if not query:
        return None, []
    usable = [info for info in infos if info.ok]
    exact = [info for info in usable if info.name.lower() == query.lower()]
    if exact:
        return exact[0], exact[1:]
    partial = [info for info in usable if query.lower() in info.name.lower()]
    if len(partial) == 1:
        return partial[0], []
    if partial:
        return None, partial
    names = [info.name for info in usable]
    close = difflib.get_close_matches(query, names, n=5, cutoff=0.55)
    return None, [info for info in usable if info.name in close]
