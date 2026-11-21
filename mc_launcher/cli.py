"""命令行入口与交互菜单。"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from . import APP_NAME, __version__, i18n, loaders, ui
from .accounts import AccountError, AccountStore
from .config import Config
from .instances import InstanceStore, safe_folder_name
from .java import JavaError, discover_javas
from .launch import LaunchError, build_plan, execute, format_command
from .paths import app_dir, default_game_dir, find_game_dirs, pick_folder
from .versions import (
    VersionInfo,
    find_instance,
    required_java_major,
    scan_versions,
)

from .download import DownloadError, install as download_install, list_versions

t = i18n.t


class UsageError(Exception):
    pass


VALUE_OPTIONS = {
    "-u": "user",
    "--user": "user",
    "--username": "user",
    "--game-dir": "game_dir",
    "--gamedir": "game_dir",
    "--dir": "game_dir",
    "--java": "java",
    "--name": "instance_name",
    "--memory": "memory",
    "--lang": "lang",
}
FLAG_OPTIONS = {
    "--dry-run": "dry_run",
    "--dryrun": "dry_run",
    "--wait": "wait",
    "--deep": "deep",
    "--isolate": "isolate",
    "--no-isolate": "no_isolate",
    "-h": "help",
    "--help": "help",
    "-?": "help",
}


def parse_options(args: list[str]) -> tuple[dict, list[str]]:
    options = {
        "user": None,
        "game_dir": None,
        "java": None,
        "instance_name": None,
        "memory": None,
        "lang": None,
        "isolate": False,
        "no_isolate": False,
        "dry_run": False,
        "wait": False,
        "deep": False,
        "help": False,
    }
    rest: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        key = token.lower()
        if key in VALUE_OPTIONS:
            if index + 1 >= len(args):
                raise UsageError(f"参数 {token} 缺少取值。")
            options[VALUE_OPTIONS[key]] = args[index + 1]
            index += 2
            continue
        if key in FLAG_OPTIONS:
            options[FLAG_OPTIONS[key]] = True
            index += 1
            continue
        rest.append(token)
        index += 1
    return options, rest


def help_text() -> None:
    ui.banner()
    if i18n.is_en():
        print("Usage:")
        print("  \"CM Launcher.exe\" -crate a new player <name>       Create offline account")
        print("  \"CM Launcher.exe\" -search game                     Find game instances")
        print("  \"CM Launcher.exe\" -start game <instance>           Launch an instance")
        print("  \"CM Launcher.exe\" -download game <version>         Fill missing files only")
        print("  \"CM Launcher.exe\" -install game <version>-forge    Install instance (latest Forge)")
        print("  \"CM Launcher.exe\" -install game <version> with forge  Manual loader version")
        print("  \"CM Launcher.exe\" -download list                   List downloadable versions")
        print()
        print("Other commands:")
        print("  \"CM Launcher.exe\" -list accounts                   List accounts")
        print("  \"CM Launcher.exe\" -search java                     List Java runtimes")
        print("  \"CM Launcher.exe\" -instance list                   List registered instances")
        print("  \"CM Launcher.exe\" -instance dir <name>             Show instance folder")
        print("  \"CM Launcher.exe\" -instance open <name>            Open instance folder")
        print("  \"CM Launcher.exe\" -instance move <name> <path>     Move isolated instance")
        print("  \"CM Launcher.exe\" -instance memory <name> <MB>     Set instance memory")
        print("  \"CM Launcher.exe\" -help                            Show this help")
        print()
        print("Options:")
        print("  -u, --user <name>       Account to use")
        print("  --game-dir <path>       .minecraft directory")
        print("  --java <path>           java.exe path")
        print("  --dry-run               Print launch command only")
        print("  --wait                  Wait for game exit")
        print("  --deep                  Deep search for game folders")
        print("  --name <name>           Instance name for installation")
        print("  --isolate / --no-isolate  Version isolation")
        print("  --memory <MB>           Max memory")
        print("  --lang zh|en            UI language")
        print()
        print("Examples:")
        print("  \"CM Launcher.exe\" -crate a new player Steve")
        print("  \"CM Launcher.exe\" -install game 1.20.1-forge --name MyPack --isolate --memory 4096")
        print("  \"CM Launcher.exe\" -search game")
        print("  \"CM Launcher.exe\" -start game MyPack")
        return
    print("用法：")
    print("  \"CM Launcher.exe\" -crate a new player <用户名>     创建离线账户（UUID 随机）")
    print("  \"CM Launcher.exe\" -search game                     搜索本机游戏实例")
    print("  \"CM Launcher.exe\" -start game <实例名称>           启动游戏")
    print("  \"CM Launcher.exe\" -download game <版本>             只补全文件，不建实例")
    print("  \"CM Launcher.exe\" -install game <版本>-<模组加载器>        安装实例（自动安装模组加载器 最新版）")
    print("  \"CM Launcher.exe\" -install game <版本> with <模组加载器>   专业安装（手动选加载器版本）")
    print("  \"CM Launcher.exe\" -download list                    查看可下载版本")
    print()
    print("其他命令：")
    print("  \"CM Launcher.exe\" -list accounts                   查看离线账户")
    print("  \"CM Launcher.exe\" -search java                     查看本机 Java")
    print("  \"CM Launcher.exe\" -instance list                   查看已登记实例与文件夹")
    print("  \"CM Launcher.exe\" -instance dir <实例名称>         查看实例文件夹")
    print("  \"CM Launcher.exe\" -instance open <实例名称>        打开实例文件夹")
    print("  \"CM Launcher.exe\" -instance move <名称> <新目录>   切换隔离实例文件夹")
    print("  \"CM Launcher.exe\" -instance memory <名称> <MB>     设置实例内存")
    print("  \"CM Launcher.exe\" -remove account <用户名>         删除离线账户")
    print("  \"CM Launcher.exe\" -help                            显示本帮助")
    print()
    print("可选参数：")
    print("  -u, --user <用户名>     指定登录账户")
    print("  --game-dir <目录>       指定 .minecraft 目录")
    print("  --java <路径>           指定 java.exe")
    print("  --dry-run               只打印启动命令，不启动游戏")
    print("  --wait                  等待游戏退出后返回（含日志）")
    print("  --deep                  深度搜索游戏目录")
    print("  --name <实例名>         安装时预先指定实例名称")
    print("  --isolate / --no-isolate 安装时预设是否版本隔离")
    print("  --memory <MB>           安装/启动时的最大内存")
    print("  --lang zh|en            界面语言")
    print()
    print("示例：")
    print("  \"CM Launcher.exe\" -crate a new player Steve")
    print("  \"CM Launcher.exe\" -download game 1.20.1")
    print("  \"CM Launcher.exe\" -install game 1.20.1-forge")
    print("  \"CM Launcher.exe\" -search game")
    print("  \"CM Launcher.exe\" -start game 1.20.1-forge-47.2.0")
    print("  \"CM Launcher.exe\" -start game 1.20.1 -u Steve --dry-run")


def collect_dirs(options: dict, config: Config, deep: bool, force_deep: bool = False) -> list:
    extra = []
    if options.get("game_dir"):
        path = Path(options["game_dir"]).expanduser()
        if not path.is_dir():
            raise UsageError(f"游戏目录不存在：{path}")
        extra.append(path)
    return find_game_dirs(
        configured=config.game_dirs(),
        extra=extra,
        deep=deep,
        force_deep=force_deep,
    )


def cmd_create(words: list[str], options: dict, store: AccountStore) -> int:
    if [word.lower() for word in words[:3]] == ["a", "new", "player"]:
        words = words[3:]
    if not words:
        ui.section(t("创建离线账户", "Create offline account"))
        name = ui.ask(t("请输入用户名（3-16 位字母/数字/下划线）",
                        "Username (3-16 letters/digits/underscore)"))
        if not name:
            ui.warn(t("已取消。", "Cancelled."))
            return 1
        words = [name]
    if len(words) != 1:
        raise UsageError("用户名不能包含空格。用法：-crate a new player <用户名>")
    account, created = store.create(words[0])
    if created:
        ui.ok(t(f"离线账户已创建：{account.name}", f"Offline account created: {account.name}"))
    else:
        ui.warn(t(f"账户已存在：{account.name}", f"Account already exists: {account.name}"))
    ui.detail(t(f"UUID：{account.uuid}", f"UUID: {account.uuid}"))
    ui.detail(t(f"账户文件：{store.path}", f"Account file: {store.path}"))
    if created:
        ui.detail(t("启动游戏时会自动使用该账户登录。",
                    "This account will be used automatically when launching."))
    return 0


def _status_text(status: str) -> str:
    if not i18n.is_en():
        return status
    return {
        "就绪": "Ready",
        "缺客户端": "No client",
        "缺资源": "No assets",
        "缺客户端/资源": "Missing files",
        "损坏": "Broken",
    }.get(status, status)


def cmd_search_game(options: dict, config: Config) -> int:
    deep = bool(options.get("deep") or config.get("deep_search"))
    dirs = collect_dirs(options, config, deep, force_deep=bool(options.get("deep")))
    if not dirs:
        ui.warn("未找到游戏目录。")
        ui.detail("请用 --game-dir <目录> 指定 .minecraft 文件夹。")
        return 1

    ui.section("游戏实例")
    instance_store = InstanceStore()
    aliases = {
        (os.path.normcase(str(Path(item.game_dir))), item.version_id): item.name
        for item in instance_store.all()
    }
    total = 0
    ready = 0
    for number, game in enumerate(dirs, 1):
        infos = scan_versions(game.path)
        ui.info(f"[{number}] {game.path}  ({game.source})")
        if not infos:
            ui.detail("没有版本实例。")
            continue
        rows = []
        for index, info in enumerate(infos, 1):
            version = info.base_version or "-"
            status = info.status
            if status == "就绪":
                ready += 1
            total += 1
            alias = aliases.get((os.path.normcase(str(game.path)), info.name), info.name)
            rows.append([index, alias, info.name, version, info.loader_text, _status_text(status)])
        ui.table(
            ["#", t("实例名称", "Instance"), t("版本目录", "Version folder"),
             t("游戏版本", "Game version"), t("加载器", "Loader"), t("状态", "Status")],
            rows,
            aligns=["right", "left", "left", "left", "left", "left"],
            max_widths=[4, 24, 44, 12, 28, 16],
        )
    ui.info(t(f"共 {len(dirs)} 个游戏目录，{total} 个实例，{ready} 个文件就绪。",
              f"{len(dirs)} game folder(s), {total} instance(s), {ready} ready."))
    ui.detail(t("启动命令：\"CM Launcher.exe\" -start game <实例名称>",
                "Launch: \"CM Launcher.exe\" -start game <instance>"))
    return 0


def cmd_download_list(words: list[str]) -> int:
    channel = words[0].lower() if words else "release"
    if channel not in ("release", "snapshot", "all"):
        raise UsageError("用法：-download list [release|snapshot|all]")
    try:
        versions, latest = list_versions(channel, 30)
    except DownloadError as exc:
        ui.error(str(exc))
        return 1
    ui.section(t("可下载版本", "Downloadable versions"))
    rows = [[index, item.get("id"), item.get("type"), str(item.get("releaseTime") or "")[:10]]
            for index, item in enumerate(versions, 1)]
    ui.table([t("#", "#"), t("版本", "Version"), t("类型", "Type"), t("发布时间", "Released")],
             rows, aligns=["right", "left", "left", "left"], max_widths=[4, 18, 10, 12])
    ui.info(t(f"最新正式版：{latest.get('release')}    最新快照：{latest.get('snapshot')}",
              f"Latest release: {latest.get('release')}    Latest snapshot: {latest.get('snapshot')}"))
    ui.detail(t("下载：\"CM Launcher.exe\" -download game <版本>",
                "Download: \"CM Launcher.exe\" -download game <version>"))
    return 0


def _ask_instance(name: str, default_name: str, options: dict, store: InstanceStore):
    instance_name = options.get("instance_name") or name
    if not instance_name:
        instance_name = ui.ask(t("实例名称", "Instance name"), default_name).strip()
    if not instance_name:
        raise UsageError(t("实例名称不能为空。", "Instance name cannot be empty."))
    for _ in range(5):
        if not store.get(instance_name):
            break
        ui.warn(t(f"实例名称已存在：{instance_name}", f"Instance name already exists: {instance_name}"))
        instance_name = ui.ask(t("请换一个实例名称", "Choose another instance name"), instance_name + "-2").strip()
    else:
        raise UsageError(t("实例名称重复次数过多。", "Too many duplicate instance names."))

    if options.get("isolate"):
        isolated = True
    elif options.get("no_isolate"):
        isolated = False
    else:
        isolated = ui.ask(t("是否版本隔离（mods/saves 独立）? (y/N)",
                            "Isolate version (separate mods/saves)? (y/N)"), "n").strip().lower() in ("y", "yes", "是")

    if options.get("memory") is not None:
        try:
            memory = int(options["memory"] or 0)
        except ValueError:
            raise UsageError(t("--memory 需要整数（MB）。", "--memory must be an integer (MB)."))
    else:
        raw = ui.ask(t("最大内存 MB（0=自动）", "Max memory MB (0=auto)"), "0").strip()
        memory = int(raw) if raw.isdigit() else 0
    if memory < 0:
        memory = 0
    return instance_name, isolated, memory


def _parse_game_target(name: str) -> tuple[str, str, bool]:
    words = name.split()
    professional = "with" in [word.lower() for word in words]
    loader_text = ""
    base = name
    if professional:
        index = [word.lower() for word in words].index("with")
        base = " ".join(words[:index]).strip()
        loader_text = " ".join(words[index + 1:]).strip()
    if not loader_text:
        match = re.search(r"(neoforge|neo-forge|forge|fabric|quilt)", base, re.IGNORECASE)
        if match:
            loader_text = match.group(1)
            base = (base[:match.start()] + base[match.end():]).strip()
    mc_match = re.search(r"\d+\.\d+(?:\.\d+)?", base or name)
    if not mc_match:
        raise UsageError("用法：-install game <游戏版本>[-forge|neoforge|fabric]")
    return mc_match.group(0), loader_text, professional


def _ensure_game_dir(options: dict, config: Config) -> Path:
    explicit = options.get("game_dir")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_dir():
            raise UsageError(f"游戏目录不存在：{path}")
        config.set("game_dir", str(path))
        config.set("game_dir_configured", True)
        return path

    configured = config.get("game_dir")
    if config.get("game_dir_configured") and configured:
        path = Path(configured)
        if path.resolve() == app_dir().resolve():
            # 兼容 1.0.0：旧版本把游戏文件直接放在启动器根目录。
            target = app_dir() / ".minecraft"
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                for name in ("versions", "libraries", "assets", "mods", "saves",
                             "config", "resourcepacks", "shaderpacks", "logs", "options.txt"):
                    source = path / name
                    if source.exists():
                        try:
                            shutil.move(str(source), str(target / name))
                        except OSError:
                            pass
            config.set("game_dir", str(target))
            return target
        return path

    ui.info(t("首次安装实例，请先确定游戏实例文件夹。",
              "First installation: choose the game instance folder."))
    answer = ui.ask(
        t(f"是否把实例文件放在启动器文件夹下的 .minecraft？\n  {app_dir() / '.minecraft'}\n(y/N)",
          f"Put instance files in the launcher folder's .minecraft?\n  {app_dir() / '.minecraft'}\n(y/N)"),
        "y",
    ).strip().lower()
    if answer in ("y", "yes", "是"):
        path = app_dir() / ".minecraft"
    else:
        selected = pick_folder(t("选择游戏实例文件夹（将存放 versions/libraries/assets）",
                                 "Select game instance folder (versions/libraries/assets)"))
        if selected is None:
            raise UsageError(t("未选择游戏实例文件夹，已取消安装。",
                               "No game folder selected; installation cancelled."))
        path = selected
    path.mkdir(parents=True, exist_ok=True)
    config.set("game_dir", str(path))
    config.set("game_dir_configured", True)
    ui.ok(t(f"游戏实例文件夹已确定：{path}", f"Game folder set to: {path}"))
    return path


def cmd_download_game(name: str, options: dict, config: Config) -> int:
    """只补全文件，不创建/登记实例。"""
    name = (name or "").strip().strip('"').strip("'")
    if not name:
        return cmd_download_list(["release"])
    _ensure_game_dir(options, config)
    dirs = collect_dirs(options, config, deep=False)
    game_dir = dirs[0].path if dirs else default_game_dir(config)

    store = InstanceStore()
    record = store.get(name)
    if record:
        game_dir = Path(record.game_dir)
        version_id = record.version_id
    else:
        exact = [
            (Path(item.path), item.path / "versions" / name / f"{name}.json")
            for item in dirs
        ]
        found = next((path for _root, path in exact if path.is_file()), None)
        if found:
            version_id = name
        else:
            mc, loader_text, _professional = _parse_game_target(name)
            if loader_text:
                raise UsageError(
                    t("补全文件不安装加载器；安装带加载器的实例请用：\n"
                      f"  \"CM Launcher.exe\" -install game {name}",
                      "Fill-only mode does not install loaders; use:\n"
                      f"  \"CM Launcher.exe\" -install game {name}")
                )
            version_id = mc
    try:
        download_install(game_dir, version_id)
    except DownloadError as exc:
        ui.error(str(exc))
        return 1
    return 0


def cmd_install_game(name: str, options: dict, config: Config) -> int:
    name = (name or "").strip().strip('"').strip("'")
    if not name:
        raise UsageError("用法：-install game <游戏版本>[-forge|neoforge|fabric]")
    mc, loader_text, professional = _parse_game_target(name)

    _ensure_game_dir(options, config)
    dirs = collect_dirs(options, config, deep=False)
    game_dir = dirs[0].path if dirs else default_game_dir(config)
    store = InstanceStore()

    selection = None
    if loader_text:
        try:
            selection = loaders.choose_loader(mc, loader_text, professional)
        except loaders.LoaderError as exc:
            ui.error(str(exc))
            return 1

    default_name = f"{mc}-{loader_text.lower()}" if loader_text else mc
    instance_name, isolated, memory = _ask_instance("", default_name, options, store)
    instance_dir = game_dir / "instances" / safe_folder_name(instance_name) if isolated else None
    if instance_dir:
        for sub in ("mods", "saves", "config", "resourcepacks", "shaderpacks", "logs"):
            (instance_dir / sub).mkdir(parents=True, exist_ok=True)
    mods_dir = (instance_dir / "mods") if instance_dir else (game_dir / "mods")

    try:
        if loader_text:
            version_id = loaders.install_loader(
                game_dir, mc, loader_text, config,
                interactive=professional, mods_dir=mods_dir,
                selection=selection,
            )
        else:
            download_install(game_dir, mc)
            version_id = mc
    except (loaders.LoaderError, DownloadError) as exc:
        ui.error(str(exc))
        return 1

    if loader_text:
        version_id = loaders.adopt_loader_folder(game_dir, version_id, instance_name)
    loaders.cleanup_installer_residue(game_dir, version_id)

    store.add(instance_name, version_id, game_dir, instance_dir, isolated, memory)
    ui.ok(t(f"实例「{instance_name}」登记完成，版本目录：{version_id}",
            f"Instance '{instance_name}' registered (version folder: {version_id})."))
    ui.detail(t(f"游戏目录：{instance_dir or game_dir}；内存：{memory or '自动'} MB",
                f"Game folder: {instance_dir or game_dir}; memory: {memory or 'auto'} MB"))
    ui.detail(t(f"启动：\"CM Launcher.exe\" -start game {instance_name}",
                f"Launch: \"CM Launcher.exe\" -start game {instance_name}"))
    return 0


def cmd_search_java() -> int:
    javas = discover_javas(Config.load())
    ui.section("本机 Java")
    if not javas:
        ui.warn("未找到 Java。")
        ui.detail("安装 Java 21（新版）或 Java 8（旧版）后重试。")
        return 1
    rows = [[index, f"Java {java.major}", java.version, str(java.path)] for index, java in enumerate(javas, 1)]
    ui.table(
        ["#", "版本", "完整版本", "路径"],
        rows,
        aligns=["right", "left", "left", "left"],
        max_widths=[4, 10, 24, 64],
    )
    ui.detail("可用 --java <路径> 强制指定。")
    return 0


def cmd_list_accounts(store: AccountStore) -> int:
    accounts = store.all()
    ui.section("离线账户")
    if not accounts:
        ui.warn("还没有账户。")
        ui.detail("创建：\"CM Launcher.exe\" -crate a new player <用户名>")
        return 1
    rows = []
    for index, account in enumerate(accounts, 1):
        mark = "默认" if store.last_account.lower() == account.name.lower() else ""
        rows.append([index, account.name, account.uuid, account.created_at, mark])
    ui.table(
        ["#", "用户名", "UUID", "创建时间", "默认"],
        rows,
        aligns=["right", "left", "left", "left", "left"],
        max_widths=[4, 20, 38, 26, 6],
    )
    return 0


def cmd_remove_account(words: list[str], store: AccountStore) -> int:
    if [word.lower() for word in words[:1]] == ["account"]:
        words = words[1:]
    if not words:
        raise UsageError("用法：-remove account <用户名>")
    name = words[0]
    if not store.get(name):
        ui.warn(f"账户不存在：{name}")
        return 1
    store.delete(name)
    ui.ok(f"已删除账户：{name}")
    return 0


def _pick_instance(infos: list[VersionInfo], name: str) -> tuple[VersionInfo | None, list[VersionInfo]]:
    exact = [info for info in infos if info.ok and info.name.lower() == name.lower()]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        usable = [info for info in exact if info.client_jar and info.client_jar.is_file()]
        if len(usable) == 1:
            return usable[0], []
        return None, exact
    return find_instance(infos, name)


def _show_ambiguous(name: str, candidates: list[VersionInfo]) -> None:
    if not candidates:
        ui.error(f"未找到实例「{name}」。")
        ui.detail("运行 \"CM Launcher.exe\" -search game 查看可用实例名称。")
        return
    ui.error(f"实例「{name}」不唯一或未找到，候选如下：")
    rows = [[info.name, info.loader_text, str(info.game_dir)] for info in candidates]
    ui.table(
        ["实例名称", "加载器", "游戏目录"],
        rows,
        max_widths=[44, 24, 70],
    )
    ui.detail("可用 --game-dir 指定游戏目录，或输入更完整的实例名称。")


def cmd_instance(words: list[str], options: dict) -> int:
    store = InstanceStore()
    action = words[0].lower() if words else "list"
    if action in ("list", "ls"):
        items = store.all()
        ui.section("实例列表")
        if not items:
            ui.warn("还没有登记实例。")
            ui.detail("安装：\"CM Launcher.exe\" -download game 1.20.1-forge")
            return 1
        rows = [
            [item.name, item.version_id, "是" if item.isolated else "否",
             str(item.memory_mb or "自动"), item.instance_dir or item.game_dir]
            for item in items
        ]
        ui.table(["实例名称", "版本目录", "隔离", "内存MB", "游戏目录"], rows,
                 max_widths=[24, 42, 6, 8, 64])
        return 0

    if action in ("dir", "path", "open"):
        if len(words) < 2:
            raise UsageError("用法：-instance dir <实例名称>")
        item = store.get(" ".join(words[1:]))
        if not item:
            ui.error("实例不存在。")
            return 1
        folder = Path(item.instance_dir) if item.isolated and item.instance_dir else Path(item.game_dir)
        ui.info(str(folder))
        if action == "open":
            try:
                os.startfile(str(folder))  # type: ignore[attr-defined]
            except (AttributeError, OSError) as exc:
                ui.warn(f"无法打开文件夹：{exc}")
        return 0

    if action in ("move", "switch"):
        if len(words) < 3:
            raise UsageError("用法：-instance move <实例名称> <新文件夹>")
        item = store.get(words[1])
        if not item:
            ui.error("实例不存在。")
            return 1
        if not item.isolated or not item.instance_dir:
            ui.error("只有隔离实例才能移动文件夹。")
            return 1
        source = Path(item.instance_dir)
        target = Path(" ".join(words[2:])).expanduser().resolve()
        if target.exists() and any(target.iterdir()):
            ui.error(f"目标文件夹非空：{target}")
            return 1
        if target.exists():
            target.rmdir()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        item.instance_dir = str(target)
        store.update(item)
        ui.ok(f"实例「{item.name}」文件夹已切换到：{target}")
        return 0

    if action in ("memory", "mem"):
        if len(words) < 3:
            raise UsageError("用法：-instance memory <实例名称> <MB，0=自动>")
        item = store.get(words[1])
        if not item:
            ui.error("实例不存在。")
            return 1
        try:
            item.memory_mb = max(0, int(words[2]))
        except ValueError:
            raise UsageError("内存需要整数（MB）。")
        store.update(item)
        ui.ok(f"实例「{item.name}」内存已设为 {item.memory_mb or '自动'} MB。")
        return 0

    raise UsageError("用法：-instance list | dir | open | move | memory")


def cmd_start_game(name: str, options: dict, config: Config, store: AccountStore) -> int:
    name = (name or "").strip().strip('"').strip("'")
    if not name:
        raise UsageError("用法：-start game <实例名称>")

    instance_store = InstanceStore()
    record = instance_store.get(name)
    runtime_dir = None
    memory_override = 0
    if options.get("memory"):
        try:
            memory_override = max(0, int(options["memory"]))
        except ValueError:
            raise UsageError("--memory 需要整数（MB）。")
    display_name = name

    if record:
        game_dir = Path(record.game_dir)
        infos = scan_versions(game_dir)
        info = next((item for item in infos if item.ok and item.name == record.version_id), None)
        if info is None:
            ui.error(f"实例「{record.name}」的版本目录不存在：{record.version_id}")
            ui.detail(str(game_dir / 'versions' / record.version_id))
            return 1
        if record.isolated and record.instance_dir:
            runtime_dir = Path(record.instance_dir)
        if not memory_override and record.memory_mb:
            memory_override = record.memory_mb
        display_name = record.name
    else:
        dirs = collect_dirs(
            options,
            config,
            bool(options.get("deep") or config.get("deep_search")),
            force_deep=bool(options.get("deep")),
        )
        if not dirs:
            ui.error("未找到游戏目录。")
            ui.detail("请用 --game-dir <目录> 指定 .minecraft 文件夹。")
            return 1
        infos = []
        for game in dirs:
            infos.extend(scan_versions(game.path))
        if not infos:
            ui.error("游戏目录中没有可用实例。")
            ui.detail("请先用Minecraft 官方客户端安装游戏版本。")
            return 1
        info, candidates = _pick_instance(infos, name)
        if info is None:
            _show_ambiguous(name, candidates)
            return 1

    account = store.default(options.get("user"))
    if options.get("user") and account is None:
        ui.error(f"指定账户不存在：{options['user']}")
        ui.detail("创建：\"CM Launcher.exe\" -crate a new player <用户名>")
        return 1
    if account is None:
        ui.error("还没有离线账户，无法登录。")
        ui.detail("创建：\"CM Launcher.exe\" -crate a new player <用户名>")
        return 1

    if options.get("java"):
        config.set("java_path", options["java"], save=False)
    if options.get("game_dir"):
        config.set("game_dir", str(Path(options["game_dir"]).resolve()), save=False)

    try:
        plan = build_plan(
            info, account, config,
            game_directory=runtime_dir,
            memory_mb=memory_override,
        )
    except LaunchError as exc:
        ui.error(str(exc))
        return 1
    except JavaError as exc:
        ui.error(str(exc))
        return 1

    for warning in plan.warnings:
        ui.warn(warning)

    ui.section(t("启动信息", "Launch details"))
    memory = next((arg for arg in plan.command if arg.startswith("-Xmx")), "-")
    rows = [
        [t("实例名称", "Instance"), display_name],
        [t("版本目录", "Version folder"), info.name],
        [t("游戏版本", "Game version"), info.base_version],
        [t("加载器", "Loader"), info.loader_text],
        [t("登录账户", "Account"), t(f"{account.name}（离线）", f"{account.name} (offline)")],
        ["UUID", account.uuid],
        ["Java", f"Java {plan.java.major}  {plan.java.path}"],
        [t("内存", "Memory"), memory.lstrip("-")],
        [t("游戏目录", "Game folder"), str(plan.cwd)],
    ]
    ui.table([t("项目", "Item"), t("内容", "Value")], rows, max_widths=[12, 90])
    ui.detail(t(f"日志文件：{plan.log_path}", f"Log file: {plan.log_path}"))

    if options.get("dry_run"):
        ui.section(t("启动命令（dry-run，不实际执行）", "Launch command (dry-run)"))
        print(format_command(plan.command))
        return 0

    store.touch(account)
    try:
        return execute(plan, wait=bool(options.get("wait")), close_console=True)
    except LaunchError as exc:
        ui.error(str(exc))
        return 1


def interactive() -> int:
    config = Config.load()
    store = AccountStore()
    ui.banner()
    while True:
        print()
        print("  1. 创建离线账户")
        print("  2. 搜索游戏实例")
        print("  3. 启动游戏")
        print("  4. 查看账户")
        print("  0. 退出")
        choice = ui.ask("请选择", "0").lower()
        try:
            if choice in ("1", "c", "create"):
                cmd_create([], {}, store)
            elif choice in ("2", "s", "search"):
                cmd_search_game({}, config)
            elif choice in ("3", "l", "launch", "start"):
                cmd_search_game({}, config)
                name = ui.ask("输入要启动的实例名称")
                if name:
                    cmd_start_game(name, {}, config, store)
            elif choice in ("4", "a", "account"):
                cmd_list_accounts(store)
            elif choice in ("0", "q", "quit", "exit"):
                ui.info("再见。")
                return 0
            else:
                ui.warn("无效选项。")
        except (UsageError, AccountError) as exc:
            ui.error(str(exc))
        except KeyboardInterrupt:
            print()
            ui.info("已取消。")
        if not sys.stdin or sys.stdin.closed:
            return 0


def run(args: list[str]) -> int:
    options, rest = parse_options(args)
    config = Config.load()
    if options.get("lang"):
        i18n.set_lang(options["lang"])
        config.set("lang", i18n.LANG)
    else:
        i18n.set_lang(config.get("lang") or None)
    if options.get("help") or not rest:
        help_text()
        return 0

    command = rest[0].lower().lstrip("-")
    words = rest[1:]
    store = AccountStore()

    if command in ("crate", "create", "new"):
        return cmd_create(words, options, store)
    if command == "search":
        target = words[0].lower() if words else "game"
        if target in ("game", "games", "版本", "实例"):
            return cmd_search_game(options, config)
        if target in ("java", "jdk"):
            return cmd_search_java()
        if target in ("account", "accounts", "user", "users"):
            return cmd_list_accounts(store)
        raise UsageError("用法：-search game | -search java | -search accounts")
    if command == "start":
        target = words[0].lower() if words else ""
        instance = " ".join(words[1:] if target in ("game", "games", "版本") else words)
        return cmd_start_game(instance, options, config, store)
    if command in ("download", "dl"):
        target = words[0].lower() if words else "list"
        if target in ("list", "versions", "版本"):
            return cmd_download_list(words[1:])
        if target in ("game", "version", "missing", "游戏"):
            return cmd_download_game(" ".join(words[1:]), options, config)
        raise UsageError("用法：-download list | -download game <版本>")
    if command in ("install", "setup"):
        target = words[0].lower() if words else ""
        if target in ("game", "version", "游戏"):
            return cmd_install_game(" ".join(words[1:]), options, config)
        raise UsageError("用法：-install game <版本>[-forge|neoforge|fabric]")
    if command in ("list", "ls"):
        target = words[0].lower() if words else "accounts"
        if target in ("account", "accounts", "user", "users"):
            return cmd_list_accounts(store)
        if target in ("game", "games", "versions"):
            return cmd_search_game(options, config)
        if target in ("java", "jdk"):
            return cmd_search_java()
        raise UsageError("用法：-list accounts | -list versions | -list java")
    if command in ("instance", "instances"):
        return cmd_instance(words, options)
    if command in ("remove", "delete", "del"):
        return cmd_remove_account(words, store)
    if command in ("help", "?"):
        help_text()
        return 0
    raise UsageError(f"未知命令：{rest[0]}")


def show_no_args_guide() -> None:
    if i18n.is_en():
        text = (
            "Please do NOT start the launcher by double-clicking it.\n\n"
            "Open Command Prompt or PowerShell in the launcher folder:\n"
            "Shift + right-click the folder -> Open PowerShell here.\n\n"
            "Then run:\n"
            "  launcher.exe -help\n"
            "  launcher.exe -crate a new player <name>\n"
            "  launcher.exe -install game 1.20.1-forge\n"
            "  launcher.exe -start game <instance>\n\n"
            "Run launcher.exe -help for all commands."
        )
    else:
        text = (
            "请不要直接双击CM Launcher。\n\n"
            "请在CM Launcher所在文件夹打开命令提示符或 PowerShell：\n"
            "按住 Shift + 右键文件夹 -> 在此处打开 PowerShell窗口。\n\n"
            "完整启动器用法请运行 \"CM Launcher.exe\" -help 查看。"
        )
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x00000040)
            return
        except Exception:
            pass
    print(text)


def main(argv=None) -> int:
    ui.init_console()
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args:
            try:
                i18n.set_lang(Config.load().get("lang") or None)
            except OSError:
                i18n.set_lang(None)
            show_no_args_guide()
            return 0
        return run(args)
    except UsageError as exc:
        ui.error(str(exc))
        ui.detail(t("运行 \"CM Launcher.exe\" -help 查看用法。", "Run \"CM Launcher.exe\" -help for usage."))
        return 2
    except AccountError as exc:
        ui.error(str(exc))
        return 1
    except KeyboardInterrupt:
        print()
        ui.info(t("已取消。", "Cancelled."))
        return 130
    except OSError as exc:
        ui.error(t(f"文件操作失败：{exc}", f"File operation failed: {exc}"))
        return 1
    except Exception as exc:  # 版本 JSON 异常等，避免直接抛出堆栈
        ui.error(t(f"发生未预期的错误：{exc}", f"Unexpected error: {exc}"))
        ui.detail(t("可先用 --dry-run 检查启动命令，并把版本 JSON 与 data/logs 一并反馈。",
                    "Try --dry-run and check version JSON and data/logs."))
        return 1
