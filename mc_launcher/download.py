"""下载与补全：版本 JSON、客户端、运行库、资源。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import ui
from .i18n import t
from .launch import _maven_relative, _native_classifier, library_path, rules_allow
from .storage import read_json
from .versions import resolve_version

MANIFEST_URL = "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"
OFFICIAL_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RESOURCES_URL = "https://bmclapi2.bangbang93.com/assets"
DEFAULT_LIBS = "https://bmclapi2.bangbang93.com/maven/"
BMCLAPI = "https://bmclapi2.bangbang93.com"
USER_AGENT = {"User-Agent": "CMLauncher/1.1"}
# BMCLAPI 的 CDN 证书链在部分 Windows 上不完整，下载文件仍会校验 SHA1。
_SSL = ssl._create_unverified_context()


def _mirror(url: str) -> str:
    for old, new in (
        ("https://piston-meta.mojang.com", BMCLAPI),
        ("https://piston-data.mojang.com", BMCLAPI),
        ("https://launchermeta.mojang.com", BMCLAPI),
        ("https://launcher.mojang.com", BMCLAPI),
        ("https://resources.download.minecraft.net", BMCLAPI + "/assets"),
        ("https://libraries.minecraft.net", BMCLAPI + "/maven"),
    ):
        if url.startswith(old):
            return new + url[len(old):]
    return url


class DownloadError(Exception):
    pass


def _fallbacks(url: str) -> list[str]:
    if url.startswith(BMCLAPI + "/maven/"):
        return ["https://libraries.minecraft.net/" + url[len(BMCLAPI + "/maven/"):]]
    if url.startswith(BMCLAPI + "/assets/"):
        return ["https://resources.download.minecraft.net/" + url[len(BMCLAPI + "/assets/"):]]
    if url.startswith(BMCLAPI + "/v1/objects/"):
        return ["https://piston-data.mojang.com" + url[len(BMCLAPI):]]
    if url.startswith(BMCLAPI + "/v1/packages/"):
        return ["https://piston-meta.mojang.com" + url[len(BMCLAPI):]]
    return []


def _get(url: str, mirror: bool = True) -> bytes:
    if mirror:
        url = _mirror(url)
    try:
        request = urllib.request.Request(url, headers=USER_AGENT)
        with urllib.request.urlopen(request, timeout=90, context=_SSL) as response:
            return response.read()
    except Exception as exc:
        raise DownloadError(f"请求失败：{url}\n  {exc}") from exc


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_manifest() -> dict:
    last_error = None
    for url, mirror in ((MANIFEST_URL, True), (OFFICIAL_MANIFEST, False)):
        try:
            data = json.loads(_get(url, mirror=mirror).decode("utf-8"))
        except Exception as exc:
            last_error = exc
            continue
        if isinstance(data, dict) and data.get("versions"):
            return data
    raise DownloadError(f"获取版本清单失败（BMCLAPI 与官方源均不可用）：{last_error}")


def list_versions(channel: str = "release", limit: int = 30):
    data = fetch_manifest()
    versions = [
        item for item in data.get("versions", [])
        if channel == "all" or item.get("type") == channel
    ]
    return versions[:limit], data.get("latest") or {}


def download_file(url: str, destination: Path, sha1: str | None = None,
                  size: int | None = None, retries: int = 3) -> bool:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = _mirror(url)
    candidates = [url] + [item for item in _fallbacks(url) if item != url]
    if destination.is_file():
        try:
            if sha1:
                if (size is None or destination.stat().st_size == size) and _sha1(destination) == sha1:
                    return False
            elif size is None or destination.stat().st_size == size:
                return False
        except OSError:
            pass

    errors = []
    for candidate in candidates:
        temporary = destination.with_name(destination.name + ".part")
        for attempt in range(retries):
            try:
                request = urllib.request.Request(candidate, headers=USER_AGENT)
                with urllib.request.urlopen(request, timeout=90, context=_SSL) as response, open(temporary, "wb") as output:
                    shutil.copyfileobj(response, output, 1 << 20)
                if sha1 and _sha1(temporary) != sha1:
                    raise DownloadError("SHA1 校验失败")
                os.replace(temporary, destination)
                return True
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
                time.sleep(1 + attempt)
        try:
            temporary.unlink()
        except OSError:
            pass
    raise DownloadError("下载失败：\n  " + "\n  ".join(errors[-3:]))


def _maven_base(lib: dict) -> str:
    base = str(lib.get("url") or "").strip()
    if base:
        return base.rstrip("/") + "/"
    name = str(lib.get("name") or "").lower()
    if "net.minecraftforge" in name:
        return "https://maven.minecraftforge.net/"
    if "net.neoforged" in name:
        return "https://maven.neoforged.net/releases/"
    if "fabricmc" in name:
        return "https://maven.fabricmc.net/"
    if "quiltmc" in name:
        return "https://maven.quiltmc.org/repository/release/"
    return DEFAULT_LIBS


def _artifact_url(lib: dict) -> str | None:
    artifact = (lib.get("downloads") or {}).get("artifact") or {}
    if artifact.get("url"):
        return str(artifact["url"])
    relative = _maven_relative(str(lib.get("name") or ""))
    return _maven_base(lib) + relative.as_posix() if relative else None


def _native_url(lib: dict, classifier: str) -> str | None:
    classifiers = (lib.get("downloads") or {}).get("classifiers") or {}
    entry = classifiers.get(classifier) or {}
    if entry.get("url"):
        return str(entry["url"])
    raw = str(lib.get("name") or "").split("@")[0].split(":")
    if len(raw) < 3:
        return None
    relative = _maven_relative(f"{raw[0]}:{raw[1]}:{raw[2]}:{classifier}")
    return _maven_base(lib) + relative.as_posix() if relative else None


def _asset_url(digest: str) -> str:
    return f"{RESOURCES_URL}/{digest[:2]}/{digest}"


def _ensure_assets(info, workers: int = 8):
    index_id = info.asset_index_id()
    if not index_id:
        return 0, []
    index_path = info.game_dir / "assets" / "indexes" / f"{index_id}.json"
    index = read_json(index_path)
    if not isinstance(index, dict):
        return 0, [f"缺少资源索引：{index_path}"]
    objects = index.get("objects") or {}
    missing = []
    for _name, meta in objects.items():
        if not isinstance(meta, dict) or not meta.get("hash"):
            continue
        digest = str(meta["hash"])
        destination = info.game_dir / "assets" / "objects" / digest[:2] / digest
        if destination.is_file():
            continue
        missing.append((_asset_url(digest), destination, digest, meta.get("size")))
    if not missing:
        return 0, []

    ui.detail(f"资源待下载 {len(missing)} 个文件...")
    completed = 0
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(download_file, url, destination, sha1, size)
            for url, destination, sha1, size in missing
        ]
        for future in as_completed(futures):
            try:
                if future.result():
                    completed += 1
            except DownloadError as exc:
                errors.append(str(exc))
            if (completed + len(errors)) % 200 == 0:
                ui.detail(f"资源进度 {completed + len(errors)}/{len(missing)}")
    return completed, errors


def ensure_files(info) -> tuple[int, list[str]]:
    data = info.data or {}
    game_dir = info.game_dir
    libraries_dir = game_dir / "libraries"
    jobs = []
    warnings = []

    client = (data.get("downloads") or {}).get("client") or {}
    jar_id = str(data.get("jar") or info.base_version or info.name)
    jar_path = game_dir / "versions" / jar_id / f"{jar_id}.jar"
    if not jar_path.is_file():
        if client.get("url"):
            jobs.append((str(client["url"]), jar_path, client.get("sha1"), client.get("size")))
        else:
            warnings.append("版本 JSON 没有客户端下载地址。")

    for lib in data.get("libraries") or []:
        if not isinstance(lib, dict) or not rules_allow(lib.get("rules")):
            continue
        path = library_path(lib, libraries_dir)
        if path and not path.is_file() and not lib.get("natives"):
            url = _artifact_url(lib)
            if url:
                jobs.append((url, path, (lib.get("downloads") or {}).get("artifact", {}).get("sha1"),
                             (lib.get("downloads") or {}).get("artifact", {}).get("size")))
            else:
                warnings.append(f"无法确定下载地址：{lib.get('name')}")
        classifier = _native_classifier(lib)
        if classifier:
            existing = _native_local(lib, classifier, libraries_dir)
            if existing is None:
                url = _native_url(lib, classifier)
                target = _native_target(lib, classifier, libraries_dir)
                if url and target:
                    jobs.append((url, target, None, None))
                else:
                    warnings.append(f"无法确定原生库地址：{lib.get('name')}")

    index = data.get("assetIndex") or {}
    if isinstance(index, dict) and index.get("url"):
        index_path = game_dir / "assets" / "indexes" / f"{index['id']}.json"
        if not index_path.is_file():
            jobs.append((str(index["url"]), index_path, index.get("sha1"), index.get("size")))

    logging_client = ((data.get("logging") or {}).get("client") or {})
    log_file = logging_client.get("file") or {}
    if log_file.get("url") and log_file.get("id"):
        log_path = game_dir / "assets" / "log_configs" / str(log_file["id"])
        if not log_path.is_file():
            jobs.append((str(log_file["url"]), log_path, log_file.get("sha1"), log_file.get("size")))

    downloaded = 0
    errors = []
    for index_no, (url, destination, sha1, size) in enumerate(jobs, 1):
        try:
            if download_file(url, destination, sha1, size):
                downloaded += 1
                ui.detail(f"[{index_no}/{len(jobs)}] {destination.name}")
        except DownloadError as exc:
            errors.append(str(exc))
            ui.warn(f"失败：{destination.name}")

    asset_count, asset_errors = _ensure_assets(info)
    downloaded += asset_count
    errors.extend(asset_errors)
    for warning in warnings:
        ui.warn(warning)
    errors.extend(warnings)
    return downloaded, errors


def _native_local(lib: dict, classifier: str, libraries_dir: Path):
    classifiers = (lib.get("downloads") or {}).get("classifiers") or {}
    entry = classifiers.get(classifier) or {}
    if entry.get("path"):
        candidate = libraries_dir / str(entry["path"])
        if candidate.is_file():
            return candidate
    raw = str(lib.get("name") or "").split("@")[0].split(":")
    if len(raw) >= 3:
        relative = _maven_relative(f"{raw[0]}:{raw[1]}:{raw[2]}:{classifier}")
        if relative and (libraries_dir / relative).is_file():
            return libraries_dir / relative
    return None


def _native_target(lib: dict, classifier: str, libraries_dir: Path):
    classifiers = (lib.get("downloads") or {}).get("classifiers") or {}
    entry = classifiers.get(classifier) or {}
    if entry.get("path"):
        return libraries_dir / str(entry["path"])
    raw = str(lib.get("name") or "").split("@")[0].split(":")
    if len(raw) >= 3:
        relative = _maven_relative(f"{raw[0]}:{raw[1]}:{raw[2]}:{classifier}")
        return libraries_dir / relative if relative else None
    return None


def install(game_dir: Path, version_id: str) -> None:
    version_id = version_id.strip()
    if not version_id:
        raise DownloadError("请指定游戏版本，例如：-download game 1.20.1")
    game_dir = Path(game_dir)
    json_path = game_dir / "versions" / version_id / f"{version_id}.json"

    if not json_path.is_file():
        ui.info(t("获取 BMCLAPI 版本清单...", "Fetching BMCLAPI version manifest..."))
        manifest = fetch_manifest()
        entry = next((v for v in manifest["versions"] if v.get("id") == version_id), None)
        if entry is None:
            raise DownloadError(t(f"版本清单中没有 {version_id}，可用 -download list 查看。",
                                  f"Version {version_id} not found; try -download list."))
        ui.info(t(f"下载版本 JSON：{version_id}", f"Downloading version JSON: {version_id}"))
        download_file(str(entry["url"]), json_path, entry.get("sha1"), entry.get("size"))

    try:
        info = resolve_version(game_dir, version_id)
    except Exception as exc:
        raise DownloadError(t(f"版本解析失败：{exc}", f"Failed to parse version: {exc}")) from exc
    ui.info(t(f"目标：{info.game_dir}", f"Target: {info.game_dir}"))
    ui.info(t(f"实例：{info.name}  游戏版本：{info.base_version}  加载器：{info.loader_text}",
              f"Instance: {info.name}  Game: {info.base_version}  Loader: {info.loader_text}"))
    ui.info(t("检查并补全客户端、运行库、资源...",
              "Checking client, libraries and assets..."))
    count, errors = ensure_files(info)
    if errors:
        for message in errors[:5]:
            ui.detail(message)
        raise DownloadError(t(f"完成 {count} 个文件，仍有 {len(errors)} 个失败。",
                              f"Downloaded {count} file(s), {len(errors)} failed."))
    ui.ok(t(f"下载完成，共处理 {count} 个文件。", f"Done. {count} file(s) processed."))
