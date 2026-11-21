# CM Launcher

[中文](README.md) | [English](README.en.md)

Minecraft Java 版命令行工具（Python 3，纯标准库；已打包为免解压的 `"CM Launcher.exe"` + `_internal` 目录）。

> 作者学业繁忙，软件更新会较缓慢，感谢理解。

## 命令

```bat
"CM Launcher.exe" -crate a new player Steve           :: 创建离线账户（UUID 随机）
"CM Launcher.exe" -search game                        :: 自动定位游戏目录并列出实例
"CM Launcher.exe" -start game 1.20.1-forge-47.2.0     :: 启动指定实例
"CM Launcher.exe" -download game 1.20.1               :: 只补全文件，不建实例
"CM Launcher.exe" -install game 1.20.1-forge          :: 安装/登记带加载器的实例
"CM Launcher.exe" -download list                      :: 查看可下载版本
"CM Launcher.exe" -list accounts                      :: 查看账户
"CM Launcher.exe" -search java                        :: 查看本机 Java
"CM Launcher.exe" -start game 1.20.1 --dry-run        :: 只打印完整启动命令，便于排错
```

`-create` 是 `-crate` 的等价别名；`-start game` 后的实例名可以包含空格。

### 语言

```bat
"CM Launcher.exe" --lang en -help
"CM Launcher.exe" --lang zh -help
```

也可以用 `--lang en` 配合其他命令。语言会保存到 `data/config.json`；首次运行按 Windows 系统语言自动选择。直接双击 CM Launcher 不会进入游戏，而是弹出提示窗口，要求从命令行使用。

可选参数：

| 参数 | 作用 |
| --- | --- |
| `-u, --user <名字>` | 指定离线账户；默认使用最近使用的账户 |
| `--game-dir <目录>` | 指定 `.minecraft` 目录 |
| `--java <路径>` | 指定 `java.exe` |
| `--dry-run` | 打印启动命令，不启动游戏 |
| `--wait` | 等待游戏退出并输出失败日志末尾 |
| `--deep` | 深度搜索游戏目录 |
| `--name <实例名>` | 安装时预先指定实例名称 |
| `--isolate` / `--no-isolate` | 安装时预设是否版本隔离 |
| `--memory <MB>` | 安装或启动时的最大内存 |

无参数双击运行会进入交互菜单。

## 自动定位游戏目录

按以下顺序查找，找到多个时全部显示：

1. `--game-dir` / `data/config.json` 的 `game_dir`
2. `%APPDATA%\.minecraft`（Minecraft 官方客户端）
3. CM Launcher所在目录及 `instances/` 下的便携实例
4. `launcher_profiles.json` 中自定义的 `gameDirectory`
5. 以上都没有时，在用户目录与非系统盘做限时深度搜索（`--deep`）

实例就是 `versions/<名称>/<名称>.json`。CM Launcher会解析 `inheritsFrom` 继承链，合并库、参数、主类，并通过库名和主类识别 **原版 / Forge / NeoForge / Fabric / Quilt / OptiFine**。

### 首次安装：选择游戏文件夹

第一次执行 `-install game ...` 或 `-download game ...` 时会询问一次：

1. 是否把实例文件放在CM Launcher所在文件夹（默认是）；
2. 选否则弹出 Windows 原生文件夹选择窗口，由用户指定游戏实例文件夹。

选择结果写入 `data/config.json`（`game_dir`、`game_dir_configured`），之后不再重复询问，也不会默认使用 `%APPDATA%\.minecraft`。用 `--game-dir` 可随时覆盖并记住新目录。

## 下载

```bat
"CM Launcher.exe" -download list                 :: 查看可下载版本
"CM Launcher.exe" -download game 1.20.1          :: 只补全文件，不创建实例
"CM Launcher.exe" -download game 1.20.1 --game-dir "D:\MC\.minecraft"
```

`-download game` 只下载/补全版本 JSON、客户端 JAR、运行库、资源等文件，不会创建或登记实例。对已安装的 Forge/NeoForge/Fabric 实例，也可用同一命令补全缺失的运行库。

### 安装带模组加载器的实例

```bat
:: 普通安装：自动选该版本最新加载器，并登记实例
"CM Launcher.exe" -install game 1.20.1-forge
"CM Launcher.exe" -install game 1.20.1-neoforge
"CM Launcher.exe" -install game 1.20.1-fabric

:: 专业安装：先列出版本，由用户选择
"CM Launcher.exe" -install game 1.20.1 with forge
"CM Launcher.exe" -install game 1.20.1 with neoforge
"CM Launcher.exe" -install game 1.20.1 with fabric
```

- Forge/NeoForge：先装原版实例，再下载并运行对应安装器；完成后显示实际安装的加载器版本。
- Fabric：自动写入 Fabric Loader 配置并补全运行库；普通模式会同时把最新 Fabric API 下载到 `mods/`。
- Fabric 专业模式：先选择 Fabric Loader 版本，安装后再选择 Fabric API 版本下载到 `mods/`。
- 安装完成后会把加载器版本目录整理为实例名称目录，并清理 `.tmp`、`installer`、空目录等安装残留。

### 实例名称、版本隔离与内存

安装顺序：**游戏版本 → 模组加载器版本 → Fabric API 版本（仅 Fabric）→ 实例名称/隔离/内存**。

每次安装前会依次询问：
1. **实例名称**（可自定义，用于 `-start game <名称>`）
2. **是否版本隔离**：隔离后 mods/saves/config 放在 `.minecraft/instances/<名称>/`，不污染全局
3. **最大内存 MB**：0 表示自动

也可以用参数跳过询问：

```bat
"CM Launcher.exe" -install game 1.20.1-fabric --name MyPack --isolate --memory 4096
```

实例管理：

```bat
"CM Launcher.exe" -instance list
"CM Launcher.exe" -instance dir MyPack
"CM Launcher.exe" -instance open MyPack
"CM Launcher.exe" -instance move MyPack "D:\MC\MyPack"
"CM Launcher.exe" -instance memory MyPack 4096
```

启动时按实例登记的内存分配；`-start game MyPack --memory 8192` 可临时覆盖。

## 启动逻辑

- 按版本 JSON 的 `rules` 过滤 Windows/Linux/macOS、架构与 feature 参数。
- 库路径优先取 `downloads.artifact.path`，否则按 Maven 坐标推导；缺失库会明确列出并中止。
- 旧版 `natives` 映射自动解压到 `versions/<实例>/natives`；1.19+ 的 natives 库按官方方式进 classpath。
- 资源索引缺失会警告；1.6 及更早的 `virtual`/`map_to_resources` 资源会自动整理。
- Java 版本按 `javaVersion.majorVersion` 或游戏版本推断（1.20.5+ → 21，1.17+ → 17，旧版 → 8），自动从 PATH、`JAVA_HOME`、常见 JDK 安装目录、Minecraft 官方客户端 runtime、HMCL runtime 中挑选最合适的一个。
- 内存默认按物理内存自动分配（上限 8 GB），可在配置中固定。
- Forge：自动补 `-Dfml.ignoreInvalidMinecraftCertificates` 等兼容参数；1.13+ 的 `BootstrapLauncher` 自动补 `-DlibraryDirectory`。
- NeoForge：使用其 JSON 的 `--launchTarget` 参数并补 `-DlibraryDirectory`。
- Fabric/Quilt/OptiFine：完全按版本 JSON 的 `mainClass`、`tweakClass` 与库启动，不做硬编码。
- 启动前校验账户、客户端 JAR、运行库、资源索引；启动后 4 秒检测是否秒退，失败时打印日志末尾。
- Java 进程默认无窗口运行，完整输出写入 `data/logs/`。
- 启动前自动把游戏语言写为中文（1.13+ 为 `zh_cn`，旧版为 `zh_CN`），修改的是对应实例目录的 `options.txt`。

## 目录结构

```
CM Launcher.exe
_internal/              PyInstaller 运行库（必须与 exe 同目录）
CM Launcher.py         入口
mc_launcher/           CM Launcher 实现
  cli.py               命令解析、交互菜单
  launch.py            参数拼装、natives、进程启动
  versions.py          继承链、加载器识别、实例扫描
  download.py          版本/客户端/运行库/资源下载
  java.py              Java 探测与内存建议
  paths.py             游戏目录定位
  accounts.py          离线账户
  config.py            配置
  ui.py                控制台输出
data/                  运行时生成
  accounts.json
  config.json
  java_cache.json
  logs/
build.bat              一键打包
build.ps1              PowerShell 版打包脚本
```

## 配置

`data/config.json`（首次运行自动生成）：

```json
{
  "game_dir": "",
  "game_dir_configured": false,
  "extra_game_dirs": [],
  "java_path": "",
  "min_memory_mb": 512,
  "max_memory_mb": 0,
  "jvm_args": [],
  "game_args": [],
  "width": 0,
  "height": 0,
  "deep_search": true
}
```

`max_memory_mb: 0` 表示自动。`jvm_args` / `game_args` 会追加到启动命令。`deep_search` 控制“没有找到实例时是否兜底深度搜索”，命令行 `--deep` 则强制搜索。

## 构建

双击 `build.bat`，或：

```powershell
.\build.bat
```

依赖：Python 3.10+、PyInstaller。生成的是**免解压目录版**：`"CM Launcher.exe"` + `_internal/`，不再依赖系统 `TEMP`，也不会出现 `Could not create temporary directory`。分发时请整个文件夹一起复制。

## 说明与边界

- 离线账户 UUID 按需求随机生成（`uuid4`），仅用于本地与离线服务器登录；正版登录不在本版本范围。
- CM Launcher 只读取版本 JSON、库、资源并启动 Java；仅在实例目录写入 `natives/` 解压文件，旧版本还会整理 `assets/virtual` 与 `resources`。
- 当前版本要求实例已由 Minecraft 官方客户端、Forge/NeoForge/Fabric 安装器或第三方客户端安装完整；缺失文件会给出明确提示。下载/补全功能已预留模块边界，可在后续加入。
- 若实例启动失败，先加 `--dry-run` 检查命令，再看 `data/logs/` 中的完整日志。

## 常见问题

- **提示缺少客户端 JAR / 运行库**：直接执行 `-download game <版本>` 自动补全；Forge/NeoForge/Fabric 的运行库若缺失，也会按其 Maven 地址补全。
- **不要只复制 "CM Launcher.exe"**：目录版必须连同 `_internal/` 一起复制或移动。
- **Java 版本不匹配**：1.20.5+ 用 Java 21，1.17–1.20.4 用 Java 17，1.16.5 及更早用 Java 8。`-search java` 可查看本机版本，`--java <路径>` 可强制指定。
- **游戏秒退**：查看 `data/logs/` 最新日志；Forge 旧版请确认使用 Java 8，新版 Forge/NeoForge 请使用 Java 17/21。
- **单文件 exe 提示 `Failed to extract VCRUNTIME140.dll` 或 `Could not create temporary directory`**：本版本已改为目录版，不再解压到 `TEMP`；若仍遇到，请确认使用的是本目录下的 `"CM Launcher.exe"` 且 `_internal/` 完整。
- **中文乱码**：CM Launcher 会自动把控制台切到 UTF-8 并在退出时恢复；若仍乱码，请在 Windows Terminal 中运行。
