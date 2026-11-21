# CM Launcher

A command-line launcher for Minecraft Java Edition, written in Python 3.

> The author is busy with studies, so updates may be slow. Thank you for your understanding.

[English](README.en.md) | [中文](README.md)

## Features

- Offline accounts with random UUIDs.
- Automatic discovery of `.minecraft` folders and game instances.
- Version JSON inheritance, library resolution, natives extraction and asset handling.
- Launch support for Vanilla, Forge, NeoForge, Fabric, Quilt and OptiFine.
- Installer for Forge / NeoForge / Fabric, including Fabric API.
- Download or repair game files from BMCLAPI, with official Mojang fallback.
- Version isolation, custom instance names, per-instance memory.
- Automatic Chinese in-game language.
- Chinese / English launcher UI.

## Requirements

- Windows 10/11 (64-bit).
- The packaged build needs no Python installation.
- Java 8 for 1.16.5 and older, Java 17 for 1.17–1.20.4, Java 21 for 1.20.5+.

## Quick start

Do **not** double-click the EXE. Open PowerShell or Command Prompt in the launcher folder, then run:

```bat
"CM Launcher.exe" -help
"CM Launcher.exe" -crate a new player Steve
"CM Launcher.exe" -search game
"CM Launcher.exe" -start game MyPack
```

On the first install, CM Launcher asks whether to store game files in the launcher folder. Choose `n` to pick another folder with the native Windows folder dialog. The choice is saved; use `--game-dir <path>` to change it later.

## Install an instance

```bat
:: Latest loader version
"CM Launcher.exe" -install game 1.20.1-forge
"CM Launcher.exe" -install game 1.20.1-neoforge
"CM Launcher.exe" -install game 1.20.1-fabric

:: Choose loader version manually
"CM Launcher.exe" -install game 1.20.1 with fabric
```

The install flow asks for:

1. loader version (manual mode);
2. Fabric API version (Fabric only);
3. instance name;
4. version isolation;
5. maximum memory.

Non-interactive example:

```bat
"CM Launcher.exe" -install game 1.20.1-fabric --name MyPack --isolate --memory 4096
```

## Fill missing files

```bat
"CM Launcher.exe" -download game 1.20.1
"CM Launcher.exe" -download game MyPack
```

This only downloads or repairs files. It does not create or register an instance.

## Manage instances

```bat
"CM Launcher.exe" -instance list
"CM Launcher.exe" -instance dir MyPack
"CM Launcher.exe" -instance open MyPack
"CM Launcher.exe" -instance move MyPack "D:\MC\MyPack"
"CM Launcher.exe" -instance memory MyPack 4096
"CM Launcher.exe" -start game MyPack --memory 8192
```

## Language

```bat
"CM Launcher.exe" --lang en -help
"CM Launcher.exe" --lang zh -help
```

The choice is saved in `data/config.json`. On first run it follows the Windows UI language.

## Build

Double-click `build.bat`, or run:

```bat
build.bat
```

Requirements: Python 3.10+ and PyInstaller.

The build produces:

```text
CM Launcher.exe
_internal/
```

Keep both together. For distribution, zip the whole folder or publish `CM Launcher.exe` plus `_internal` in a GitHub Release.

## Notes

- The launcher expects the selected game version to be installed. `-download game` can fill missing vanilla files.
- Forge / NeoForge / Fabric loader installation requires network access and may take several minutes.
- Forge and NeoForge installers are run automatically; old Forge installers are handled by extracting their built-in profile.
- Logs are written to `data/logs/`.

## License

No license has been declared yet.
