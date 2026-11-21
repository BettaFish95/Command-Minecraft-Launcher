"""模组加载器下载与安装：Forge、NeoForge、Fabric。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import ui
from .download import _get, download_file, install as install_version
from .i18n import t
from .instances import safe_folder_name
from .java import choose_java
from .launch import _maven_relative
from .paths import data_dir
from .storage import read_json, write_json
from .versions import parse_mc_version, resolve_version, scan_versions

FORGE_META = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
NEO_META = "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/maven-metadata.xml"
NEO_FORGE_META = "https://bmclapi2.bangbang93.com/maven/net/neoforged/forge/maven-metadata.xml"
FABRIC_META = "https://meta.fabricmc.net/v2/versions/loader"
MODRINTH_API = "https://api.modrinth.com/v2/project/fabric-api/version"


class LoaderError(Exception):
    pass


def normalize_loader(text: str) -> str:
    value = (text or "").strip().lower().replace("-", "").replace("_", "")
    if value in ("forge", "fmlloader"):
        return "forge"
    if value in ("neoforge", "neo"):
        return "neoforge"
    if value == "fabric":
        return "fabric"
    raise LoaderError(f"暂不支持模组加载器：{text}（支持 Forge、NeoForge、Fabric）")


def _version_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _metadata_versions(url: str) -> list[str]:
    try:
        root = ET.fromstring(_get(url))
    except (ET.ParseError, Exception) as exc:
        raise LoaderError(f"读取版本列表失败：{exc}") from exc
    return [node.text.strip() for node in root.iter("version") if node.text]


def forge_versions(mc: str) -> list[str]:
    prefix = mc + "-"
    versions = [
        item[len(prefix):] for item in _metadata_versions(FORGE_META)
        if item.startswith(prefix)
    ]
    versions = sorted(set(versions), key=_version_key, reverse=True)
    if not versions:
        raise LoaderError(f"没有找到 {mc} 对应的 Forge 版本。")
    return versions


def _neo_prefix(mc: str) -> str:
    parts = mc.split(".")
    if parts[:2] == ["1", "20"] and len(parts) >= 3 and parts[2] == "1":
        return "47.1."
    if len(parts) >= 3:
        return f"{parts[1]}.{parts[2]}."
    return f"{parts[1]}.0."


def neoforge_versions(mc: str) -> list[str]:
    if mc == "1.20.1":
        versions = [item for item in _metadata_versions(NEO_FORGE_META) if item.startswith("47.1.")]
    else:
        prefix = _neo_prefix(mc)
        versions = [item for item in _metadata_versions(NEO_META) if item.startswith(prefix)]
    versions = sorted(set(versions), key=_version_key, reverse=True)
    if not versions:
        raise LoaderError(f"没有找到 {mc} 对应的 NeoForge 版本。")
    return versions


def fabric_versions(mc: str) -> list[str]:
    try:
        data = json.loads(_get(f"{FABRIC_META}/{mc}"))
    except Exception as exc:
        raise LoaderError(f"读取 Fabric 版本失败：{exc}") from exc
    stable = [
        item["loader"]["version"] for item in data
        if item.get("loader", {}).get("stable") and item["loader"].get("version")
    ]
    all_versions = [
        item["loader"]["version"] for item in data
        if item.get("loader", {}).get("version")
    ]
    versions = stable or all_versions
    if not versions:
        raise LoaderError(f"没有找到 {mc} 对应的 Fabric Loader 版本。")
    return versions


def fabric_api_versions(mc: str) -> list[tuple[str, str]]:
    query = urllib.parse.urlencode({
        "game_versions": json.dumps([mc]),
        "loaders": json.dumps(["fabric"]),
    })
    try:
        data = json.loads(_get(f"{MODRINTH_API}?{query}"))
    except Exception as exc:
        raise LoaderError(f"读取 Fabric API 版本失败：{exc}") from exc
    result = []
    for item in data:
        files = item.get("files") or []
        url = next((f.get("url") for f in files if f.get("primary")), None)
        if not url and files:
            url = files[0].get("url")
        if url and item.get("version_number"):
            result.append((str(item["version_number"]), str(url)))
    if not result:
        raise LoaderError(f"没有找到 {mc} 对应的 Fabric API 版本。")
    return result


def choose_version(versions: list[str], label: str, interactive: bool) -> str:
    if not versions:
        raise LoaderError(t(f"没有可用的 {label} 版本。", f"No {label} versions available."))
    if not interactive:
        return versions[0]
    ui.info(t(f"可用 {label} 版本：", f"Available {label} versions:"))
    for index, version in enumerate(versions[:20], 1):
        ui.detail(f"{index}. {version}")
    raw = ui.ask(t("选择版本序号", "Select version number"), "1")
    try:
        selected = int(raw) - 1
    except ValueError:
        selected = 0
    if selected < 0 or selected >= min(20, len(versions)):
        selected = 0
    return versions[selected]


def _java_for_mc(mc: str, config):
    version = parse_mc_version(mc)
    required = 21 if version >= (1, 20, 5) else 17 if version >= (1, 17) else 8
    return choose_java(required, config)


def cleanup_installer_residue(game_dir: Path, keep_id: str = "") -> None:
    versions = game_dir / "versions"
    if not versions.is_dir():
        return
    for child in list(versions.iterdir()):
        if not child.is_dir() or child.name == keep_id:
            continue
        if (child / f"{child.name}.json").is_file():
            continue
        name = child.name.lower()
        residue = any(mark in name for mark in (".tmp", ".temp", "installer", "-install"))
        try:
            empty = not any(child.iterdir())
        except OSError:
            empty = False
        if residue or empty:
            try:
                shutil.rmtree(child)
                ui.detail(f"已清理安装残留：{child.name}")
            except OSError:
                pass


def adopt_loader_folder(game_dir: Path, version_id: str, instance_name: str) -> str:
    """把加载器版本目录改名为实例目录，原安装目录随之消失。"""
    versions = game_dir / "versions"
    source = versions / version_id
    if not source.is_dir():
        return version_id
    target_name = safe_folder_name(instance_name)
    target = versions / target_name
    if target.resolve() == source.resolve():
        return version_id
    if target.exists():
        index = 2
        while (versions / f"{target_name}-{index}").exists():
            index += 1
        target_name = f"{target_name}-{index}"
        target = versions / target_name
    try:
        shutil.move(str(source), str(target))
    except OSError:
        return version_id

    old_json = target / f"{version_id}.json"
    new_json = target / f"{target_name}.json"
    try:
        data = read_json(old_json)
        if not isinstance(data, dict):
            raise ValueError("版本 JSON 无效")
        data["id"] = target_name
        write_json(new_json, data)
        if old_json != new_json and old_json.is_file():
            old_json.unlink()
        info = resolve_version(game_dir, target_name)
        if not info.ok:
            raise ValueError(info.error or "版本解析失败")
    except Exception:
        try:
            if new_json.is_file():
                new_json.replace(old_json)
            shutil.move(str(target), str(source))
        except OSError:
            pass
        return version_id

    ui.detail(f"加载器目录已整理为实例目录：{target_name}")
    return target_name


def _legacy_install(game_dir: Path, installer: Path) -> str:
    try:
        with zipfile.ZipFile(installer) as archive:
            profile = json.loads(archive.read("install_profile.json").decode("utf-8"))
            info = profile.get("versionInfo")
            if not isinstance(info, dict) or not info.get("id"):
                return ""
            libraries = [
                lib for lib in info.get("libraries") or []
                if not (isinstance(lib, dict) and lib.get("clientreq") is False)
            ]
            info["libraries"] = libraries
            version_id = str(info["id"])
            write_json(game_dir / "versions" / version_id / f"{version_id}.json", info)
            file_path = (profile.get("install") or {}).get("filePath")
            if file_path and file_path in archive.namelist():
                forge_lib = next(
                    (lib for lib in libraries if str(lib.get("name", "")).startswith("net.minecraftforge:forge:")),
                    None,
                )
                relative = _maven_relative(str(forge_lib.get("name"))) if forge_lib else None
                if relative:
                    target = game_dir / "libraries" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(file_path))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        return ""
    ui.info("检测到旧版 Forge 安装包，使用内置配置安装...")
    install_version(game_dir, version_id)
    return version_id


def _run_installer(game_dir: Path, url: str, java, label: str, fallback_url: str | None = None) -> str:
    installer = data_dir() / "cache" / url.rsplit("/", 1)[-1]
    ui.info(f"下载 {label} 安装器...")
    try:
        download_file(url, installer)
    except Exception:
        if fallback_url:
            download_file(fallback_url, installer)
        else:
            raise
    legacy_id = _legacy_install(game_dir, installer)
    if legacy_id:
        return legacy_id
    launcher_profiles = game_dir / "launcher_profiles.json"
    if not launcher_profiles.is_file():
        write_json(launcher_profiles, {"profiles": {}, "settings": {}, "version": 3})
    ui.info(f"运行 {label} 安装器（可能需要几分钟）...")
    command = [str(java.path), "-jar", str(installer), "--installClient", str(game_dir)]
    try:
        process = subprocess.run(
            command,
            cwd=str(game_dir.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LoaderError(f"{label} 安装器启动失败：{exc}") from exc
    if process.returncode != 0:
        tail = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()[-1200:]
        raise LoaderError(f"{label} 安装器退出代码 {process.returncode}：\n{tail}")
    ui.detail(f"{label} 安装器执行完成。")
    return ""


def _installed_name(game_dir: Path, mc: str, loader: str) -> str:
    wanted = "neoforge" if loader == "neoforge" else loader
    for info in scan_versions(game_dir):
        if info.ok and info.base_version == mc and info.loader.lower() == wanted:
            return info.name
    return ""


def install_forge(game_dir: Path, mc: str, version: str, config) -> str:
    artifact = f"{mc}-{version}"
    url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{artifact}/forge-{artifact}-installer.jar"
    fallback = f"https://bmclapi2.bangbang93.com/maven/net/minecraftforge/forge/{artifact}/forge-{artifact}-installer.jar"
    legacy_id = _run_installer(game_dir, url, _java_for_mc(mc, config), "Forge", fallback)
    return _installed_name(game_dir, mc, "forge") or legacy_id or f"{mc}-forge-{version}"

def install_neoforge(game_dir: Path, mc: str, version: str, config) -> str:
    if mc == "1.20.1":
        url = f"https://bmclapi2.bangbang93.com/maven/net/neoforged/forge/{version}/forge-{version}-installer.jar"
        fallback = f"https://maven.neoforged.net/releases/net/neoforged/forge/{version}/forge-{version}-installer.jar"
    else:
        url = f"https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
        fallback = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
    legacy_id = _run_installer(game_dir, url, _java_for_mc(mc, config), "NeoForge", fallback)
    return _installed_name(game_dir, mc, "neoforge") or legacy_id or f"neoforge-{version}"


def install_fabric(game_dir: Path, mc: str, loader: str, config) -> tuple[str, str]:
    try:
        profile = json.loads(_get(f"{FABRIC_META}/{mc}/{loader}/profile/json"))
    except Exception as exc:
        raise LoaderError(f"下载 Fabric 配置失败：{exc}") from exc
    version_id = str(profile.get("id") or f"fabric-loader-{loader}-{mc}")
    write_json(game_dir / "versions" / version_id / f"{version_id}.json", profile)
    install_version(game_dir, version_id)
    return version_id, loader


def choose_fabric_api(mc: str, interactive: bool) -> tuple[str, str]:
    versions = fabric_api_versions(mc)
    if not interactive:
        return versions[0]
    ui.info(t("可用 Fabric API 版本：", "Available Fabric API versions:"))
    for index, (version, _url) in enumerate(versions[:20], 1):
        ui.detail(f"{index}. {version}")
    raw = ui.ask(t("选择 Fabric API 版本序号", "Select Fabric API version"), "1")
    try:
        selected = int(raw) - 1
    except ValueError:
        selected = 0
    if selected < 0 or selected >= min(20, len(versions)):
        selected = 0
    return versions[selected]


def choose_loader(mc: str, loader_text: str, interactive: bool = False) -> dict:
    loader = normalize_loader(loader_text)
    if loader == "forge":
        return {"loader": loader, "version": choose_version(forge_versions(mc), "Forge", interactive)}
    if loader == "neoforge":
        return {"loader": loader, "version": choose_version(neoforge_versions(mc), "NeoForge", interactive)}
    version = choose_version(fabric_versions(mc), "Fabric Loader", interactive)
    return {"loader": loader, "version": version, "api": choose_fabric_api(mc, interactive)}


def install_fabric_api(game_dir: Path, version: str, url: str, mods_dir: Path | None = None) -> str:
    mods = Path(mods_dir) if mods_dir else game_dir / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    target = mods / f"fabric-api-{version}.jar"
    ui.info(f"下载 Fabric API {version}...")
    download_file(url, target)
    return version


def install_loader(game_dir: Path, mc: str, loader_text: str, config,
                   interactive: bool = False, mods_dir: Path | None = None,
                   selection: dict | None = None) -> str:
    selection = selection or choose_loader(mc, loader_text, interactive)
    loader = selection["loader"]
    ui.info(t(f"先安装原版实例：{mc}", f"Installing vanilla {mc} first..."))
    install_version(game_dir, mc)

    if loader == "forge":
        version = selection["version"]
        name = install_forge(game_dir, mc, version, config)
        ui.ok(t(f"Forge {version} 安装完成（实例：{name}）。",
                f"Forge {version} installed (instance: {name})."))
        return name
    if loader == "neoforge":
        version = selection["version"]
        name = install_neoforge(game_dir, mc, version, config)
        ui.ok(t(f"NeoForge {version} 安装完成（实例：{name}）。",
                f"NeoForge {version} installed (instance: {name})."))
        return name

    loader_version = selection["version"]
    name, _ = install_fabric(game_dir, mc, loader_version, config)
    ui.ok(t(f"Fabric Loader {loader_version} 安装完成（实例：{name}）。",
            f"Fabric Loader {loader_version} installed (instance: {name})."))
    api_version, api_url = selection["api"]
    install_fabric_api(game_dir, api_version, api_url, mods_dir)
    ui.ok(t(f"Fabric API {api_version} 已下载到 mods。",
            f"Fabric API {api_version} downloaded to mods."))
    return name
    return name
