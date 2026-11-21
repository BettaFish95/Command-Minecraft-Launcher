"""本地自检：构造仿真实例，验证搜索、参数拼装与真实 Java 启动。

用法：python tests/selfcheck.py
不会改动真实 .minecraft；测试数据位于 tests/tmp。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(__file__).resolve().parent / "tmp"
MC = TMP / ".minecraft"
CLI = [sys.executable, str(ROOT / "CM Launcher.py")]

if os.name == "nt":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_jar(path: Path, files: dict[str, bytes] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        for name, payload in (files or {}).items():
            archive.writestr(name, payload)


def find_javac() -> Path:
    found = shutil.which("javac")
    if found:
        return Path(found)
    candidates = sorted(Path(r"C:\Program Files\Java").glob("jdk-*/bin/javac.exe"))
    if not candidates:
        raise SystemExit("未找到 javac，无法编译测试类。")
    return candidates[-1]


HELLO_TEMPLATE = """
public class {cls} {{
    public static void main(String[] args) {{
        String user = "?";
        for (int i = 0; i + 1 < args.length; i++) {{
            if (args[i].equals("--username")) user = args[i + 1];
        }}
        System.out.println("LAUNCH_OK {cls} user=" + user + " argc=" + args.length);
    }}
}}
"""


def build_fixture() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    MC.mkdir(parents=True)

    src = TMP / "src"
    src.mkdir()
    classes = {"Hello", "HelloForge", "HelloFabric", "HelloLegacy"}
    for name in classes:
        (src / f"{name}.java").write_text(HELLO_TEMPLATE.format(cls=name), encoding="utf-8")
    out = TMP / "classes"
    out.mkdir()
    subprocess.run(
        [str(find_javac()), "--release", "8", "-d", str(out)]
        + [str(src / f"{name}.java") for name in classes],
        check=True,
        capture_output=True,
    )
    make_jar(
        MC / "libraries" / "test" / "hello" / "1.0" / "hello-1.0.jar",
        {f"{name}.class": (out / f"{name}.class").read_bytes() for name in classes},
    )
    make_jar(MC / "libraries" / "net" / "minecraftforge" / "forge" / "1.20.1-47.2.0" / "forge-1.20.1-47.2.0.jar")
    make_jar(MC / "libraries" / "net" / "fabricmc" / "fabric-loader" / "0.15.11" / "fabric-loader-0.15.11.jar")
    make_jar(MC / "libraries" / "net" / "neoforged" / "neoforge" / "20.4.237" / "neoforge-20.4.237.jar")
    make_jar(
        MC / "libraries" / "net" / "minecraftforge" / "forge" / "1.12.2-14.23.5.2860" / "forge-1.12.2-14.23.5.2860-universal.jar"
    )
    make_jar(
        MC / "libraries" / "org" / "lwjgl" / "lwjgl" / "lwjgl-platform" / "2.9.4-nightly-20150209"
        / "lwjgl-platform-2.9.4-nightly-20150209.jar"
    )
    make_jar(
        MC / "libraries" / "org" / "lwjgl" / "lwjgl" / "lwjgl-platform" / "2.9.4-nightly-20150209"
        / "lwjgl-platform-2.9.4-nightly-20150209-natives-windows.jar",
        {"lwjgl64.dll": b"dummy-native"},
    )

    asset_index = {"objects": {}}
    for index in ("1.20.1", "1.12.2"):
        write_json(MC / "assets" / "indexes" / f"{index}.json", asset_index)

    base_game_args = [
        "--username", "${auth_player_name}",
        "--version", "${version_name}",
        "--gameDir", "${game_directory}",
        "--assetsDir", "${assets_root}",
        "--assetIndex", "${assets_index_name}",
        "--uuid", "${auth_uuid}",
        "--accessToken", "${auth_access_token}",
        "--userType", "${user_type}",
    ]
    write_json(MC / "versions" / "1.20.1" / "1.20.1.json", {
        "id": "1.20.1",
        "type": "release",
        "mainClass": "Hello",
        "assets": "1.20.1",
        "assetIndex": {"id": "1.20.1"},
        "javaVersion": {"component": "java-runtime-gamma", "majorVersion": 21},
        "libraries": [
            {"name": "test:hello:1.0", "downloads": {"artifact": {"path": "test/hello/1.0/hello-1.0.jar"}}},
        ],
        "arguments": {
            "game": base_game_args,
            "jvm": [
                "-Djava.library.path=${natives_directory}",
                "-cp", "${classpath}",
                "-Dminecraft.launcher.brand=${launcher_name}",
            ],
        },
    })
    make_jar(MC / "versions" / "1.20.1" / "1.20.1.jar")

    write_json(MC / "versions" / "1.20.1-forge-47.2.0" / "1.20.1-forge-47.2.0.json", {
        "id": "1.20.1-forge-47.2.0",
        "inheritsFrom": "1.20.1",
        "mainClass": "HelloForge",
        "libraries": [
            {"name": "net.minecraftforge:forge:1.20.1-47.2.0", "downloads": {"artifact": {"path": "net/minecraftforge/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0.jar"}}},
            {"name": "test:hello:1.0", "downloads": {"artifact": {"path": "test/hello/1.0/hello-1.0.jar"}}},
        ],
        "arguments": {
            "jvm": ["-DlibraryDirectory=${library_directory}"],
            "game": ["--launchTarget", "forgeclient"],
        },
    })

    write_json(MC / "versions" / "fabric-loader-0.15.11-1.20.1" / "fabric-loader-0.15.11-1.20.1.json", {
        "id": "fabric-loader-0.15.11-1.20.1",
        "inheritsFrom": "1.20.1",
        "mainClass": "HelloFabric",
        "libraries": [
            {"name": "net.fabricmc:fabric-loader:0.15.11", "downloads": {"artifact": {"path": "net/fabricmc/fabric-loader/0.15.11/fabric-loader-0.15.11.jar"}}},
        ],
    })

    write_json(MC / "versions" / "1.20.1-neoforge-20.4.237" / "1.20.1-neoforge-20.4.237.json", {
        "id": "1.20.1-neoforge-20.4.237",
        "inheritsFrom": "1.20.1",
        "mainClass": "cpw.mods.bootstraplauncher.BootstrapLauncher",
        "libraries": [
            {"name": "net.neoforged:neoforge:20.4.237", "downloads": {"artifact": {"path": "net/neoforged/neoforge/20.4.237/neoforge-20.4.237.jar"}}},
        ],
        "arguments": {
            "jvm": ["-DlibraryDirectory=${library_directory}"],
            "game": ["--launchTarget", "forgeclient", "--fml.neoForgeVersion", "20.4.237"],
        },
    })

    write_json(MC / "versions" / "1.12.2" / "1.12.2.json", {
        "id": "1.12.2",
        "type": "release",
        "mainClass": "HelloLegacy",
        "assets": "1.12.2",
        "assetIndex": {"id": "1.12.2"},
        "javaVersion": {"majorVersion": 8},
        "minecraftArguments": (
            "--username ${auth_player_name} --session ${auth_session} "
            "--gameDir ${game_directory} --assetsDir ${assets_root} "
            "--uuid ${auth_uuid} --version ${version_name}"
        ),
        "libraries": [
            {"name": "test:hello:1.0", "downloads": {"artifact": {"path": "test/hello/1.0/hello-1.0.jar"}}},
        ],
    })
    make_jar(MC / "versions" / "1.12.2" / "1.12.2.jar")

    write_json(MC / "versions" / "1.12.2-forge-14.23.5.2860" / "1.12.2-forge-14.23.5.2860.json", {
        "id": "1.12.2-forge-14.23.5.2860",
        "inheritsFrom": "1.12.2",
        "mainClass": "HelloLegacy",
        "minecraftArguments": (
            "--username ${auth_player_name} --session ${auth_session} "
            "--gameDir ${game_directory} --assetsDir ${assets_root} "
            "--uuid ${auth_uuid} --tweakClass net.minecraftforge.fml.common.launcher.FMLTweaker"
        ),
        "libraries": [
            {"name": "net.minecraftforge:forge:1.12.2-14.23.5.2860:universal", "downloads": {"artifact": {"path": "net/minecraftforge/forge/1.12.2-14.23.5.2860/forge-1.12.2-14.23.5.2860-universal.jar"}}},
            {
                "name": "org.lwjgl.lwjgl:lwjgl-platform:2.9.4-nightly-20150209",
                "natives": {"windows": "natives-windows"},
                "downloads": {
                    "artifact": {"path": "org/lwjgl/lwjgl/lwjgl-platform/2.9.4-nightly-20150209/lwjgl-platform-2.9.4-nightly-20150209.jar"},
                    "classifiers": {
                        "natives-windows": {"path": "org/lwjgl/lwjgl/lwjgl-platform/2.9.4-nightly-20150209/lwjgl-platform-2.9.4-nightly-20150209-natives-windows.jar"}
                    },
                },
            },
            {"name": "test:hello:1.0", "downloads": {"artifact": {"path": "test/hello/1.0/hello-1.0.jar"}}},
        ],
    })


def run(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        CLI + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
    )


def expect(condition: bool, message: str, output: str = "") -> None:
    if not condition:
        print(output)
        raise AssertionError(message)


def latest_log() -> str:
    logs = sorted((ROOT / "data" / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1].read_text(encoding="utf-8", errors="replace") if logs else ""


def main() -> int:
    build_fixture()
    print("fixture:", MC)

    result = run("-search", "game", "--game-dir", str(MC))
    print(result.stdout)
    expect(result.returncode == 0, f"search 退出码 {result.returncode}", result.stderr)
    for text in ("原版", "Forge 47.2.0", "Fabric 0.15.11", "NeoForge 20.4.237", "Forge 14.23.5.2860"):
        expect(text in result.stdout, f"搜索结果缺少 {text}")

    run("-remove", "account", "SelfCheck")
    result = run("-crate", "a", "new", "player", "SelfCheck")
    expect(result.returncode == 0 and "已创建" in result.stdout, "创建账户失败", result.stdout + result.stderr)

    dry = run("-start", "game", "1.20.1-forge-47.2.0", "--game-dir", str(MC), "--dry-run")
    print(dry.stdout[-4000:])
    expect(dry.returncode == 0, f"dry-run 退出码 {dry.returncode}", dry.stderr)
    for token in (
        "HelloForge",
        "forge-1.20.1-47.2.0.jar",
        "hello-1.0.jar",
        "-DlibraryDirectory=",
        "-Dfml.ignoreInvalidMinecraftCertificates=true",
        "--launchTarget",
        "--username SelfCheck",
        "1.20.1-forge-47.2.0",
    ):
        expect(token in dry.stdout, f"启动命令缺少 {token}")

    dry_neo = run("-start", "game", "1.20.1-neoforge-20.4.237", "--game-dir", str(MC), "--dry-run")
    expect(dry_neo.returncode == 0, "NeoForge dry-run 失败", dry_neo.stderr)
    expect("BootstrapLauncher" in dry_neo.stdout and "-DlibraryDirectory=" in dry_neo.stdout, "NeoForge 参数缺失")
    expect("--fml.neoForgeVersion" in dry_neo.stdout, "NeoForge 游戏参数缺失")

    dry_legacy = run("-start", "game", "1.12.2-forge-14.23.5.2860", "--game-dir", str(MC), "--dry-run")
    expect(dry_legacy.returncode == 0, "旧版 Forge dry-run 失败", dry_legacy.stderr)
    natives = MC / "versions" / "1.12.2-forge-14.23.5.2860" / "natives" / "lwjgl64.dll"
    expect(natives.is_file(), "natives 未解压")
    expect("Java 8" in dry_legacy.stdout, "旧版未选择 Java 8")

    for name in ("1.20.1", "1.20.1-forge-47.2.0", "fabric-loader-0.15.11-1.20.1", "1.12.2-forge-14.23.5.2860"):
        result = run("-start", "game", name, "--game-dir", str(MC), "--wait")
        print(f"\n== 启动 {name} ==")
        print(result.stdout)
        expect(result.returncode == 0, f"{name} 启动失败", result.stderr)
        expect("游戏已正常退出" in result.stdout, f"{name} 未正常退出")
        log = latest_log()
        expect("LAUNCH_OK" in log, f"{name} 的 Java 输出未写入日志：{log[-500:]}")

    run("-remove", "account", "SelfCheck")
    print("\nSELF CHECK PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print("SELF CHECK FAILED:", exc)
        raise SystemExit(1)
